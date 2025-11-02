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
from src.candidate_store import candidate_store
from src.config import settings
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
        sentry_config = settings.get_sentry_config()
        if sentry_config["dsn"]:
            sentry_sdk.init(
                dsn=sentry_config["dsn"],
                enable_tracing=True,
                traces_sample_rate=0.1,
                profiles_sample_rate=0.1,
                send_default_pii=True,
                environment=sentry_config["environment"] or "development",
                release=sentry_config["release"] or "unknown",
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
        self.candidate_store = candidate_store
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
        logger.info("正在初始化 Playwright (async)...")
        self.playwright = await async_playwright().start()
        await self.start_browser()
        self.startup_complete.set()
        logger.info("Playwright 初始化完成。")

    async def start_browser(self) -> None:
        if not self.playwright:
            raise RuntimeError("Playwright 未初始化")
        user_data_dir = os.path.join(tempfile.gettempdir(), "bosszhipin_playwright_user_data")
        os.makedirs(user_data_dir, exist_ok=True)
        
        # Connect with timeout and retry to handle page reload deadlock
        max_retries = 3
        timeout_ms = 15000  # 15 seconds per attempt
        
        for attempt in range(max_retries):
            try:
                logger.info("连接 Chrome CDP (尝试 %d/%d): %s", attempt + 1, max_retries, settings.CDP_URL)
                self.browser = await self.playwright.chromium.connect_over_cdp(
                    settings.CDP_URL,
                    timeout=timeout_ms
                )
                self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
                self.page = await self._ensure_page()
                logger.info("持久化浏览器会话已建立。")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning("CDP连接失败 (尝试 %d/%d): %s. %d秒后重试...", 
                                 attempt + 1, max_retries, e, wait_time)
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("CDP连接失败，已达到最大重试次数: %s", e)
                    raise RuntimeError(f"无法连接到Chrome CDP，已尝试{max_retries}次: {e}") from e

    async def _shutdown_async(self) -> None:
        logger.info("正在关闭 Playwright...")
        try:
            if self.context:
                await self.context.storage_state(path=settings.STORAGE_STATE)
        except Exception as exc:  # noqa: BLE001
            logger.warning("保存 storage_state 失败: %s", exc)
        try:
            if self.browser:
                await self.browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("关闭浏览器失败（忽略）: %s", exc)
        if self.playwright:
            await self.playwright.stop()
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        self.is_logged_in = False
        logger.info("Playwright 已停止。")

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
        target_pages = {settings.CHAT_URL, settings.RECOMMEND_URL}
        candidate: Optional[Page] = None
        for existing in self.context.pages:
            if existing.is_closed():
                continue
            if existing.url in target_pages or existing.url.startswith(settings.BASE_URL):
                candidate = existing
                break
        if not candidate:
            candidate = await self.context.new_page()
        # Only navigate if we're not already on a target page
        if candidate.url not in target_pages and not candidate.url.startswith(settings.BASE_URL):
            await candidate.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=20000)
        return candidate

    async def _inject_navigation_guard(self, page: Page) -> None:
        """
        Optional: Inject JavaScript to prevent manual link clicks from navigating.
        This provides an additional layer on top of Chrome's --app mode.
        
        Note: This is currently NOT automatically called. Enable it by calling this
        method after page loads if you want to completely block manual navigation.
        The --app mode in start_service.py already provides good isolation.
        """
        allowed_origin = settings.BASE_URL
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
        os.makedirs(os.path.dirname(settings.STORAGE_STATE), exist_ok=True)
        await self.context.storage_state(path=settings.STORAGE_STATE)
        logger.info("登录状态已保存: %s", settings.STORAGE_STATE)
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
            logger.info(f'等待登录: {current_url}')
            if settings.BASE_URL in current_url and await _page_contains_keywords():
                await self._save_login_state_with_lock()
                logger.info("检测到登录成功。")
                return
            if any(token in current_url.lower() for token in ("login", "web/user", "bticket")):
                logger.info("等待用户在浏览器中完成登录...")
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

        # ------------------ Chat API ------------------
        @self.app.get("/chat/dialogs")
        async def get_messages(
            limit: int = Query(10, ge=1, le=100),
            tab: str = Query('新招呼', description="Tab filter: 新招呼, 沟通中, 全部"),
            status: str = Query('未读', description="Status filter: 未读, 牛人已读未回, 全部"),
            job_title: str = Query('全部', description="Job title filter: 全部 or specific job title")
        ):
            """Get list of chat dialogs/candidates.
            
            Args:
                limit: Maximum number of dialogs to return (1-100)
                tab: Tab filter for dialog type (新招呼, 沟通中, 全部)
                status: Status filter (未读, 牛人已读未回, 全部)
                job_title: Job title filter (全部 or specific job title)
            
            Returns:
                List[dict]: List of candidate dialogs, each containing:
                    - chat_id: Unique chat identifier
                    - name: Candidate name
                    - job_applied: Job title applied for
                    - last_message: Last message text
                    - timestamp: Message timestamp
            """
            page = await self._ensure_browser_session()
            return await chat_actions.get_chat_list_action(page, limit, tab, status, job_title)

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
            new_only: bool = Query(True, description="Only include new candidates (not yet viewed/greeted)")
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
            return await recommendation_actions.list_recommended_candidates_action(page, limit=limit, job_title=job_title, new_only=new_only)

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
        def get_candidate_api(chat_id: str, fields: Optional[List[str]] = ["*"]):
            """Get candidate information from the Zilliz store.
            
            Args:
                chat_id: Unique identifier for the chat/candidate
                fields: Optional list of fields to return (default: all fields)
            """
            return candidate_store.get_candidate_by_id(chat_id=chat_id, fields=fields)
        
        @self.app.post("/store/candidate/get-by-resume")
        def check_candidate_by_resume_api(resume_text: str = Body(..., embed=True)):
            """Check if candidate exists by resume similarity search.
            
            Args:
                resume_text: Resume text content to search for
            
            Returns:
                Optional[dict]: Matching candidate data if found, None otherwise
            """
            return assistant_actions.get_candidate_by_resume(
                chat_id=None,
                candidate_resume=resume_text
            )

        # ------------------ Thread/AI Assistant API ------------------

        @self.app.post("/chat/generate-message")
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
        
        @self.app.post("/chat/init-chat")
        async def init_chat_api(data: dict = Body(...)):
            """Initialize a new OpenAI thread for candidate conversation.
            
            Creates a new OpenAI thread and populates it with initial context
            including candidate resume, job requirements, and optional chat history.
            The thread can then be used for generating AI messages via /chat/generate-message.
            
            Args:
                data: JSON body containing:
                    - chat_id: Chat identifier (None for recommend candidates)
                    - name: Candidate name
                    - job_info: Job information dictionary containing job requirements, keywords, etc.
                    - resume_text: Candidate resume text
                    - chat_history: Optional existing chat history
            
            Returns:
                dict: Response containing:
                    - thread_id: Created OpenAI thread identifier
                    - success: Boolean indicating success (always True on success)
            
            Raises:
                ValueError: If initialization fails (converted to 500 response)
            """
            return assistant_actions.init_chat(**data)
        
        @self.app.get("/chat/{thread_id}/messages")
        def get_thread_messages_api(thread_id: str):
            """Get all messages from an OpenAI thread.
            
            Args:
                thread_id: OpenAI thread identifier
            
            Returns:
                dict: Response containing:
                    - messages: List of thread messages with id, role, and content
                    - has_more: Boolean indicating if more messages are available
            
            Raises:
                ValueError: If thread not found or retrieval fails
            """
            from src.assistant_utils import get_thread_messages
            return get_thread_messages(thread_id)
        
        @self.app.get("/thread/{thread_id}/messages")
        def get_thread_messages_alias(thread_id: str):
            """Alias for /chat/{thread_id}/messages endpoint.
            
            Args:
                thread_id: OpenAI thread identifier
            
            Returns:
                dict: Response containing messages list and has_more flag
            """
            from src.assistant_utils import get_thread_messages
            return get_thread_messages(thread_id)

        @self.app.get("/chat/{thread_id}/analysis")
        def get_thread_analysis_api(thread_id: str):
            """Get analysis result from thread messages.
            
            Extracts the most recent analysis from thread messages, typically generated
            by ANALYZE_ACTION purpose.
            
            Args:
                thread_id: OpenAI thread identifier
            
            Returns:
                Optional[dict]: Analysis dictionary if found in thread, None otherwise
            
            Raises:
                ValueError: If thread not found
            """
            from src.assistant_utils import get_analysis_from_thread
            return get_analysis_from_thread(thread_id)

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
from web.routes import candidates, automation, assistants, jobs

