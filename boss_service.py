#!/usr/bin/env python3
"""
Boss直聘后台服务（FastAPI版） - 保持登录状态，提供API接口
"""
from ast import pattern
import re
from playwright.sync_api import sync_playwright, expect
import sys
import os
import time
import json
import threading
import hashlib
from datetime import datetime
from fastapi import FastAPI, Query, Request, Body
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from contextlib import asynccontextmanager
import signal
import tempfile # Import tempfile
import logging # Import logging
import shutil # Import shutil

from src.config import settings
from src.ui_utils import ensure_on_chat_page, find_chat_item
from src.chat_actions import (
    request_resume_action,
    send_message_action,
    view_full_resume_action,
    discard_candidate_action,
    get_messages_list_action,
    get_chat_history_action,
    select_chat_job_action,
    view_online_resume_action,
    accept_resume_action,
    check_full_resume_available,
    get_chat_stats_action,
)
from src.recommendation_actions import (
    list_recommended_candidates_action,
    view_recommend_candidate_resume_action,
    greet_recommend_candidate_action,
    select_recommend_job_action,
    _prepare_recommendation_page,
)
from src.events import EventManager
from src.global_logger import get_logger
from src.qa_store import qa_store
from src.assistant_actions import assistant_actions, DEFAULT_GREETING
from src.scheduler import BRDWorkScheduler
from typing import Any, Dict, List, Optional, Callable, Tuple, Union


# Get global logger once at module level
logger = get_logger()

DEFAULT_GREET_MESSAGE = (
    "您好，我们是一家AI科技公司，是奔驰全球创新代表中唯一的中国公司，"
    "代表中国参加中德Autobahn汽车大会，是华为云自动驾驶战略合作伙伴中唯一创业公司，"
    "也是经过华为严选的唯一产品级AI数据合作伙伴。您对我们岗位有没有兴趣？"
)

