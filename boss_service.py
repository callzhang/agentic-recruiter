#!/usr/bin/env python3
"""Async FastAPI service that automates Boss直聘 via Playwright."""

from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import sentry_sdk
from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.async_api import Browser, BrowserContext, Page, Playwright, TimeoutError as PlaywrightTimeoutError, async_playwright

from src import assistant_actions
from src.candidate_store import get_candidates, get_candidate_count, search_candidates_by_resume, upsert_candidate
from src.config import get_boss_zhipin_config, get_browser_config, get_service_config, get_sentry_config
from src.global_logger import logger
import src.chat_actions as chat_actions
import src.recommendation_actions as recommendation_actions

class BossServiceAsync:
    """Async Playwright driver exposed as FastAPI service.
    
    API Response Format (v2.2.0+):
        - Success: Returns data directly (dict/list/bool)
        - Failure: Returns {"error": "错误描述"} with HTTP status code:
            * 200: Success
            * 400: Request error (parameter validation, business logic errors)
            * 408: Request timeout (Playwright operation timeout, default 30s)
            * 500: Server error (unexpected system errors)
    
    All endpoints follow this pattern unless otherwise specified.
    """

    def __init__(self) -> None:
        # Initialize Sentry for error tracking (Sentry 2.x auto-detects FastAPI)
        sentry_config = get_sentry_config()
        if sentry_config["dsn"]:
            # Disable auto-integration detection to avoid timeout during package scanning
            # Manually enable only FastAPI integration to avoid scanning all packages
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            sentry_sdk.init(
                dsn=sentry_config["dsn"],
                enable_tracing=True,
                send_default_pii=sentry_config["send_default_pii"],
                environment=sentry_config["environment"] or "development",
                release=sentry_config["release"] or "unknown",
                default_integrations=False,  # Disable auto-detection to prevent timeout
                integrations=[FastApiIntegration()],  # Manually enable FastAPI integration only
            )
            logger.info("Sentry initialized: environment=%s, release=%s", 
                        sentry_config["environment"], sentry_config["release"])
        else:
            logger.info("Sentry DSN not configured in secrets.yaml, error tracking disabled")
        
        self.app = FastAPI(lifespan=self.lifespan)
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_logged_in = False
        self.browser_lock = asyncio.Lock()
        self.startup_complete = asyncio.Event()
        self.event_manager = None  # Placeholder for legacy debug endpoint
        self.setup_routes()
        self.setup_exception_handlers()

    # ------------------------------------------------------------------
    # Lifecycle management
    # ------------------------------------------------------------------
    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        await self._startup_async()
        try:
            yield
        finally:
            await self._shutdown_async()

    async def _startup_async(self) -> None:
        if self.playwright:
            return
        logger.debug("正在初始化 Playwright (async)...")
        self.playwright = await async_playwright().start()
        await self.start_browser()
        self.startup_complete.set()
        logger.debug("Playwright 初始化完成。")

    async def start_browser(self) -> None:
        if not self.playwright:
            raise RuntimeError("Playwright 未初始化")
        user_data_dir = os.path.join(tempfile.gettempdir(), "bosszhipin_playwright_user_data")
        os.makedirs(user_data_dir, exist_ok=True)
        

        browser_config = get_browser_config()
        self.browser = await self.playwright.chromium.connect_over_cdp(
            browser_config["cdp_url"],
            timeout=15000
        )
        self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
        self.page = await self._ensure_page()
        logger.debug("持久化浏览器会话已建立。")
        return True

    async def _shutdown_async(self) -> None:
        logger.debug("正在关闭 Playwright...")
        # Add timeouts to prevent hanging during reload
        try:
            if self.context:
                browser_config = get_browser_config()
                await asyncio.wait_for(
                    self.context.storage_state(path=browser_config["storage_state"]),
                    timeout=2.0
                )
        except asyncio.TimeoutError:
            logger.warning("保存 storage_state 超时，跳过")
        except Exception as exc:  # noqa: BLE001
            logger.warning("保存 storage_state 失败: %s", exc)
        
        # For CDP connections, we just disconnect, don't close the external browser
        try:
            if self.browser:
                await asyncio.wait_for(
                    self.browser.close(),
                    timeout=2.0
                )
        except asyncio.TimeoutError:
            logger.warning("关闭浏览器连接超时，强制断开")
            # Force cleanup on timeout
            self.browser = None
        except Exception as exc:  # noqa: BLE001
            logger.error("关闭浏览器失败（忽略）: %s", exc)
        
        if self.playwright:
            try:
                await asyncio.wait_for(
                    self.playwright.stop(),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.warning("停止 Playwright 超时，强制清理")
            except Exception as exc:  # noqa: BLE001
                logger.warning("停止 Playwright 失败: %s", exc)
        
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        self.is_logged_in = False
        logger.debug("Playwright 已停止。")

    # ------------------------------------------------------------------
    # Browser/session helpers
    # ------------------------------------------------------------------
    async def _ensure_page(self) -> Page:
        """Ensure we have a valid page, reusing existing page if on chat or recommend page.
        
        If the current page is already on CHAT_URL or RECOMMEND_URL, reuse it without navigation.
        Only navigate to CHAT_URL if the page is not on any target page.
        
        Returns:
            Page: A valid Playwright page object
        """
        if not self.context:
            raise RuntimeError("浏览器上下文不存在")
        
        boss_zhipin_config = get_boss_zhipin_config()
        target_pages = {boss_zhipin_config["chat_url"], boss_zhipin_config["recommend_url"]}
        candidate: Optional[Page] = None
        
        try:
            for existing in self.context.pages:
                if existing.is_closed():
                    continue
                if existing.url in target_pages or existing.url.startswith(boss_zhipin_config["base_url"]):
                    candidate = existing
                    break
            if not candidate:
                candidate = await self.context.new_page()
        except Exception as e:
            # Context or browser has been closed - reconnect
            logger.warning(f"Browser context closed, reconnecting to CDP: {e}")
            await self.start_browser()
            # After reconnect, get page from the new context
            for existing in self.context.pages:
                if not existing.is_closed():
                    candidate = existing
                    break
            if not candidate:
                candidate = await self.context.new_page()
        
        # Only navigate if we're not already on a target page
        if candidate.url not in target_pages and not candidate.url.startswith(boss_zhipin_config["base_url"]):
            await candidate.goto(boss_zhipin_config["chat_url"], wait_until="domcontentloaded", timeout=20000)
        return candidate

    async def _inject_navigation_guard(self, page: Page) -> None:
        """
        Optional: Inject JavaScript to prevent manual link clicks from navigating.
        This provides an additional layer on top of Chrome's --app mode.
        
        Note: This is currently NOT automatically called. Enable it by calling this
        method after page loads if you want to completely block manual navigation.
        The --app mode in start_service.py already provides good isolation.
        """
        boss_zhipin_config = get_boss_zhipin_config()
        allowed_origin = boss_zhipin_config["base_url"]
        navigation_guard_script = f"""
        (function() {{
            const allowedOrigin = '{allowed_origin}';
            
            // Prevent link clicks that navigate outside BASE_URL
            document.addEventListener('click', function(event) {{
                let target = event.target;
                while (target && target.tagName !== 'A') {{
                    target = target.parentElement;
                }}
                if (target && target.tagName === 'A') {{
                    const href = target.getAttribute('href');
                    if (href && !href.startsWith(allowedOrigin) && !href.startsWith('/') && !href.startsWith('#')) {{
                        event.preventDefault();
                        event.stopPropagation();
                        console.log('[Navigation Guard] Blocked navigation to:', href);
                    }}
                }}
            }}, true);
            
            // Log when navigation is attempted
            window.addEventListener('beforeunload', function(event) {{
                console.log('[Navigation Guard] Page unload detected');
            }});
            
            console.log('[Navigation Guard] Installed - only {allowed_origin} navigation allowed');
        }})();
        """
        await page.evaluate(navigation_guard_script)
        logger.debug("Navigation guard injected for page: %s", page.url)

    async def save_login_state(self) -> None:
        if not self.context:
            return
        browser_config = get_browser_config()
        os.makedirs(os.path.dirname(browser_config["storage_state"]), exist_ok=True)
        await self.context.storage_state(path=browser_config["storage_state"])
        logger.info("登录状态已保存: %s", browser_config["storage_state"])
        self.is_logged_in = True

    async def _save_login_state_with_lock(self) -> None:
        async with self.browser_lock:
            await self.save_login_state()
            logger.info("登录状态已保存")

    async def _ensure_browser_session(self, max_wait_time: int = 600) -> Page:
        """Ensure we have an open Playwright page and a valid login session.

        To avoid blocking all requests while waiting for manual login, we acquire the
        browser lock only for the short critical section that (re)creates the
        Playwright objects.  If a login check is needed, we release the lock and
        perform the polling without holding the lock so other read-only endpoints can
        continue to serve status information.
        """
        while True:
            async with self.browser_lock:
                page = await self._prepare_browser_session()
                login_needed = not self.is_logged_in

            if not login_needed:
                return page

            # Perform the potentially long manual-login wait without holding the lock.
            await self._verify_login(page, max_wait_time=max_wait_time)

    async def _prepare_browser_session(self) -> Page:
        if not self.playwright:
            await self._startup_async()
        if not self.context or not self.browser:
            await self.start_browser()
        if not self.page or self.page.is_closed():
            self.page = await self._ensure_page()

        page = self.page
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass

        return page

    async def _verify_login(self, page: Page, max_wait_time: int = 600) -> None:
        async def _page_contains_keywords() -> bool:
            try:
                body_text = await page.inner_text("body")
                keywords = ["职位管理", "牛人", "沟通", "打招呼"]
                return any(keyword in body_text for keyword in keywords)
            except Exception:
                return False

        try:
            if await _page_contains_keywords():
                await self._save_login_state_with_lock()
                return
        except Exception:
            pass

        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < max_wait_time:
            current_url = page.url
            logger.debug(f'等待登录: {current_url}')
            boss_zhipin_config = get_boss_zhipin_config()
            if boss_zhipin_config["base_url"] in current_url and await _page_contains_keywords():
                await self._save_login_state_with_lock()
                logger.info("检测到登录成功。")
                return
            if any(token in current_url.lower() for token in ("login", "web/user", "bticket")):
                logger.debug("等待用户在浏览器中完成登录...")
            await asyncio.sleep(3)
        raise TimeoutError("等待登录超时，请在浏览器中完成登录后重试")

    async def soft_restart(self) -> None:
        async with self.browser_lock:
            logger.info("正在重启浏览器...")
            await self._shutdown_async()
            await self._startup_async()
            logger.info("浏览器已重启")

    # ------------------------------------------------------------------
    # Exception handlers
    # ------------------------------------------------------------------
    def setup_exception_handlers(self) -> None:
        """Configure global exception handlers for consistent error responses."""
        @self.app.get("/sentry-debug")
        async def trigger_error():
            """Test endpoint to verify Sentry integration."""
            division_by_zero = 1 / 0
        
        @self.app.exception_handler(Exception)
        async def unified_exception_handler(request: Request, exc: Exception):
            """Unified exception handler with branching logic based on exception type."""
            
            # Determine status code, log level, and error message based on exception type
            if isinstance(exc, ValueError):
                status_code = 400
                log_level = "warning"
                sentry_level = "warning"
                error_message = str(exc)
                logger.warning("ValueError in %s: %s", request.url.path, error_message)
                
            elif isinstance(exc, PlaywrightTimeoutError):
                status_code = 408
                log_level = "warning"
                sentry_level = "warning"
                error_message = f"操作超时: {str(exc)}"
                logger.warning("Playwright timeout in %s: %s", request.url.path, str(exc))
                
            elif isinstance(exc, RuntimeError):
                status_code = 500
                log_level = "error"
                sentry_level = "error"
                error_message = str(exc)
                logger.error("RuntimeError in %s: %s", request.url.path, error_message)
                
            else:
                # Catch-all for unexpected exceptions
                status_code = 500
                log_level = "error"
                sentry_level = "error"
                error_message = "Internal server error"
                logger.exception("Unhandled exception in %s", request.url.path)
            
            # Send to Sentry with context and appropriate level
            with sentry_sdk.push_scope() as scope:
                scope.set_context("request", {
                    "url": str(request.url),
                    "method": request.method,
                    "path": request.url.path,
                })
                scope.set_tag("exception_type", type(exc).__name__)
                scope.set_level(sentry_level)
                sentry_sdk.capture_exception(exc)
            
            return JSONResponse(
                status_code=status_code,
                content={"error": error_message}
            )

    # ------------------------------------------------------------------
    # FastAPI routes
    # ------------------------------------------------------------------
    def setup_routes(self) -> None:
        # TODO: Add API key authentication middleware for security
        # When exposing service via Cloudflare tunnel, all endpoints should be protected
        # with API key authentication to prevent unauthorized access.
        # Example implementation:
        # @self.app.middleware("http")
        # async def verify_api_key(request: Request, call_next):
        #     # Skip authentication for web UI routes and static files
        #     if (request.url.path.startswith("/") and 
        #         (request.url.path in ["/", "/candidates", "/automation", "/jobs", "/stats", "/recent-activity"] or
        #          request.url.path.startswith("/static/") or
        #          request.url.path.startswith("/candidates/") or
        #          request.url.path.startswith("/automation/") or
        #          request.url.path.startswith("/jobs/"))):
        #         return await call_next(request)
        #     api_key = request.headers.get("X-API-Key")
        #     if api_key != settings.API_KEY:
        #         raise HTTPException(status_code=401, detail="Invalid API key")
        #     return await call_next(request)
        
        # Playwright/browser actions (async)
        @self.app.get("/status")
        async def get_status():
            """Get service status including login state and message counts.
            
            Returns:
                dict: Service status with keys:
                    - status: Always "running"
                    - logged_in: Boolean indicating if user is logged in
                    - timestamp: ISO format timestamp
                    - new_message_count: Count of new messages
                    - new_greet_count: Count of new greeting requests
            """
            page = await self._ensure_browser_session()
            stats = await chat_actions.get_chat_stats_action(page)
            return {
                "status": "running",
                "logged_in": self.is_logged_in,
                "timestamp": datetime.now().isoformat(),
                "new_message_count": stats.get("new_message_count", 0),
                "new_greet_count": stats.get("new_greet_count", 0),
            }

        @self.app.post("/login")
        async def login():
            """Verify login status. Triggers browser session check.
            
            Returns:
                bool: True if logged in, False otherwise
            """
            await self._ensure_browser_session()
            return self.is_logged_in

        @self.app.get("/tunnel-url")
        async def get_tunnel_url():
            """Get Cloudflare tunnel URL if available.
            
            Returns:
                dict: Tunnel URL information with keys:
                    - tunnel_url: Public tunnel URL (if available)
                    - local_url: Local service URL
                    - has_tunnel: Boolean indicating if tunnel is active
            """
            import os
            tunnel_url = os.environ.get('BOSS_TUNNEL_URL')
            service_config = get_service_config()
            local_url = f"http://{service_config['host']}:{service_config['port']}"
            
            return {
                "tunnel_url": tunnel_url,
                "local_url": local_url,
                "has_tunnel": tunnel_url is not None
            }

        # ------------------ Chat API ------------------
        @self.app.get("/chat/dialogs")
        async def list_caht_messages(
            limit: int = Query(10, ge=1, le=100),
            tab: str = Query('新招呼', description="Tab filter: 新招呼, 沟通中, 全部"),
            status: str = Query('未读', description="Status filter: 未读, 牛人已读未回, 全部"),
            job_title: str = Query('全部', description="Job title filter: 全部 or specific job title"),
            new_only: bool = Query(True, description="Only include new candidates (not yet viewed/greeted)")
        ):
            """Get list of chat dialogs/candidates.
            
            Args:
                limit: Maximum number of dialogs to return (1-100)
                tab: Tab filter for dialog type (新招呼, 沟通中, 全部)
                status: Status filter (未读, 牛人已读未回, 全部)
                job_title: Job title filter (全部 or specific job title)
                new_only: If True, only include new candidates (not yet viewed/greeted)
            Returns:
                List[dict]: List of candidate dialogs, each containing:
                    - chat_id: Unique chat identifier
                    - name: Candidate name
                    - job_applied: Job title applied for
                    - last_message: Last message text
                    - timestamp: Message timestamp
            """
            page = await self._ensure_browser_session()
            return await chat_actions.list_conversations_action(page, limit, tab, status, job_title, new_only)

        @self.app.get("/chat/{chat_id}/messages")
        async def get_message_history(chat_id: str):
            """Get message history for a specific chat.
            
            Args:
                chat_id: Unique identifier for the chat/candidate
            
            Returns:
                List[dict]: List of messages, each containing:
                    - type: Message type (candidate, recruiter, system)
                    - message: Message content
                    - timestamp: Message timestamp
                    - status: Read status (if applicable)
            """
            page = await self._ensure_browser_session()
            return await chat_actions.get_chat_history_action(page, chat_id)

        @self.app.post("/chat/{chat_id}/send_message")
        async def send_message_api(chat_id: str, message: str = Body(..., embed=True)):
            """Send a message to a candidate.
            
            Args:
                chat_id: Unique identifier for the chat/candidate
                message: Message text to send
            
            Returns:
                bool: True if message was sent successfully
            """
            page = await self._ensure_browser_session()
            return await chat_actions.send_message_action(page, chat_id, message)
        
        @self.app.post("/chat/greet")
        async def greet_candidate(
            chat_id: str = Body(..., embed=True), 
            message: str = Body(..., embed=True)
        ):
            """Send a greeting message to a candidate.
            
            Args:
                chat_id: Unique identifier for the chat/candidate
                message: Greeting message text (will be stripped of whitespace)
            
            Returns:
                dict: Response containing success status and message details
            """
            page = await self._ensure_browser_session()
            return await chat_actions.send_message_action(page, chat_id, message.strip())

        @self.app.get("/chat/stats")
        async def get_chat_stats():
            """Get chat statistics including message counts.
            
            Returns:
                dict: Statistics containing:
                    - new_message_count: Count of new messages
                    - new_greet_count: Count of new greeting requests
            """
            page = await self._ensure_browser_session()
            return await chat_actions.get_chat_stats_action(page)

        @self.app.post("/chat/resume/request_full")
        async def request_resume_api(chat_id: str = Body(..., embed=True)):
            """Request full resume from a candidate.
            
            Args:
                chat_id: Unique identifier for the chat/candidate
            
            Returns:
                bool: True if request was sent successfully
            
            Raises:
                ValueError: If request fails (converted to 400 response)
            """
            page = await self._ensure_browser_session()
            return await chat_actions.request_full_resume_action(page, chat_id)
        
        @self.app.get("/chat/resume/full/{chat_id}")
        async def view_full_resume(chat_id: str):
            """View full (offline) resume for a candidate.
            
            This endpoint retrieves the full resume PDF/document that was uploaded
            by the candidate as an attachment. The resume is extracted from the PDF
            using OCR if necessary.
            
            Args:
                chat_id: Unique identifier for the chat/candidate
            
            Returns:
                dict: Resume data containing:
                    - text: Resume text content (extracted from PDF)
                    - name: Candidate name
                    - chat_id: Chat identifier
                    - pages: List of image filenames (one per PDF page)
            
            Raises:
                ValueError: If resume is not available or retrieval fails (converted to 400/408 response)
                PlaywrightTimeoutError: If PDF extraction times out (converted to 408 response)
            """
            page = await self._ensure_browser_session()
            return await chat_actions.view_full_resume_action(page, chat_id)
        
        @self.app.post("/chat/resume/check_full_resume_available")
        async def check_full_resume(chat_id: str = Body(..., embed=True)):
            """Check if full resume is available for a candidate.
            
            Args:
                chat_id: Unique identifier for the chat/candidate
            
            Returns:
                bool: True if full resume button/option is available
            """
            page = await self._ensure_browser_session()
            resume_button = await chat_actions.check_full_resume_available(page, chat_id)
            return resume_button is not None

        @self.app.get("/chat/resume/online/{chat_id}")
        async def view_online_resume_api(chat_id: str):
            """View online resume for a candidate.
            
            This endpoint retrieves the online resume that is displayed on the
            candidate's profile page. This is typically shorter than the full resume
            and includes key information visible before requesting the full document.
            
            Args:
                chat_id: Unique identifier for the chat/candidate
            
            Returns:
                dict: Resume data containing:
                    - text: Resume text content
                    - name: Candidate name
                    - chat_id: Chat identifier
            """
            page = await self._ensure_browser_session()
            return await chat_actions.view_online_resume_action(page, chat_id)
        
        @self.app.post("/chat/resume/accept")
        async def accept_resume_api(chat_id: str = Body(..., embed=True)):
            """Accept a candidate's resume.
            
            Args:
                chat_id: Unique identifier for the chat/candidate
            
            Returns:
                bool: True if resume was accepted successfully
            
            Raises:
                ValueError: If accept button is not found or action fails
            """
            page = await self._ensure_browser_session()
            return await chat_actions.accept_full_resume_action(page, chat_id)

        @self.app.post("/chat/candidate/discard")
        async def discard_candidate_api(chat_id: str = Body(..., embed=True)):
            """Discard/pass a candidate (mark as not suitable).
            
            Args:
                chat_id: Unique identifier for the chat/candidate
            
            Returns:
                bool: True if candidate was discarded successfully
            """
            page = await self._ensure_browser_session()
            return await chat_actions.discard_candidate_action(page, chat_id)
        
        @self.app.post("/chat/contact/request")
        async def ask_contact_api(chat_id: str = Body(..., embed=True)):
            """Request contact information from a candidate.
            
            Args:
                chat_id: Unique identifier for the chat/candidate
            
            Returns:
                bool: True if contact request was sent successfully
            """
            page = await self._ensure_browser_session()
            return await chat_actions.ask_contact_action(page, chat_id)

        # ------------------ Recommend API ------------------
        @self.app.get("/recommend/candidates")
        async def get_recommended_candidates(
            limit: int = Query(20, ge=1, le=100),
            job_title: str = Query(None, description="Job title to filter recommendations"),
            new_only: bool = Query(True, description="Only include new candidates (not yet viewed/greeted)"),
            filters: str = Query(None, description="Candidate filters as JSON string")
        ):
            """Get list of recommended candidates.
            
            Returns candidates from the "推荐牛人" (Recommended Candidates) page.
            Candidates are indexed starting from 0 for use with other recommend endpoints.
            
            Args:
                limit: Maximum number of candidates to return (1-100)
                job_title: Optional job title to filter recommendations
                new_only: If True, only return candidates not yet viewed/greeted
            
            Returns:
                List[dict]: List of recommended candidates, each containing:
                    - index: Index in the recommendation list (0-based, use for /recommend/candidate/{index}/* endpoints)
                    - name: Candidate name
                    - text: Candidate summary/description
                    - job_title: Job title applied for
            
            """
            page = await self._ensure_browser_session()
            # Parse filters from JSON string if provided
            parsed_filters = None
            if filters:
                try:
                    import json
                    parsed_filters = json.loads(filters)
                except json.JSONDecodeError:
                    raise ValueError(f"Invalid filters JSON: {filters}")
            return await recommendation_actions.list_recommended_candidates_action(page, limit=limit, job_title=job_title, new_only=new_only, filters=parsed_filters)

        @self.app.get("/recommend/candidate/{index}/resume")
        async def view_recommended_candidate_resume(index: int):
            """Get resume for a recommended candidate by index.
            
            The index corresponds to the position in the list returned by
            /recommend/candidates. This endpoint opens the candidate's profile
            and extracts their resume information.
            
            Args:
                index: Index of the candidate in the recommendation list (0-based)
            
            Returns:
                dict: Resume data containing:
                    - text: Resume text content
                    - name: Candidate name
                    - index: Candidate index
            """
            page = await self._ensure_browser_session()
            return await recommendation_actions.view_recommend_candidate_resume_action(page, index)

        @self.app.post("/recommend/candidate/{index}/greet")
        async def greet_recommended_candidate(index: int, message: str = Body(..., embed=True)):
            """Send a greeting message to a recommended candidate.
            
            Args:
                index: Index of the candidate in the recommendation list
                message: Greeting message text
            
            Returns:
                bool: True if message was sent successfully
            """
            page = await self._ensure_browser_session()
            return await recommendation_actions.greet_recommend_candidate_action(page, index, message)


        # ------------------ Candidate API ------------------
        @self.app.get("/store/candidate/{chat_id}")
        def get_candidate_api(chat_id: str, fields: Optional[List[str]] = None):
            """Get candidate information from the Zilliz store.
            
            Args:
                chat_id: Unique identifier for the chat/candidate
                fields: Optional list of fields to return (default: all fields)
            """
            results = get_candidates(identifiers=[chat_id], limit=1, fields=fields)
            return results[0] if results else None
        
        @self.app.post("/store/candidate/get-by-resume")
        def check_candidate_by_resume_api(resume_text: str = Body(..., embed=True)):
            """Check if candidate exists by resume similarity search.
            
            Args:
                resume_text: Resume text content to search for
            
            Returns:
                Optional[dict]: Matching candidate data if found, None otherwise
            """
            return search_candidates_by_resume(
                resume_text=resume_text
            )

        # ------------------ AI Assistant API ------------------

        @self.app.post("/assistant/generate-message")
        def generate_message(data: dict = Body(...)):
            """Generate AI message for candidate based on thread context.
            
            Uses OpenAI Assistant API to generate contextual messages based on
            the thread history, candidate resume, and job requirements.
            
            Args:
                data: JSON body containing:
                    - thread_id: OpenAI thread identifier (required)
                    - assistant_id: OpenAI assistant identifier (required)
                    - purpose: Purpose of message generation:
                        * "GREET_ACTION": Initial greeting message
                        * "CHAT_ACTION": Follow-up conversation message
                        * "ANALYZE_ACTION": Analysis of candidate
                    - chat_history: Optional chat history for context
            
            Returns:
                str: Generated message text
            """
            return assistant_actions.generate_message(**data)
        
        @self.app.post("/assistant/init-chat")
        async def init_chat_api(data: dict = Body(...)):
            """Initialize a new OpenAI conversation for candidate.
            
            Creates a new OpenAI conversation and populates it with initial context
            including candidate resume and job requirements.
            The conversation_id can then be used for generating AI messages via /assistant/generate-message.
            
            Args:
                data: JSON body containing:
                    - chat_id: Chat identifier (None for recommend candidates)
                    - name: Candidate name
                    - job_info: Job information dictionary containing job requirements, keywords, etc.
                    - resume_text: Candidate resume text
                    - chat_history: Optional existing chat history (currently unused)
            
            Returns:
                str: Created OpenAI conversation identifier
            
            Raises:
                ValueError: If initialization fails (converted to 500 response)
            """
            return assistant_actions.init_chat(**data)
        
        @self.app.get("/assistant/{thread_id}/messages")
        def get_thread_messages_api(thread_id: str):
            """Get all messages from an OpenAI conversation.
            
            Note: The URL parameter is named 'thread_id' for backward compatibility,
            but it actually accepts a conversation_id.
            
            Args:
                thread_id: OpenAI conversation identifier (stored as thread_id field)
            
            Returns:
                dict: Response containing:
                    - messages: List of conversation messages with id, role, and content
                    - has_more: Boolean indicating if more messages are available (always False)
                    - analysis: Optional analysis dict if found in messages
                    - action: Optional action dict if found in messages
            
            Raises:
                ValueError: If conversation not found or retrieval fails
            """
            from src.assistant_utils import get_conversation_messages
            return get_conversation_messages(thread_id)

        @self.app.get("/assistant/{thread_id}/analysis")
        def get_thread_analysis_api(thread_id: str):
            """Get analysis result from conversation messages.
            
            Note: The URL parameter is named 'thread_id' for backward compatibility,
            but it actually accepts a conversation_id.
            
            Extracts the most recent analysis from conversation messages, typically generated
            by ANALYZE_ACTION purpose.
            
            Args:
                thread_id: OpenAI conversation identifier (stored as thread_id field)
            
            Returns:
                Optional[dict]: Analysis dictionary if found in conversation, None otherwise
            
            Raises:
                ValueError: If conversation not found
            """
            from src.assistant_utils import get_analysis_from_conversation
            return get_analysis_from_conversation(thread_id)

        # ------------------ OpenAI Assistant API ------------------
        @self.app.get("/assistant/list")
        def list_assistants_api():
            """List all OpenAI assistants.
            
            Returns:
                List[dict]: List of assistant dictionaries, each containing:
                    - id: Assistant identifier
                    - name: Assistant name
                    - model: Model used by assistant
                    - description: Assistant description
                    - instructions: System instructions
                    - metadata: Additional metadata
                    - created_at: Creation timestamp
            """
            assistants = assistant_actions.get_assistants()
            return [assistant.model_dump() for assistant in assistants.data]

        @self.app.post("/assistant/create")
        def create_assistant_api(payload: dict = Body(...)):
            """Create a new OpenAI assistant.
            
            Args:
                payload: JSON body containing:
                    - name: Assistant name (required)
                    - model: Model identifier (required, e.g., "gpt-4o-mini")
                    - instructions: System instructions (required)
                    - description: Optional description
                    - metadata: Optional metadata dictionary
            
            Returns:
                dict: Created assistant data
            """
            client = assistant_actions._openai_client
            assistant = client.beta.assistants.create(**payload)
            return assistant.model_dump()

        @self.app.post("/assistant/update/{assistant_id}")
        def update_assistant_api(assistant_id: str, payload: dict = Body(...)):
            """Update an existing OpenAI assistant.
            
            Args:
                assistant_id: OpenAI assistant identifier
                payload: JSON body containing fields to update:
                    - name: Optional new name
                    - model: Optional new model
                    - instructions: Optional new instructions
                    - description: Optional new description
                    - metadata: Optional new metadata
            
            Returns:
                dict: Updated assistant data
            
            Raises:
                ValueError: If update fails or assistant not found
            """
            client = assistant_actions._openai_client
            assistant = client.beta.assistants.update(assistant_id, **payload)
            assistant_actions.get_assistants.cache_clear()
            return assistant.model_dump()

        @self.app.delete("/assistant/delete/{assistant_id}")
        def delete_assistant_api(assistant_id: str):
            """Delete an OpenAI assistant.
            
            Args:
                assistant_id: OpenAI assistant identifier
            
            Returns:
                bool: True if deletion was successful
            """
            client = assistant_actions._openai_client
            client.beta.assistants.delete(assistant_id)
            assistant_actions.get_assistants.cache_clear()
            return True

        # ------------------ System / Debug Endpoints ------------------
        @self.app.post("/restart")
        async def soft_restart_endpoint():
            """Perform a soft restart of the browser session.
            
            Closes and reopens the browser context without restarting the entire service.
            Useful for recovering from browser errors or refreshing the session.
            
            Returns:
                bool: True if restart was successful
            """
            await self.soft_restart()
            return True

        @self.app.get("/debug/page")
        async def debug_page():
            """Get debug information about the current browser page.
            
            Returns:
                dict: Debug information containing:
                    - url: Current page URL
                    - title: Page title
                    - content: First 5000 characters of page HTML
                    - content_length: Total length of page HTML
            
            Note: This endpoint is for debugging purposes only.
            """
            page = await self._ensure_browser_session()
            await page.locator("body").first.wait_for(state="visible", timeout=5000)
            await page.wait_for_load_state("networkidle", timeout=5000)
            content = await page.content()
            readable = content[:5000] + "..." if len(content) > 5000 else content
            return {
                "url": page.url,
                "title": await page.title(),
                "content": readable,
                "content_length": len(content),
            }

        @self.app.get("/debug/cache")
        async def get_cache_stats():
            """Get cache statistics for debugging.
            
            Returns:
                dict: Cache statistics if available, empty dict otherwise
            
            Note: This endpoint is for debugging purposes only.
            """
            if self.event_manager and hasattr(self.event_manager, "get_cache_stats"):
                return self.event_manager.get_cache_stats()
            return {}

        @self.app.middleware("http")
        async def ensure_startup(request: Request, call_next):
            await self.startup_complete.wait()
            return await call_next(request)


service = BossServiceAsync()
app = service.app

# ============================================================================
# Web UI Configuration
# ============================================================================

# Mount static files
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Configure Jinja2 templates
templates = Jinja2Templates(directory="web/templates")

# Include web UI routers
from web.routes import candidates, automation, jobs

app.include_router(candidates.router, prefix="/candidates", tags=["web-candidates"])
app.include_router(automation.router, prefix="/automation", tags=["web-automation"])
app.include_router(jobs.router, prefix="/jobs", tags=["web-jobs"])

# Chrome DevTools configuration endpoint
@app.get("/.well-known/appspecific/com.chrome.devtools.json", tags=["system"])
async def chrome_devtools_config():
    """Handle Chrome DevTools configuration request.
    
    Chrome DevTools automatically requests this file when inspecting pages.
    Returning an empty JSON response prevents 404 errors in logs.
    
    Returns:
        dict: Empty JSON object
    """
    return {}

# Favicon endpoints (browsers check these paths automatically)
@app.get("/favicon.ico", tags=["web"])
@app.get("/favicon.svg", tags=["web"])
async def favicon():
    """Serve favicon directly."""
    from fastapi.responses import FileResponse
    import os
    favicon_path = os.path.join("web", "static", "favicon.svg")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path, media_type="image/svg+xml")
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Favicon not found")