app.include_router(candidates.router, prefix="/web/candidates", tags=["web-candidates"])
app.include_router(automation.router, prefix="/web/automation", tags=["web-automation"])
app.include_router(assistants.router, prefix="/web/assistants", tags=["web-assistants"])
app.include_router(jobs.router, prefix="/web/jobs", tags=["web-jobs"])

# Web UI root endpoint
@app.get("/web", response_class=HTMLResponse, tags=["web"])
@app.get("/web/", response_class=HTMLResponse, tags=["web"])
async def web_index(request: Request):
    """Serve the Web UI landing page.
    
    Returns:
        HTMLResponse: Rendered index.html template
    """
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/web/stats", response_class=HTMLResponse, tags=["web"])
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
    total_candidates = 0
    try:
        if candidate_store and candidate_store.collection:
            total_candidates = candidate_store.collection.num_entities
    except Exception as e:
        logger.warning(f"Failed to get candidate count: {e}")
    
    # Count running workflows (placeholder - would need actual tracking)
    running_workflows = 0
    
    html = f'''
    <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-sm text-gray-600 mb-2">候选人总数</h3>
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

@app.get("/web/recent-activity", response_class=HTMLResponse, tags=["web"])
async def web_recent_activity():
    """Get recent activity feed for the Web UI dashboard.
    
    Currently returns a placeholder message. Future implementation should
    track and display recent system activities like candidate processing,
    message sending, etc.
    
    Returns:
        HTMLResponse: HTML content with recent activity (placeholder)
    """
    # TODO: Implement actual activity log
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
