"""Scheduler for BRD-defined automation workflows."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import NAMESPACE_URL, uuid5

import requests

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
        base_url: str = None,
    ) -> None:
        self.recommend_limit = recommend_limit
        self.assistant = assistant
        self.overall_threshold = overall_threshold or 9.0
        self.dingtalk_webhook = settings.DINGTALK_URL
        self.base_url = base_url or settings.BOSS_SERVICE_BASE_URL

        self.enable_chat_processing = bool(enable_chat_processing)
        self.enable_recommend = bool(enable_recommend)
        self.enable_followup = bool(enable_followup)
        self.job_snapshot = job or {}

        self._running = False
        self._stop_event = threading.Event()

        if not self.job_snapshot:
            raise ValueError("Job information must be provided as parameter")

        self.threshold_greet = threshold_greet or 0.7
        self.threshold_borderline = threshold_borderline or 0.6
        self.report_interval = 604800
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

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        logger.info("启动BRD自动化调度：%s", self.job_snapshot.get("position"))
        self._main_thread = threading.Thread(target=self._main_loop, name="brd-main", daemon=True)
        self._main_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._running = False
        if hasattr(self, "_main_thread") and self._main_thread:
            self._main_thread.join(timeout=5)
        logger.info("BRD自动化调度已停止")

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "status_message": self._status_message,
            "timestamp": datetime.now().isoformat(),
        }

    def _main_loop(self) -> None:
        logger.info("BRD主循环启动")
        while not self._stop_event.is_set():
            if self.enable_chat_processing:
                self._status_message = "正在处理新聊天..."
                self._process_inbound_chats()

            if self.enable_recommend:
                self._process_recommendations()

            self._status_message = "等待下次检查..."
            self._stop_event.wait(10)
        logger.info("BRD主循环结束")

    # ------------------------------------------------------------------
    # Inbound processing via HTTP API
    # ------------------------------------------------------------------
    def _process_inbound_chats(self) -> None:
        try:
            response = requests.get(
                f"{self.base_url}/chat/dialogs",
                params={"limit": self.recommend_limit or 20},
                timeout=15,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("获取聊天列表失败: %s", exc)
            return

        messages = response.json() or []
        for entry in messages:
            chat_id = str(entry.get("id") or entry.get("chat_id") or "").strip()
            if not chat_id:
                continue
            snippet = (entry.get("text") or "").strip()
            self._evaluate_chat(chat_id, snippet, source="inbound")

    def _evaluate_chat(self, chat_id: str, snippet: str, source: str) -> Dict[str, Any]:
        resume_text = ""
        resume_meta: Dict[str, Any] = {}
        try:
            result = requests.post(
                f"{self.base_url}/resume/online",
                json={"chat_id": chat_id},
                timeout=30,
            )
            if result.ok:
                payload = result.json()
                if payload.get("success"):
                    resume_text = payload.get("text") or payload.get("content") or ""
                    resume_meta = payload
        except Exception as exc:
            logger.warning("获取在线简历失败: %s", exc)

        if not resume_text:
            decision = "pending_resume"
            score = 0.0
            details = "无法获取在线简历"
        else:
            analysis = self._analyze_candidate_resume(resume_text, snippet)
            score = analysis.get("overall", 0.0) / 10.0
            details = analysis.get("summary", "AI分析完成")
            if score >= self.threshold_greet:
                decision = self._request_resume(chat_id)
            elif score >= self.threshold_borderline:
                decision = "manual_review"
            else:
                decision = self._discard_candidate(chat_id)

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
        logger.info("[%s] %s 分数 %.1f -> %s", source, chat_id, score * 100, decision)
        return record

    def _request_resume(self, chat_id: str) -> str:
        try:
            resp = requests.post(f"{self.base_url}/resume/request", json={"chat_id": chat_id}, timeout=15)
            if resp.ok and resp.json().get("success"):
                return "resume_requested"
        except Exception as exc:
            logger.warning("请求简历失败: %s", exc)
        return "request_failed"

    def _discard_candidate(self, chat_id: str) -> str:
        try:
            resp = requests.post(f"{self.base_url}/candidate/discard", json={"chat_id": chat_id}, timeout=15)
            if resp.ok and resp.json().get("success"):
                return "discarded"
        except Exception as exc:
            logger.warning("丢弃候选人失败: %s", exc)
        return "discard_failed"

    # ------------------------------------------------------------------
    # Recommendation processing via HTTP API
    # ------------------------------------------------------------------
    def _process_recommendations(self) -> None:
        self._status_message = "正在处理推荐候选人..."
        try:
            response = requests.get(
                f"{self.base_url}/recommend/candidates",
                params={"limit": self.recommend_limit or 20},
                timeout=30,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("获取推荐候选人失败: %s", exc)
            self._status_message = f"获取推荐候选人失败: {exc}"
            return

        candidates = response.json() or []
        self._status_message = f"找到 {len(candidates)} 个推荐候选人，开始处理..."
        for index, entry in enumerate(candidates):
            summary = (entry.get("text") or "").strip() or f"candidate-{index}"
            candidate_id = self._build_candidate_id("recommend", index, summary)

            resume_result = requests.get(
                f"{self.base_url}/recommend/candidate/{index}/resume",
                timeout=30,
            )
            if not resume_result.ok:
                logger.warning("获取推荐候选人简历失败: HTTP %d", resume_result.status_code)
                continue
            resume_payload = resume_result.json()
            resume_text = resume_payload.get("text") or resume_payload.get("content") or ""
            if not resume_text:
                continue

            analysis = self._analyze_candidate_resume(resume_text, summary)
            overall = analysis.get("overall", 0.0)
            decision = overall >= self.overall_threshold

            greeting_message = ""
            greeted = False
            if resume_text and decision:
                # TODO: migrate greeting generation to Streamlit client
                pass

            metadata = {
                "source": "recommendation",
                "index": index,
                "summary": summary,
                "analysis": analysis,
                "greeted": greeted,
            }

            self.assistant.upsert_candidate(
                candidate_id=candidate_id,
                scores=analysis,
                resume_text=resume_text,
                metadata=metadata,
                last_message=greeting_message,
                job_applied=self.job_snapshot.get("position"),
            )
            logger.info("[recommend] #%s overall=%.1f -> %s", index, overall, decision)

    def _greet_recommendation(self, index: int, greeting: str) -> bool:
        try:
            response = requests.post(
                f"{self.base_url}/recommend/candidate/{index}/greet",
                json={"message": greeting},
                timeout=15,
            )
            if response.ok:
                payload = response.json()
                return bool(payload.get("success"))
        except Exception as exc:
            logger.warning("打招呼失败 #%s: %s", index, exc)
        return False

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------
    def _build_candidate_id(self, source: str, index: int, label: str) -> str:
        job_id = self.job_snapshot.get("id", "default")
        base = f"{job_id}:{source}:{index}:{label}"
        return uuid5(NAMESPACE_URL, base).hex

    def _analyze_candidate_resume(
        self,
        resume_text: str,
        candidate_summary: str,
    ) -> Dict[str, Any]:
        return self.assistant.analyze_candidate(
            job_info=self.job_snapshot,
            candidate_resume=resume_text,
            candidate_summary=candidate_summary,
            chat_history={},
        )


__all__ = ["BRDWorkScheduler"]
