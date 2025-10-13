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
from src.chat_actions import (
    accept_full_resume_action,
    check_full_resume_available,
    discard_candidate_action,
    get_chat_history_action,
    get_chat_list_action,
    get_chat_stats_action,
    request_full_resume_action,
    send_message_action,
    view_full_resume_action,
    view_online_resume_action,
)
from src.recommendation_actions import (
    _prepare_recommendation_page,
    greet_recommend_candidate_action,
    list_recommended_candidates_action,
    select_recommend_job_action,
    view_recommend_candidate_resume_action,
)


class BossServiceAsync:
    """Async Playwright driver exposed as FastAPI service."""

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
        if settings.BASE_URL not in candidate.url:
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
            page = await self._ensure_browser_session()
            stats = await get_chat_stats_action(page)
            return {
                "status": "running",
                "logged_in": self.is_logged_in,
                "timestamp": datetime.now().isoformat(),
                "new_message_count": stats.get("new_message_count", 0),
                "new_greet_count": stats.get("new_greet_count", 0),
            }

        @self.app.post("/login")
        async def login():
            await self._ensure_browser_session()
            return self.is_logged_in

        @self.app.get("/chat/dialogs")
        async def get_messages(
            limit: int = Query(10, ge=1, le=100),
            tab: str = Query('新招呼', description="Tab filter: 新招呼, 沟通中, 全部"),
            status: str = Query('未读', description="Status filter: 未读, 牛人已读未回, 全部"),
            job_title: str = Query('全部', description="Job title filter: 全部 or specific job title")
        ):
            page = await self._ensure_browser_session()
            return await get_chat_list_action(page, limit, tab, status, job_title)

        @self.app.get("/chat/{chat_id}/messages")
        async def get_message_history(chat_id: str):
            page = await self._ensure_browser_session()
            return await get_chat_history_action(page, chat_id)

        @self.app.post("/chat/{chat_id}/send")
        async def send_message_api(chat_id: str, message: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await send_message_action(page, chat_id, message)

        @self.app.post("/chat/greet")
        async def greet_candidate(
            chat_id: str = Body(..., embed=True), 
            message: str = Body(..., embed=True)
        ):
            page = await self._ensure_browser_session()
            return await send_message_action(page, chat_id, message.strip())

        @self.app.get("/chat/stats")
        async def get_chat_stats():
            page = await self._ensure_browser_session()
            return await get_chat_stats_action(page)

        @self.app.post("/resume/request")
        async def request_resume_api(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await request_full_resume_action(page, chat_id)

        @self.app.post("/resume/view_full")
        async def view_full_resume(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await view_full_resume_action(page, chat_id)

        @self.app.post("/resume/check_full_resume_available")
        async def check_full_resume(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            resume_button = await check_full_resume_available(page, chat_id)
            return resume_button is not None

        @self.app.post("/resume/online")
        async def view_online_resume_api(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await view_online_resume_action(page, chat_id)

        @self.app.post("/resume/accept")
        async def accept_resume_api(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await accept_full_resume_action(page, chat_id)

        @self.app.post("/candidate/discard")
        async def discard_candidate_api(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await discard_candidate_action(page, chat_id)

        @self.app.get("/recommend/candidates")
        async def get_recommended_candidates(
            limit: int = Query(20, ge=1, le=100),
            job_title: str = Query(None, description="Job title to filter recommendations")
        ):
            page = await self._ensure_browser_session()
            return await list_recommended_candidates_action(page, limit=limit, job_title=job_title)

        @self.app.get("/recommend/candidate/{index}/resume")
        async def view_recommended_candidate_resume(index: int):
            page = await self._ensure_browser_session()
            return await view_recommend_candidate_resume_action(page, index)

        @self.app.post("/recommend/candidate/{index}/greet")
        async def greet_recommended_candidate(index: int, message: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await greet_recommend_candidate_action(page, index, message)

        @self.app.post("/recommend/select-job")
        async def select_recommend_job(job_title: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            frame = await _prepare_recommendation_page(page)
            return await select_recommend_job_action(frame, job_title)


        # Assistant QA endpoints
        # @self.app.post("/assistant/analyze-candidate")
        # def analyze_candidate_api(payload: dict = Body(...)):
        #     return self.assistant_actions.analyze_candidate(**payload)

        # ------------------ Thread API ------------------

        @self.app.post("/assistant/generate-message")
        def generate_message(data: dict = Body(...)):
            return assistant_actions.generate_message(**data)

        @self.app.get("/candidate/{chat_id}")
        def get_candidate_api(chat_id: str, fields: Optional[List[str]] = ["*"]):
            """Get candidate information from the store."""
            return candidate_store.get_candidate_by_id(chat_id, fields)

        @self.app.post("/thread/init-chat")
        async def init_chat_api(data: dict = Body(...)):
            """Initialize chat thread."""
            return assistant_actions.init_chat(**data)

        @self.app.get('thread/{thread_id}/messages')
        def get_thread_messages_api(thread_id: str):
            return assistant_actions.get_thread_messages(thread_id)

        ##------ OpenAI API ------
        @self.app.get("/assistant/list")
        def list_assistants_api():
            """List openai assistants."""
            assistants = assistant_actions.get_assistants()
            return [assistant.model_dump() for assistant in assistants.data]

        @self.app.post("/assistant/create")
        def create_assistant_api(payload: dict = Body(...)):
            """Create a new openai assistant."""
            client = assistant_actions.get_openai_client()
            assistant = client.beta.assistants.create(**payload)
            return assistant.model_dump()

        @self.app.post("/assistant/update/{assistant_id}")
        def update_assistant_api(assistant_id: str, payload: dict = Body(...)):
            client = assistant_actions.get_openai_client()
            assistant = client.beta.assistants.update(assistant_id, **payload)
            assistant_actions.get_assistants.cache_clear()
            return assistant.model_dump()

        @self.app.delete("/assistant/delete/{assistant_id}")
        def delete_assistant_api(assistant_id: str):
            client = assistant_actions.get_openai_client()
            client.beta.assistants.delete(assistant_id)
            assistant_actions.get_assistants.cache_clear()
            return True

        # System / debug endpoints
        @self.app.post("/restart")
        async def soft_restart_endpoint():
            await self.soft_restart()
            return True

        @self.app.get("/debug/page")
        async def debug_page():
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
    """Landing page for web UI."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/web/stats", response_class=HTMLResponse, tags=["web"])
async def web_stats():
    """Get quick stats for dashboard."""
    # Get message counts from chat stats
    new_messages = 0
    new_greets = 0
    try:
        page = await service._ensure_browser_session()
        stats = await get_chat_stats_action(page)
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
    """Get recent activity for dashboard."""
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
