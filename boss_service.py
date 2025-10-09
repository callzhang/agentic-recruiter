#!/usr/bin/env python3
"""Async FastAPI service that automates Boss直聘 via Playwright."""

from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, Query, Request
from playwright.async_api import Browser, BrowserContext, Page, Playwright, TimeoutError as PlaywrightTimeoutError, async_playwright

from src.assistant_actions import assistant_actions
from src.candidate_store import candidate_store
from src.config import settings
from src.global_logger import logger
from src.chat_actions import (
    accept_resume_action,
    check_full_resume_available,
    discard_candidate_action,
    get_chat_history_action,
    get_chat_list_action,
    get_chat_stats_action,
    request_resume_action,
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
        self.app = FastAPI(lifespan=self.lifespan)
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_logged_in = False
        self.browser_lock = asyncio.Lock()
        self.startup_complete = asyncio.Event()
        self.candidate_store = candidate_store
        self.assistant_actions = assistant_actions
        self.event_manager = None  # Placeholder for legacy debug endpoint
        self.setup_routes()

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
        logger.info("连接 Chrome CDP: %s", settings.CDP_URL)
        self.browser = await self.playwright.chromium.connect_over_cdp(settings.CDP_URL)
        self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
        self.page = await self._ensure_page()
        logger.info("持久化浏览器会话已建立。")

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
        try:
            self.assistant_actions.stop_scheduler()
        except Exception:
            pass

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

        @self.app.post("/chat/send")
        async def send_message_api(chat_id: str = Body(..., embed=True), message: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await send_message_action(page, chat_id, message)

        @self.app.post("/chat/greet")
        async def greet_candidate(
            chat_id: str = Body(..., embed=True), 
            message: str = Body(..., embed=True)
        ):
            page = await self._ensure_browser_session()
            payload = await send_message_action(page, chat_id, message.strip())
            return payload

        @self.app.get("/chat/stats")
        async def get_chat_stats():
            page = await self._ensure_browser_session()
            return await get_chat_stats_action(page)

        @self.app.post("/resume/request")
        async def request_resume_api(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await request_resume_action(page, chat_id)

        @self.app.post("/resume/view_full")
        async def view_full_resume(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await view_full_resume_action(page, chat_id)

        @self.app.post("/resume/check_full_resume_available")
        async def check_full_resume(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            result = await check_full_resume_available(page, chat_id)
            if isinstance(result, dict):
                return result.get("success", False)
            return bool(result)

        @self.app.post("/resume/online")
        async def view_online_resume_api(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await view_online_resume_action(page, chat_id)

        @self.app.post("/resume/accept")
        async def accept_resume_api(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await accept_resume_action(page, chat_id)

        @self.app.post("/candidate/discard")
        async def discard_candidate_api(chat_id: str = Body(..., embed=True)):
            page = await self._ensure_browser_session()
            return await discard_candidate_action(page, chat_id)

        @self.app.get("/recommend/candidates")
        async def get_recommended_candidates(limit: int = Query(20, ge=1, le=100)):
            page = await self._ensure_browser_session()
            result = await list_recommended_candidates_action(page, limit=limit)
            return result.get("candidates", [])

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

        # Scheduler
        # @self.app.get("/automation/scheduler/status")
        # def scheduler_status():
        #     return self.assistant_actions.get_scheduler_status()

        # @self.app.post("/automation/scheduler/start")
        # def scheduler_start(payload: Optional[dict] = Body(default=None)):
        #     success, details = self.assistant_actions.start_scheduler(payload or {})
        #     status = self.assistant_actions.get_scheduler_status()
        #     status.update({"success": success, "details": details})
        #     return status

        # @self.app.post("/automation/scheduler/stop")
        # def scheduler_stop():
        #     success, details = self.assistant_actions.stop_scheduler()
        #     return {"success": success, "details": details}

        # Assistant QA endpoints
        # @self.app.post("/assistant/analyze-candidate")
        # def analyze_candidate_api(payload: dict = Body(...)):
        #     return self.assistant_actions.analyze_candidate(**payload)

        # ------------------ Thread API ------------------

        @self.app.post("/assistant/generate-message")
        def generate_followup_api(data: dict = Body(...)):
            return self.assistant_actions.generate_message(**data)

        @self.app.get("/candidate/{chat_id}")
        def get_candidate_api(chat_id: str):
            """Get candidate information from the store."""
            return self.assistant_actions.get_candidate_by_id(chat_id)

        @self.app.post("/thread/init-chat")
        def init_chat_api(data: dict = Body(...)):
            return self.assistant_actions.init_chat(**data)

        @self.app.get('thread/{thread_id}/messages')
        def get_thread_messages_api(thread_id: str):
            return self.assistant_actions.get_thread_messages(thread_id)

        # @self.app.post("/assistant/retrieve-answers")
        # def retrieve_answers_api(payload: dict = Body(...)):
        #     query = payload.get("query", "")
        #     return self.assistant_actions.retrieve_relevant_answers(query)

        # @self.app.get("/assistant/list-entries")
        # def list_entries_api(limit: int = Query(10, ge=1, le=30)):
        #     return self.assistant_actions.list_entries(limit)

        # @self.app.post("/assistant/record-qa")
        # def record_qa_api(payload: dict = Body(...)):
        #     self.assistant_actions.record_qa(**payload)
        #     return True

        # @self.app.post("/assistant/delete-entry")
        # def delete_entry_api(payload: dict = Body(...)):
        #     entry_id = payload.get("entry_id")
        #     return self.assistant_actions.delete_entry(entry_id)

        ##------ OpenAI API ------
        @self.app.get("/assistant/list")
        def list_assistants_api():
            """List openai assistants."""
            assistants = self.assistant_actions.get_assistants()
            return [assistant.model_dump() for assistant in assistants.data]

        @self.app.post("/assistant/create")
        def create_assistant_api(payload: dict = Body(...)):
            """Create a new openai assistant."""
            assistant = self.assistant_actions.client.beta.assistants.create(
                **payload,
            )
            return assistant.model_dump()

        @self.app.post("/assistant/update/{assistant_id}")
        def update_assistant_api(assistant_id: str, payload: dict = Body(...)):
            assistant = self.assistant_actions.client.beta.assistants.update(
                assistant_id,
                **payload,
            )
            self.assistant_actions.get_assistants.cache_clear()
            return assistant.model_dump()

        @self.app.delete("/assistant/delete/{assistant_id}")
        def delete_assistant_api(assistant_id: str):
            self.assistant_actions.client.beta.assistants.delete(assistant_id)
            self.assistant_actions.get_assistants.cache_clear()
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

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("boss_service:app", host="0.0.0.0", port=5001, reload=False)