# Web UI root endpoint
@app.get("/", response_class=HTMLResponse, tags=["web"])
async def web_index(request: Request):
    """Serve the Web UI landing page.
    
    Returns:
        HTMLResponse: Rendered index.html template
    """
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/stats", response_class=HTMLResponse, tags=["web"])
async def web_stats():
    """Get quick statistics for the Web UI dashboard.
    
    Returns HTML cards displaying:
    - Total candidate count from Zilliz store
    - New message count
    - New greeting count
    - Running workflows count (placeholder)
    
    Returns:
        HTMLResponse: HTML cards with statistics
    """
    # Get message counts from chat stats
    new_messages = 0
    new_greets = 0
    try:
        page = await service._ensure_browser_session()
        stats = await chat_actions.get_chat_stats_action(page)
        new_messages = stats.get("new_message_count", 0)
        new_greets = stats.get("new_greet_count", 0)
    except Exception as e:
        logger.warning(f"Failed to get chat stats: {e}")
    
    # Try to get total candidates from store
    try:
        total_candidates = get_candidate_count()
    except Exception as e:
        total_candidates = 0
        logger.warning(f"Failed to get candidate count: {e}")
    
    # Count running workflows (placeholder - would need actual tracking)
    running_workflows = 0
    
    html = f'''
    <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-sm text-gray-600 mb-2">已筛选候选人总数</h3>
        <p class="text-3xl font-bold text-blue-600">{total_candidates}</p>
    </div>
    <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-sm text-gray-600 mb-2">新消息</h3>
        <p class="text-3xl font-bold text-green-600">{new_messages}</p>
    </div>
    <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-sm text-gray-600 mb-2">新招呼</h3>
        <p class="text-3xl font-bold text-yellow-600">{new_greets}</p>
    </div>
    <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-sm text-gray-600 mb-2">运行中工作流</h3>
        <p class="text-3xl font-bold text-purple-600">{running_workflows}</p>
    </div>
    '''
    return HTMLResponse(content=html)