class BossService:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(BossService, cls).__new__(cls)
        return cls._instance

    def _setup_logging(self):
        """Set up file and console logging.
        
        Configures logging with both file and console handlers.
        Creates a log file in the project root directory and sets up
        the global logger for use throughout the application.
        """

        # Correctly set the log file path to the project's root directory
        log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'service.log')
        
        # Create a logger specifically for this service
        service_logger = logging.getLogger("boss_service")
        service_logger.setLevel(logging.INFO)
        
        # Only add handlers if they don't exist
        if not service_logger.handlers:
            # File handler
            file_handler = logging.FileHandler(log_file, mode='a')
            file_handler.setLevel(logging.INFO)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # File formatter (no colors for file)
            file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            
            # Console formatter (with colors, no logger name)
            from src.global_logger import ColoredFormatter
            console_formatter = ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)
            
            # Add handlers
            service_logger.addHandler(file_handler)
            service_logger.addHandler(console_handler)


    def __init__(self):
        if not hasattr(self, 'initialized'):
            self._setup_logging()
            self.app = FastAPI(lifespan=self.lifespan)
            self.playwright = None
            self.context = None # The primary browser object
            self.page = None
            self.is_logged_in = False
            self.shutdown_requested = False
            self.startup_complete = threading.Event() # Event to signal startup completion
            self.scheduler: BRDWorkScheduler | None = None
            self.scheduler_lock = threading.Lock()
            self.scheduler_config: dict[str, Any] = {}
            self.qa_store = qa_store
            if getattr(self.qa_store, "enabled", False):
                logger.info("QA store initialised and connected to Zilliz")
            else:
                logger.info("QA store disabled or not configured")
            self.assistant_actions = assistant_actions
            self.initialized = True
            self.setup_routes()
            # 事件驱动的消息缓存和响应监听器
            self.event_manager = EventManager(logger=logging.getLogger(__name__))
            
    def _service_base_url(self) -> str:
        return os.environ.get('BOSS_SERVICE_BASE_URL', 'http://127.0.0.1:5001')

    def _scheduler_status(self):
        with self.scheduler_lock:
            running = self.scheduler is not None
            config = dict(self.scheduler_config) if running else {}
        return {
            'running': running,
            'config': config,
        }

    def _stop_scheduler(self) -> tuple[bool, str]:
        with self.scheduler_lock:
            if not self.scheduler:
                return False, '调度器未运行'
            scheduler = self.scheduler
            self.scheduler = None
            self.scheduler_config = {}
        try:
            scheduler.stop()
            return True, '已停止调度器'
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"停止调度器失败: {exc}")
            return False, f'停止调度器失败: {exc}'

    def _start_scheduler(self, payload) -> tuple[bool, str]:
        with self.scheduler_lock:
            if self.scheduler:
                return False, '调度器已运行'
            try:
                options = self._build_scheduler_options(payload)
                scheduler = BRDWorkScheduler(**options)
                scheduler.start()
                self.scheduler = scheduler
                self.scheduler_config = options
                return True, '调度器已启动'
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(f"启动调度器失败: {exc}")
                self.scheduler = None
                self.scheduler_config = {}
                return False, f'启动调度器失败: {exc}'

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _build_scheduler_options(self, payload):
        base_url = payload.get('base_url') or self._service_base_url()
        criteria_path = payload.get('criteria_path') or os.environ.get('BOSS_CRITERIA_PATH', 'config/jobs.yaml')

        options = {
            'base_url': base_url.rstrip('/'),
            'criteria_path': os.path.abspath(criteria_path),
            'role_id': payload.get('role_id', 'default'),
            'poll_interval': self._coerce_int(payload.get('poll_interval'), 120),
            'recommend_interval': self._coerce_int(payload.get('recommend_interval'), 600),
            'followup_interval': self._coerce_int(payload.get('followup_interval'), 3600),
            'report_interval': self._coerce_int(payload.get('report_interval'), 604800),
            'inbound_limit': self._coerce_int(payload.get('inbound_limit'), 40),
            'recommend_limit': self._coerce_int(payload.get('recommend_limit'), 20),
        }

        greeting_template = payload.get('greeting_template')
        if isinstance(greeting_template, str) and greeting_template.strip():
            options['greeting_template'] = greeting_template

        return options

    def _compose_greeting_context(self, chat_id: str) -> str:
        cache_entry = None
        try:
            cache_entry = self.event_manager.chat_cache.get(chat_id)
        except Exception:
            cache_entry = None
        if cache_entry:
            candidate = cache_entry.get('candidate') or cache_entry.get('name') or ''
            job_title = cache_entry.get('job_title') or ''
            latest_message = cache_entry.get('message') or ''
            parts = [
                f"候选人: {candidate}" if candidate else None,
                f"意向岗位: {job_title}" if job_title else None,
                f"最近留言: {latest_message}" if latest_message else None,
            ]
            context = "；".join(part for part in parts if part)
            if context:
                return context
        return f"Chat ID: {chat_id}"

    def send_greeting(self, chat_id: str, message: str | None = None) -> Dict[str, Any]:
        self._ensure_browser_session()
        context = self._compose_greeting_context(chat_id)
        final_message = message if message else self.assistant_actions.generate_greeting(context, DEFAULT_GREETING)
        result = send_message_action(self.page, chat_id, final_message)
        success = result.get('success', False)
        if success and getattr(self.assistant_actions, 'enabled', False):
            try:
                cache_entry = self.event_manager.chat_cache.get(chat_id)
            except Exception:
                cache_entry = None
            job_title = (cache_entry or {}).get('job_title', '')
            keywords = ['greeting']
            if job_title:
                keywords.append(job_title)
            try:
                self.assistant_actions.record_qa(
                    qa_id=f"greet_{chat_id}",
                    question=context,
                    answer=final_message,
                    keywords=keywords,
                )
            except Exception as exc:
                logger.debug("Failed to persist greeting QA: %s", exc)
        return {
            'success': success,
            'message': final_message,
            'details': result.get('details', ''),
        }

    def _startup_sync(self):
        """Synchronous startup tasks executed in a thread pool.

        Initializes Playwright, starts the browser, and sets up the service.
        This method is called during FastAPI startup to prepare the service
        for handling requests.
        """
        try:
            logger.info("正在初始化Playwright...")
            self.playwright = sync_playwright().start()
            logger.info("Playwright初始化成功。")
            self.start_browser()
            # Do NOT call ensure_login here. Let it be called lazily.
        except Exception as e:
            logger.error(f"同步启动任务失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            self.startup_complete.set() # Signal that startup is finished

    def _shutdown_sync(self):
        """Synchronous shutdown tasks executed in a thread pool.
        
        Performs graceful shutdown of the service, including cleanup of
        Playwright resources and browser contexts.
        """
        logger.info("开始同步关闭任务...")
        self._graceful_shutdown()
        self._stop_scheduler()
        logger.info("同步关闭任务完成。")

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """FastAPI lifespan context manager.
        
        Handles startup and shutdown events for the FastAPI application.
        Ensures proper initialization and cleanup of browser resources.
        
        Args:
            app (FastAPI): The FastAPI application instance
        """
        # Startup logic
        logger.info("FastAPI lifespan: Startup event triggered.")
        await run_in_threadpool(self._startup_sync)
        
        yield
        # Shutdown logic
        logger.info("FastAPI lifespan: Shutdown event triggered.")
        await run_in_threadpool(self._shutdown_sync)

    def setup_routes(self):
        """设置API路由
        
        Configures all FastAPI routes and endpoints for the Boss直聘 service.
        Includes endpoints for candidates, messages, resumes, and other operations.
        """
        

        @self.app.get('/status')
        def get_status():
            """Get service status and login state.
            
            Returns:
                JSONResponse: Service status including login state and notification count
            """
            chat_stats = get_chat_stats_action(self.page)
            return JSONResponse({
                'status': 'running',
                'logged_in': self.is_logged_in,
                'timestamp': datetime.now().isoformat(),
                'new_message_count': chat_stats.get('new_message_count', 0), 
                'new_greet_count': chat_stats.get('new_greet_count', 0)
            })
        
        
        @self.app.post('/login')
        def login():
            """Check login status.
            
            Returns:
                JSONResponse: Login status and success message
            """
            self._ensure_browser_session()
            return JSONResponse({
                'success': self.is_logged_in,
                'message': '登录成功' if self.is_logged_in else '登录失败',
                'timestamp': datetime.now().isoformat()
            })
        
        
        
        @self.app.get('/chat/dialogs')
        def get_messages(limit: int = Query(10, ge=1, le=100)):
            """Get list of chat dialogs/messages.
            
            Args:
                limit (int): Maximum number of messages to return (1-100)
                
            Returns:
                JSONResponse: List of messages with count and timestamp
            """
            self._ensure_browser_session()

            messages = get_messages_list_action(
                self.page, 
                limit, 
                chat_cache=self.event_manager.chat_cache
            )
            return JSONResponse({
                'success': True,
                'messages': messages,
                'count': len(messages),
                'timestamp': datetime.now().isoformat()
            })

        @self.app.get('/recommend/candidates')
        def get_recommended_candidates(limit: int = Query(20, ge=1, le=100)):
            """Get list of recommended candidates.
            
            Args:
                limit (int): Maximum number of candidates to return (1-100)
                
            Returns:
                JSONResponse: List of recommended candidates with success status
            """
            self._ensure_browser_session()
            result = list_recommended_candidates_action(self.page, limit=limit)

            candidates = result.get('candidates', [])
            return JSONResponse({
                'success': result.get('success', False),
                'candidates': candidates,
                'count': len(candidates),
                'details': result.get('details', ''),
                'timestamp': datetime.now().isoformat()
            })

        @self.app.get('/recommend/candidate/{index}')
        def view_recommended_candidate_resume(index: int):
            """View resume of a recommended candidate by index.
            
            Args:
                index (int): Index of the candidate in the recommended list
                
            Returns:
                JSONResponse: Candidate resume information
            """
            self._ensure_browser_session()
            result = view_recommend_candidate_resume_action(self.page, index)
            return JSONResponse(result)

        @self.app.post('/recommend/candidate/{index}/greet')
        def greet_recommended_candidate(index: int, payload: dict | None = Body(default=None)):
            """Send greeting message to recommended candidate by index."""
            self._ensure_browser_session()
            message = (payload or {}).get('message') or DEFAULT_GREET_MESSAGE
            result = greet_recommend_candidate_action(self.page, index, message)
            return JSONResponse({
                'success': result.get('success', False),
                'chat_id': result.get('chat_id'),
                'details': result.get('details', ''),
                'timestamp': datetime.now().isoformat()
            })

        @self.app.post('/recommend/select-job')
        def select_recommend_job(job_title: str = Body(..., embed=True)):
            """Select current job from dropdown menu.
            
            Args:
                payload: Dictionary containing 'job_title' key
                
            Returns:
                JSONResponse: Selection result with success status and details
            """
            self._ensure_browser_session()
            frame = _prepare_recommendation_page(self.page)
            result = select_recommend_job_action(frame, job_title)
            return JSONResponse({
                'success': result.get('success', False),
                'details': result.get('details', ''),
                'selected_job': result.get('selected_job'),
                'available_jobs': result.get('available_jobs'),
                'timestamp': datetime.now().isoformat()
            })
            

        '''
        Automation Scheduler Endpoints
        '''
        @self.app.get('/automation/scheduler/status')
        def scheduler_status():
            return JSONResponse(self._scheduler_status())

        @self.app.post('/automation/scheduler/start')
        def scheduler_start(payload: dict | None = Body(default=None)):
            success, details = self._start_scheduler(payload or {})
            status = self._scheduler_status()
            status.update({'success': success, 'details': details})
            return JSONResponse(status)

        @self.app.post('/automation/scheduler/stop')
        def scheduler_stop():
            success, details = self._stop_scheduler()
            status = self._scheduler_status()
            status.update({'success': success, 'details': details})
            return JSONResponse(status)

        '''
        Chat Endpoints
        '''
        @self.app.get('/chat/stats')
        def get_chat_stats():
            result = get_chat_stats_action(self.page)
            return result


        @self.app.post('/chat/{chat_id}/greet')
        def greet_candidate(chat_id: str, message: str | None = Body(default=None)):
            """Send a greeting message to a candidate.
            
            Args:
                chat_id (str): ID of the chat/conversation
                message (str, optional): Custom greeting message. Defaults to standard greeting.
                
            Returns:
                JSONResponse: Success status and message
            """
            result = self.send_greeting(chat_id, message)
            return JSONResponse({
                'success': result.get('success', False),
                'message': result.get('message'),
                'details': result.get('details', ''),
                'timestamp': datetime.now().isoformat()
            })
        

        @self.app.post('/chat/{chat_id}/send')
        def send_message_api(chat_id: str, message: str = Body(..., embed=True)):
            """Send a text message to a specific conversation.
            
            Args:
                chat_id (str): ID of the chat/conversation
                message (str): Message content to send
                
            Returns:
                JSONResponse: Success status and details
            """
            self._ensure_browser_session()

            result = send_message_action(self.page, chat_id, message)
            return JSONResponse({
                'success': result.get('success', False),
                'chat_id': chat_id,
                'message': message,
                'details': result.get('details', ''),
                'timestamp': datetime.now().isoformat()
            })

        @self.app.get('/chat/{chat_id}/messages')
        def get_message_history(chat_id: str):
            """Get chat history for a specific conversation.
            
            Args:
                chat_id (str): ID of the chat/conversation
                
            Returns:
                JSONResponse: Chat history with message count
            """
            self._ensure_browser_session()

            history = get_chat_history_action(self.page, chat_id)
            return JSONResponse({
                'success': True,
                'chat_id': chat_id,
                'messages': history,
                'count': len(history),
                'timestamp': datetime.now().isoformat()
            })


        @self.app.post('/chat/select-job')
        def select_chat_job(payload: dict = Body(...)):
            """Select job for a specific conversation.
            
            Args:
                payload: Dictionary containing 'job_title' key
                
            Returns:
                JSONResponse: Selection result with success status and details
            """
            self._ensure_browser_session()
            job_title = payload.get('job_title')
            if not job_title:
                return JSONResponse({
                    'success': False,
                    'details': 'Missing required parameter: job_title'
                })
            
            result = select_chat_job_action(self.page, job_title)
            return JSONResponse({
                'success': result.get('success', False),
                'details': result.get('details', ''),
                'selected_job': result.get('selected_job'),
                'available_jobs': result.get('available_jobs'),
                'timestamp': datetime.now().isoformat()
            })

        '''
        Resume Endpoints
        '''
        @self.app.post('/resume/request')
        def request_resume_api(chat_id: str = Body(..., embed=True)):
            """Request resume from a candidate.
            
            Args:
                chat_id (str): ID of the chat/conversation
                
            Returns:
                JSONResponse: Success status and details
            """
            self._ensure_browser_session()

            result = request_resume_action(self.page, chat_id)
            return JSONResponse({
                'success': result.get('success', False),
                'chat_id': chat_id,
                'already_sent': result.get('already_sent', False),
                'details': result.get('details', ''),
                'timestamp': datetime.now().isoformat()
            })


        @self.app.post('/resume/view_full')
        def view_full_resume(chat_id: str = Body(..., embed=True)):
            """View candidate's attached resume.
            
            Args:
                chat_id (str): ID of the chat/conversation
                
            Returns:
                JSONResponse: Resume viewing result
            """
            self._ensure_browser_session()

            result = view_full_resume_action(self.page, chat_id)
            return result

        @self.app.post('/resume/check_full')
        def check_full_resume(chat_id: str = Body(..., embed=True)):
            """Check if full resume is available without retrieving content."""
            self._ensure_browser_session()
            result = check_full_resume_available(self.page, chat_id)
            if result is None:
                return JSONResponse({
                    'success': False,
                    'available': False,
                    'details': '未找到指定对话项',
                })
            return JSONResponse({
                'success': result.get('success', False),
                'available': result.get('success', False),
                'details': result.get('details', ''),
            })

        @self.app.post('/resume/online')
        def view_online_resume_api(chat_id: str = Body(..., embed=True)):
            """View online resume and return canvas image base64 data.
            
            Opens the conversation and views the online resume, capturing
            canvas content and returning base64 encoded image data.
            
            Args:
                chat_id (str): ID of the chat/conversation
                
            Returns:
                JSONResponse: Resume data including text, HTML, images, and metadata
            """
            # 会话与登录
            self._ensure_browser_session()

            result = view_online_resume_action(self.page, chat_id)
            return JSONResponse({
                'success': result.get('success', False),
                'chat_id': chat_id,
                'text': result.get('text'),
                'html': result.get('html'),
                'image_base64': result.get('image_base64'),
                'images_base64': result.get('images_base64'),
                'data_url': result.get('data_url'),
                'width': result.get('width'),
                'height': result.get('height'),
                'details': result.get('details', ''),
                'error': result.get('error'),
                'timestamp': datetime.now().isoformat(),
                'capture_method': result.get('capture_method'),
            })

        @self.app.post('/resume/accept')
        def accept_resume_api(chat_id: str = Body(..., embed=True)):
            """Accept a candidate by clicking "接受" button.
            
            Args:
                chat_id (str): ID of the chat/conversation
                
            Returns:
                JSONResponse: Success status and details
            """
            self._ensure_browser_session()
            
            result = accept_resume_action(self.page, chat_id)
            return JSONResponse({
                'success': result.get('success', False),
                'chat_id': chat_id,
                'details': result.get('details', ''),
                'timestamp': datetime.now().isoformat()
            })

        '''
        Candidate Endpoints
        '''

        @self.app.post('/candidate/discard')
        def discard_candidate_api(chat_id: str = Body(..., embed=True)):
            """Discard a candidate by clicking "不合适" button.
            
            Args:
                chat_id (str): ID of the chat/conversation
                
            Returns:
                JSONResponse: Success status and details
            """
            self._ensure_browser_session()

            result = discard_candidate_action(self.page, chat_id)
            return JSONResponse({
                'success': result.get('success', False),
                'chat_id': chat_id,
                'details': result.get('details', ''),
                'timestamp': datetime.now().isoformat()
            })

        
        '''
        System Endpoints
        '''
        @self.app.post('/restart')
        def soft_restart():
            """Soft restart the API service while keeping browser session.
            
            Returns:
                JSONResponse: Success status and message
            """
            self.soft_restart()
            return JSONResponse({
                'success': True,
                'message': 'API服务已重启，浏览器会话保持',
                'timestamp': datetime.now().isoformat()
            })
        
        @self.app.get('/debug/page')
        def debug_page():
            """Debug endpoint - get current page content.
            
            Returns:
                JSONResponse: Page information including URL, title, content, and metadata
            """
            self._ensure_browser_session()
            
            # 等待页面完全渲染（事件驱动）
            self.page.locator("body").wait_for(state="visible", timeout=5000)
            self.page.wait_for_load_state("networkidle", timeout=5000)
            
            if not self.page or self.page.is_closed():
                return JSONResponse({
                    'success': False,
                    'error': '页面未打开或已关闭',
                    'timestamp': datetime.now().isoformat()
                })
            
            # 获取页面信息
            full_content = self.page.content()
            # 截取前5000个字符，避免返回过长的HTML
            readable_content = full_content[:5000] + "..." if len(full_content) > 5000 else full_content
            
            page_info = {
                'url': self.page.url,
                'title': self.page.title(),
                'content': readable_content,
                'content_length': len(full_content),
                'screenshot': None,
                'cookies': [],
                'local_storage': {},
                'session_storage': {}
            }
            
            return JSONResponse({
                'success': True,
                'page_info': page_info,
                'timestamp': datetime.now().isoformat()
            })
        
        @self.app.get('/debug/cache')
        def get_cache_stats():
            """Get event cache statistics.
            
            Returns:
                JSONResponse: Cache statistics and performance metrics
            """
            stats = self.event_manager.get_cache_stats()
            return JSONResponse({
                'success': True,
                'cache_stats': stats,
                'timestamp': datetime.now().isoformat()
            })
    
    def _resolve_storage_state_path(self):
        """Resolve storage state path with environment variable priority.
        
        Priority order:
        1. BOSS_STORAGE_STATE_JSON: Direct JSON string from environment
        2. BOSS_STORAGE_STATE_FILE: File path from environment
        3. settings.STORAGE_STATE: Default configuration
        
        Returns:
            str: Path to the storage state file
        """
        env_json = os.environ.get("BOSS_STORAGE_STATE_JSON")
        if env_json:
            os.makedirs(os.path.dirname(settings.STORAGE_STATE), exist_ok=True)
            # 验证JSON
            _ = json.loads(env_json)
            with open(settings.STORAGE_STATE, "w", encoding="utf-8") as f:
                f.write(env_json)
            logger.info("已从环境变量写入登录状态(JSON)")
            return settings.STORAGE_STATE
        
        env_path = os.environ.get("BOSS_STORAGE_STATE_FILE")
        if env_path and os.path.exists(env_path):
            return env_path
        return settings.STORAGE_STATE
    
    def _get_user_data_dir(self):
        """Get the path to the user data directory.
        
        Returns:
            str: Path to the temporary user data directory for browser session
        """
        # Use a temporary directory to store browser session data
        # This will persist across service restarts but be cleaned up on system reboot
        return os.path.join(tempfile.gettempdir(), "bosszhipin_playwright_user_data")
        

    def start_browser(self):
        """Launch a persistent browser context with recovery.
        
        Connects to an external Chrome instance via CDP and sets up
        the browser context for automation. Configures event listeners
        and navigates to the chat page.
        """
        logger.info("正在启动持久化浏览器会话...")
        user_data_dir = self._get_user_data_dir()
        logger.info(f"使用用户数据目录: {user_data_dir}")

        if not getattr(self, 'playwright', None):
            logger.info("Playwright尚未初始化，正在启动...")
            self.playwright = sync_playwright().start()

        logger.info(f"尝试通过CDP连接浏览器: {settings.CDP_URL}")
        browser = self.playwright.chromium.connect_over_cdp(settings.CDP_URL)
        self.context = browser.contexts[0] if browser.contexts else browser.new_context()


        
        pages = list(self.context.pages)
        if pages:
            self.page = pages[0]
        else:
            self.page = self.context.new_page()

        if self.context:
            self.event_manager.setup(self.context)
            logger.info("事件管理器设置成功")

        if settings.BASE_URL not in getattr(self.page, 'url', ''):
            logger.info("导航到聊天页面...")
            self.page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=3000)
        else:
            logger.info("已导航到聊天页面")

        logger.info("持久化浏览器会话启动成功！")
        
            
    def _load_saved_login_state(self):
        """Load saved login state from storage.
        
        Checks for existing login state file and validates cookies
        to determine if user was previously logged in.
        """
        if os.path.exists(settings.STORAGE_STATE):
            with open(settings.STORAGE_STATE, 'r') as f:
                storage_state = json.load(f)
            
            if storage_state.get('cookies'):
                logger.info("发现已保存的登录状态")

    def save_login_state(self):
        """Save current login state to storage.
        
        Persists browser context state including cookies and session data
        to enable login persistence across service restarts.
        
        Returns:
            bool: True if login state was saved successfully
        """
        os.makedirs(os.path.dirname(settings.STORAGE_STATE), exist_ok=True)
        
        context = self.page.context
        context.storage_state(path=settings.STORAGE_STATE)
        
        logger.info(f"登录状态已保存到: {settings.STORAGE_STATE}")
        
        self.is_logged_in = True
        logger.info("用户登录状态已确认并保存")
        return True
    
    def check_login_status(self):
        """Check current login status.
        
        Navigates to the chat page and analyzes page content to determine
        if the user is logged in. Handles various login states including
        slider verification and login redirects.
        
        Returns:
            bool: True if user is logged in, False otherwise
        """
        self.page.goto(settings.BASE_URL.rstrip('/') + "/web/chat/index",
                         wait_until="domcontentloaded", timeout=10000)
        self.page.wait_for_load_state("networkidle", timeout=5000)
            
        page_text = self.page.locator("body").inner_text()
        current_url = self.page.url
        if "/web/user/safe/verify-slider" in current_url:
            logger.warning("检测到滑块验证页面，请在浏览器中完成验证...")
            start = time.time()
            while time.time() - start < 300:
                self.page.wait_for_timeout(1000)
                current_url = self.page.url
                if "/web/user/safe/verify-slider" not in current_url:
                    break
            
            if ("登录" in page_text and ("立即登录" in page_text or "登录/注册" in page_text)) or "login" in current_url.lower():
                logger.warning("检测到需要登录")
                return False
            
            if any(keyword in page_text for keyword in ["消息", "沟通", "聊天", "候选人", "简历"]):
                logger.info("登录状态正常")
                return True
            
            logger.warning("登录状态不明确")
            return False
    
    
    
    def _graceful_shutdown(self):
        """Gracefully shut down Playwright resources.
        
        Performs cleanup of browser contexts and Playwright instances.
        For CDP-attached browsers, only detaches listeners without closing
        the shared browser context.
        """
        logger.info("执行优雅关闭...")
        if hasattr(self, 'context') and self.context:
            pass
        
        if self.playwright:
            self.playwright.stop()
            logger.info("Playwright已停止。")
        
        self.context = None
        self.page = None
        self.playwright = None
        logger.info("Playwright资源已清理")
    

    def _ensure_browser_session(self, max_wait_time=600):
        """Ensure browser session and login status.
        
        Verifies that browser context and page are available, and that
        the user is logged in. Handles session recovery and login verification
        with configurable timeout.
        
        Args:
            max_wait_time (int): Maximum time to wait for login (seconds)
            
        Raises:
            Exception: If login timeout is exceeded
        """
        if not self.context:
            logger.warning("浏览器Context不存在，将重新启动。")
            self.start_browser()
            return

        if not self.page or self.page.is_closed():
            pages = list(self.context.pages)
            for page in pages:
                if settings.CHAT_URL in getattr(page, 'url', ''):
                    self.page = page
                    break
            else:
                self.page = pages[0] if pages else self.context.new_page()
                if settings.CHAT_URL not in getattr(self.page, 'url', ''):
                    self.page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=10000)
                    self.page.wait_for_load_state("networkidle", timeout=5000)

        # Check if page is still valid without causing errors
        try:
            _ = self.page.title()
        except Exception:
            # Page context was destroyed, recreate it
            logger.warning("Page context lost, recreating browser session...")
            try:
                self.page = self.context.new_page()
                self.page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=10000)
                self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception as e:
                logger.error(f"Failed to recreate page: {e}")
                # If context is also broken, restart browser
                self.start_browser()
                return

        if not self.is_logged_in:
            logger.info("正在检查登录状态...")
            
            if settings.BASE_URL in self.page.url and "加载中" not in self.page.content():
                page_text = self.page.locator("body").inner_text()
                login_indicators = ["消息", "聊天", "对话", "沟通", "候选人", "简历", "打招呼"]
                if any(indicator in page_text for indicator in login_indicators):
                    self.is_logged_in = True
                    self.save_login_state()
                    logger.info("已在聊天页面，登录状态确认。")
                    return
                
                conversation_elements = self.page.locator("xpath=//li[contains(@class, 'conversation') or contains(@class, 'chat') or contains(@class, 'item')]")
                if conversation_elements.count() > 0:
                    self.is_logged_in = True
                    self.save_login_state()
                    logger.info("检测到对话列表，登录状态确认。")
                    return
            
            self.page.wait_for_load_state("networkidle", timeout=5000)
            current_url = self.page.url
            
            if settings.LOGIN_URL in current_url or "web/user" in current_url or "login" in current_url.lower() or "bticket" in current_url:
                logger.warning("检测到登录页面，请手动完成登录...")
                logger.info("等待用户登录，最多等待10分钟...")
                
                start_time = time.time()
                while time.time() - start_time < max_wait_time:
                    current_url = self.page.url
                    page_text = self.page.locator("body").inner_text()
                    
                    if (settings.CHAT_URL in current_url or 
                        any(keyword in page_text for keyword in ["消息", "沟通", "聊天", "候选人", "简历"])):
                        logger.info("检测到用户已登录！")
                        break
                    
                    if "登录" in page_text and ("立即登录" in page_text or "登录/注册" in page_text):
                        logger.info("请在浏览器中完成登录...")
                    
                    elapsed = time.time() - start_time
                    remaining = max_wait_time - elapsed
                    minutes = int(remaining // 60)
                    seconds = int(remaining % 60)
                    print(f"\r⏰ 等待登录中... 剩余时间: {minutes:02d}:{seconds:02d}", end="", flush=True)
                    
                    time.sleep(3)
                
                print("\r" + " " * 50 + "\r", end="", flush=True)
                
                if not self.is_logged_in:
                    raise Exception("等待登录超时，请手动登录后重试")
            else:
                logger.info("等待聊天页面加载...")
                self.page.wait_for_url(
                    settings.BASE_URL,
                    timeout=6000, # 10 minutes
                )
            
            self.page.wait_for_function(
                "() => !document.body.innerText.includes('加载中，请稍候')",
                timeout=30000
            )
            self.is_logged_in = True
            self.save_login_state()
            logger.info("登录成功并已在聊天页面。")


    
    def _shutdown_thread(self, keep_browser=False):
        """Run graceful shutdown in a separate thread to avoid blocking.
        
        Args:
            keep_browser (bool): Whether to keep browser session alive
        """
        logger.info(f"在单独的线程中执行关闭(keep_browser={keep_browser})...")
        self._graceful_shutdown()

    def _handle_signal(self, signum, frame):
        """Handle system signals for graceful shutdown.
        
        Args:
            signum: Signal number
            frame: Current stack frame
        """
        logger.info(f"收到信号: {signum}")
        # Run shutdown in a separate thread to avoid greenlet/asyncio conflicts
        keep_browser = (signum == signal.SIGTERM)
        shutdown_thread = threading.Thread(target=self._shutdown_thread, args=(keep_browser,))
        shutdown_thread.start()

    def run(self, host='127.0.0.1', port=5001):
        """Run the service using uvicorn (called externally).
        
        Args:
            host (str): Host address to bind to
            port (int): Port number to bind to
        """
        import uvicorn
        logger.info("启动Boss直聘后台服务(FastAPI)...")
        uvicorn.run("boss_service:app", host=host, port=port, reload=True, log_level="info")

service = BossService()
app = service.app

if __name__ == "__main__":
    # host = os.environ.get("BOSS_SERVICE_HOST", "127.0.0.1")
    # try:
    #     port = int(os.environ.get("BOSS_SERVICE_PORT", "5001"))
    # except Exception:
    #     port = 5001
    # service.run(host=host, port=port)
    print('不应该从这里启动服务，请运行start_service.py')
