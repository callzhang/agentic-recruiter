"""Scheduler for BRD-defined automation workflows."""

from __future__ import annotations

import copy
import csv
import logging
import os
import threading
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import NAMESPACE_URL, uuid5
from src.config import settings
from .global_logger import get_logger
logger = get_logger()

if TYPE_CHECKING:  # pragma: no cover - import guard
    from .assistant_actions import AssistantActions

class BRDWorkScheduler:
    """Coordinates inbound/outbound recruitment workflows defined in the BRD."""

    def __init__(
        self,
        *,
        job: Optional[Dict[str, Any]] = None,
        recommend_limit: Optional[int] = None,
        enable_recommend: Optional[bool] = None,
        enable_chat_processing: Optional[bool] = None,
        enable_followup: Optional[bool] = None,
        assistant: Optional["AssistantActions"] = None,
        overall_threshold: Optional[float] = None,
        threshold_greet: Optional[float] = None,
        threshold_borderline: Optional[float] = None,
        base_url: str = None  # API base URL for HTTP calls
    ) -> None:
        
        self.recommend_limit = recommend_limit
        self.assistant = assistant
        self.overall_threshold = overall_threshold
        self.dingtalk_webhook = settings.DINGTALK_URL
        self.base_url = base_url or settings.BOSS_SERVICE_BASE_URL  # API base URL

        self.enable_chat_processing = bool(enable_chat_processing)
        self.enable_recommend = bool(enable_recommend)
        self.enable_followup = bool(enable_followup)
        self.job_snapshot = job

        self._running = False
        self._stop_event = threading.Event()
        self._last_report_at = datetime.now()

        # Use job parameter directly - no need to load from YAML
        if not self.job_snapshot:
            raise ValueError("Job information must be provided as parameter")
        
        # Set thresholds from parameters
        self.threshold_greet = threshold_greet or 0.7
        self.threshold_borderline = threshold_borderline or 0.6
        
        # Set report interval (weekly)
        self.report_interval = 604800  # 7 days in seconds
        
        # Status tracking for real-time updates
        self._status_message = "调度器已启动，等待执行..."

        logger.debug(
            "BRD scheduler initialised: position=%s, greet>=%.2f, overall>=%.1f, inbound=%s, recommend=%s, followup=%s",
            self.job_snapshot.get("position", "AI岗位"),
            self.threshold_greet,
            self.overall_threshold,
            self.enable_chat_processing,
            self.enable_recommend,
            self.enable_followup,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        logger.info("启动BRD自动化调度：%s", self.job_snapshot.get("position"))
        
        # Start single sequential loop in a daemon thread
        self._main_thread = threading.Thread(target=self._main_loop, name="brd-main", daemon=True)
        self._main_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._running = False
        if hasattr(self, '_main_thread') and self._main_thread:
            self._main_thread.join(timeout=5)
        logger.info("BRD自动化调度已停止")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current scheduler status for real-time updates."""
        return {
            "running": self._running,
            "status_message": self._status_message,
            "timestamp": datetime.now().isoformat()
        }
    
    def _main_loop(self) -> None:
        """Main sequential loop that runs all tasks in sequence."""
        logger.info("BRD主循环启动")
        
        while not self._stop_event.is_set():
            # Run inbound processing
            if self.enable_chat_processing:
                self._status_message = "正在处理新聊天..."
                self._process_inbound_chats()
            
            # Run recommendation processing
            if self.enable_recommend:
                self._process_recommendations()
            
            # Set idle status
            self._status_message = "等待下次检查..."
            
            # Wait before next iteration
            self._wait(10)
        
        logger.info("BRD主循环结束")

    # ------------------------------------------------------------------
    # Processing Methods
    # ------------------------------------------------------------------

    def _wait(self, seconds: int) -> None:
        self._stop_event.wait(seconds)

    # ------------------------------------------------------------------
    # Inbound processing
    # ------------------------------------------------------------------
    def _process_inbound_chats(self) -> None:
        """Process inbound chats using browser automation."""
        from .chat_actions import get_chat_list_action
        messages = get_chat_list_action(self.page, limit=self.recommend_limit or 20)
        for entry in messages:
            chat_id = str(entry.get("id") or "").strip()
            if not chat_id:
                continue
            snippet = (entry.get("text") or "").strip()
            self._evaluate_chat(chat_id, snippet, source="inbound")

    def _evaluate_chat(self, chat_id: str, snippet: str, source: str) -> Dict[str, Any]:
        resume_text, resume_meta = self._fetch_resume(chat_id)
        if not resume_text:
            decision = "pending_resume"
            score = 0.0
            details = "无法获取在线简历"
        else:
            # Use AI analysis for scoring
            analysis = self._analyze_candidate_resume(resume_text, "")
            score = analysis.get("overall", 0.0) / 10.0  # Convert from 1-10 to 0-1 scale
            details = analysis.get("summary", "AI分析完成")
            if score >= self.threshold_greet:
                success = self._request_resume(chat_id)
                decision = "resume_requested" if success else "request_failed"
            elif score >= self.threshold_borderline:
                decision = "manual_review"
            else:
                success = self._discard_candidate(chat_id)
                decision = "discarded" if success else "discard_failed"

        record = {
            "chat_id": chat_id,
            "source": source,
            "snippet": snippet,
            "score": score,
            "decision": decision,
            "details": details,
            "timestamp": datetime.utcnow().isoformat(),
            "meta": resume_meta,
        }
        logger.info(
            "[%s] %s 分数 %.1f -> %s", source, chat_id, score * 100, decision
        )

    def _fetch_resume(self, chat_id: str) -> tuple[str, Dict[str, Any]]:
        """Fetch resume using browser automation instead of direct API calls."""
        from .chat_actions import view_online_resume_action
        result = view_online_resume_action(self.page, chat_id)
        if result.get("success"):
            return result.get("content", ""), result.get("meta", {})
        return "", {}

    def _request_resume(self, chat_id: str) -> bool:
        """Request resume using browser automation."""
        from .chat_actions import request_resume_action
        result = request_resume_action(self.page, chat_id)
        return result.get("success", False)

    def _discard_candidate(self, chat_id: str) -> bool:
        """Discard candidate using browser automation."""
        from .chat_actions import discard_candidate_action
        result = discard_candidate_action(self.page, chat_id)
        return result.get("success", False)

    # ------------------------------------------------------------------
    # Recommendation processing
    # ------------------------------------------------------------------
    def _process_recommendations(self) -> None:
        """Process recommendations using API calls."""
        self._status_message = "正在处理推荐候选人..."
            
        # Get recommended candidates via API
        response = requests.get(f"{self.base_url}/recommend/candidates", 
                              params={"limit": self.recommend_limit or 20})
        if response.status_code != 200:
            logger.warning("获取推荐候选人失败: HTTP %d", response.status_code)
            self._status_message = f"获取推荐候选人失败: HTTP {response.status_code}"
            return
            
        candidates = response.json()  # Now returns list directly
        self._status_message = f"找到 {len(candidates)} 个推荐候选人，开始处理..."
        for index, entry in enumerate(candidates):
            summary = entry.get('text')[:100].replace('\n', '')
            self._status_message = f"正在处理候选人: {summary}"
            
            summary = (entry.get("text") or "").strip() or f"candidate-{index}"
            candidate_id = self._build_candidate_id("recommend", index, summary)

            # Fetch resume
            self._status_message = f"获取候选人 {index + 1} 简历: {summary}"
            result = requests.get(f"{self.base_url}/recommend/candidate/{index}/resume")
            if result.status_code != 200:
                logger.warning("获取推荐候选人简历失败: HTTP %d", result.status_code)
                self._status_message = f"获取推荐候选人简历失败: HTTP {result.status_code}"
                continue
            resume_result = result.json()
            resume_text = resume_result.get("text", "")
            assert resume_text, "获取推荐候选人简历失败"
            
            # Analyze candidate
            self._status_message = f"分析候选人 {index + 1} 简历"
            analysis = self._analyze_candidate_resume(resume_text, summary)
            overall = analysis.get("overall")
            self._status_message = f"分析候选人 {index + 1} 得分: {overall}, {analysis.get('summary')}"
            decision = True if overall >= self.overall_threshold else False

            metadata = {
                "source": "recommendation",
                "index": index,
                "summary": summary,
                "analysis": analysis,
                "greeted": False,
            }
            greeting_message = ''

            if resume_text and overall >= self.overall_threshold:
                # Send greeting
                self._status_message = f"向候选人 {index + 1} 发送打招呼"
                greeting_message = self.assistant.generate_greeting_message(
                    candidate_summary=summary,
                    candidate_resume=resume_text,
                    job_info=self.job_snapshot,
                )
                greet_success = self._greet_recommendation(index, greeting=greeting_message)
                if greet_success:
                    metadata["greeted"] = True
                

        self.assistant.upsert_candidate(
            candidate_id = candidate_id,
            scores=analysis,
            resume_text=resume_text,
            metadata=metadata,
            last_message=greeting_message,
            job_applied=self.job_snapshot.get("position"),
            updated_at=datetime.now().isoformat(),
        )
        logger.info("[recommend] #%s overall=%.1f -> %s", index, overall, decision)


    def _greet_recommendation(
        self,
        index: int,
        greeting
    ) -> Optional[str]:
        """Greet recommendation candidate using API calls."""
        response = requests.post(f"{self.base_url}/recommend/candidate/{index}/greet", json={"message": greeting})
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):  # The action function still returns a dict
                logger.info("对推荐候选人发送打招呼成功: #%s", index)
                return True  # Return a chat ID for tracking
        logger.warning("打招呼失败 #%s: HTTP %d", index, response.status_code)
        return False


    def _fetch_chat_history(self, chat_id: str) -> str:
        """Fetch chat history using API calls."""
        response = requests.get(f"{self.base_url}/chat/{chat_id}/messages")
        if response.status_code == 200:
            history = response.json()  # Now returns list directly
            # Convert structured history to text
            messages = []
            for msg in history:
                timestamp = msg.get('timestamp', '')
                msg_type = msg.get('type', '')
                message = msg.get('message', '')
                if message:
                    messages.append(f"[{timestamp}] {msg_type}: {message}")
            return "\n".join(messages)
        return ""

    def _has_positive_reply(self, history: str) -> bool:
        if not history:
            return False
        keywords = ["好的", "可以", "有兴趣", "感兴趣", "聊聊", "简历"]
        return any(keyword in history for keyword in keywords)

    def _check_full_resume(self, chat_id: str) -> bool:
        """Check if full resume is available using browser automation."""
        from .chat_actions import check_full_resume_available
        result = check_full_resume_available(self.page, chat_id)
        return result.get("success", False) if result else False

    def _view_full_resume(self, chat_id: str) -> str:
        """View full resume using browser automation."""
        from .chat_actions import view_full_resume_action
        result = view_full_resume_action(self.page, chat_id)
        if result.get("success"):
            return result.get("content", "")
        return ""

    def _notify_hr(
        self,
        *,
        candidate_id: str,
        chat_id: str,
        label: str,
        analysis: Dict[str, Any],
        resume_text: str,
    ) -> bool:
        if not self.dingtalk_webhook:
            return False
        overall = overall = analysis.get("overall")
        summary = analysis.get("summary", "")
        message = (
            f"候选人提醒\n"
            f"来源: 推荐\n"
            f"标识: {label or candidate_id}\n"
            f"沟通ID: {chat_id}\n"
            f"综合评分: {overall:.1f}/10\n"
            f"分析: {summary}"
        )
        payload = {
            "msgtype": "text",
            "text": {"content": message[:1800]},
        }
        response = requests.post(self.dingtalk_webhook, json=payload, timeout=15)
        if response.ok:
            logger.info("已通知HR，候选人:%s", candidate_id)
            return True
        logger.warning("通知HR失败(%s): %s", response.status_code, response.text)
        return False

    def _build_candidate_id(self, source: str, index: int, label: str) -> str:
        job_id = self.job_snapshot.get("id", "default")
        base = f"{job_id}:{source}:{index}:{label}"
        return uuid5(NAMESPACE_URL, base).hex

    def _analyze_candidate_resume(
        self,
        resume_text: str,
        candidate_summary: str,
    ) -> Dict[str, Any]:

        analysis = self.assistant.analyze_candidate(
            job_info=self.job_snapshot,
            candidate_resume=resume_text,
            candidate_summary=candidate_summary,
            chat_history={},
        )
        return analysis



__all__ = ["BRDWorkScheduler"]