@app.get("/recent-activity", response_class=HTMLResponse, tags=["web"])
async def web_recent_activity():
    """Get recent activity feed for the Web UI dashboard.
    
    Reads the latest changelog entries from CHANGELOG.md and displays
    them in a formatted list.
    
    Returns:
        HTMLResponse: HTML content with recent activity from changelog
    """
    import re
    from pathlib import Path
    
    changelog_path = Path(__file__).parent / "CHANGELOG.md"
    
    if not changelog_path.exists():
        html = '''
        <div class="text-gray-600 space-y-2">
            <p>📊 系统已启动，等待操作...</p>
            <p class="text-sm text-gray-500">提示：访问「候选人管理」或「自动化工作流」开始使用</p>
        </div>
        '''
        return HTMLResponse(content=html)
    
    try:
        with open(changelog_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract the latest version section (first ## after # 更新日志)
        # Match pattern: ## vX.X.X (date) - title
        version_pattern = r'^## (v[\d.]+) \(([^)]+)\) - (.+)$'
        sections = re.split(r'^## ', content, flags=re.MULTILINE)
        
        if len(sections) < 2:
            html = '''
            <div class="text-gray-600 space-y-2">
                <p>📊 系统已启动，等待操作...</p>
                <p class="text-sm text-gray-500">提示：访问「候选人管理」或「自动化工作流」开始使用</p>
            </div>
            '''
            return HTMLResponse(content=html)
        
        # Get the first version section (most recent)
        latest_section = sections[1]  # First section after split is the header
        lines = latest_section.split('\n')
        
        # Extract version info from first line
        first_line = lines[0] if lines else ""
        version_match = re.match(r'^(v[\d.]+) \(([^)]+)\) - (.+)$', first_line)
        
        if not version_match:
            html = '''
            <div class="text-gray-600 space-y-2">
                <p>📊 系统已启动，等待操作...</p>
                <p class="text-sm text-gray-500">提示：访问「候选人管理」或「自动化工作流」开始使用</p>
            </div>
            '''
            return HTMLResponse(content=html)
        
        version, date, title = version_match.groups()
        
        # Extract major updates (### 🚀 重大更新 section)
        html_parts = [f'<div class="space-y-3">']
        html_parts.append(f'<div class="border-b pb-2 mb-3">')
        html_parts.append(f'<h3 class="text-lg font-bold text-gray-800">{version}</h3>')
        html_parts.append(f'<p class="text-sm text-gray-600">{date} - {title}</p>')
        html_parts.append(f'</div>')
        
        # Extract key points from all sections
        items = []
        current_section = None
        skip_next_section = False
        
        for i, line in enumerate(lines[1:100]):  # Limit to first 100 lines
            line = line.strip()
            if not line:
                continue
            
            # Stop at next version section
            if line.startswith('## '):
                break
            
            # Track section headers
            if line.startswith('### '):
                section_title = line.replace('### ', '').strip()
                # Skip certain sections that are too detailed
                if any(skip in section_title for skip in ['提交记录', '参考文档', '测试验证', '配置文件']):
                    skip_next_section = True
                    current_section = None
                    continue
                else:
                    skip_next_section = False
                    current_section = section_title
                    continue
            elif line.startswith('#### '):
                current_section = line.replace('#### ', '').strip()
                skip_next_section = False
                continue
            
            # Skip if we're in a section to skip
            if skip_next_section:
                continue
            
            # Collect bullet points (with or without bold)
            if line.startswith('- **') or line.startswith('- '):
                # Clean up markdown formatting
                clean_line = line.replace('- **', '- ').replace('**', '').strip()
                # Remove nested markdown like `code` or [links]
                clean_line = re.sub(r'`([^`]+)`', r'\1', clean_line)
                clean_line = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean_line)
                
                if clean_line and len(clean_line) > 5:  # Minimum length
                    # Add section context if available
                    if current_section and not clean_line.startswith(current_section):
                        items.append(f"{current_section}: {clean_line}")
                    else:
                        items.append(clean_line)
        
        # Display items (limit to 10 most recent)
        if items:
            html_parts.append('<ul class="space-y-2 text-sm text-gray-700">')
            for item in items[:10]:
                # Escape HTML and format
                item_html = item.replace('<', '&lt;').replace('>', '&gt;')
                html_parts.append(f'<li class="flex items-start">')
                html_parts.append(f'<span class="mr-2 text-blue-500">▸</span>')
                html_parts.append(f'<span class="flex-1">{item_html}</span>')
                html_parts.append(f'</li>')
            html_parts.append('</ul>')
            if len(items) > 10:
                html_parts.append(f'<p class="text-xs text-gray-400 mt-2">还有 {len(items) - 10} 项更新...</p>')
        else:
            html_parts.append('<p class="text-sm text-gray-500">暂无详细更新信息</p>')
        
        html_parts.append('</div>')
        html = '\n'.join(html_parts)
        
    except Exception as e:
        logger.warning(f"Failed to parse changelog: {e}")
        html = '''
        <div class="text-gray-600 space-y-2">
            <p>📊 系统已启动，等待操作...</p>
            <p class="text-sm text-gray-500">提示：访问「候选人管理」或「自动化工作流」开始使用</p>
        </div>
        '''
    
    return HTMLResponse(content=html)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("boss_service:app", host="0.0.0.0", port=5001, reload=False)
