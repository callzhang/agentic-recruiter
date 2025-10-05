"""Scheduler for BRD-defined automation workflows."""

from __future__ import annotations

import copy
import csv
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import NAMESPACE_URL, uuid5
from src.config import settings
import requests
from requests import Response
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
        enable_inbound: Optional[bool] = None,
        enable_followup: Optional[bool] = None,
        assistant: Optional["AssistantActions"] = None,
        overall_threshold: Optional[float] = None,
        threshold_greet: Optional[float] = None,
        threshold_borderline: Optional[float] = None,
        **_: Any,
    ) -> None:
        
        self.recommend_limit = recommend_limit
        # self.session = requests.Session()
        self.assistant = assistant
        self.overall_threshold = overall_threshold or 8.0
        self.dingtalk_webhook = settings.DINGTALK_URL

        self.enable_inbound = bool(enable_inbound)
        self.enable_recommend = bool(enable_recommend)
        self.enable_followup = bool(enable_followup)
        self.job_snapshot = job

        self._running = False
        self._stop_event = threading.Event()
        self._processed_chats: Dict[str, Dict[str, Any]] = {}
        self._recommended_history: Dict[str, Dict[str, Any]] = {}
        self._pending_followups: Dict[str, Dict[str, Any]] = {}
        self._candidate_records: List[Dict[str, Any]] = []
        self._last_report_at = datetime.now()
        
        

        # Use job parameter directly - no need to load from YAML
        if not self.job_snapshot:
            raise ValueError("Job information must be provided as parameter")
        
        # Set thresholds from parameters
        self.threshold_greet = threshold_greet or 0.7
        self.threshold_borderline = threshold_borderline or 0.6
        
        # Set report interval (weekly)
        self.report_interval = 604800  # 7 days in seconds

        logger.debug(
            "BRD scheduler initialised: position=%s, greet>=%.2f, overall>=%.1f, inbound=%s, recommend=%s, followup=%s",
            self.job_snapshot.get("position", "AI岗位"),
            self.threshold_greet,
            self.overall_threshold,
            self.enable_inbound,
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

    def add_manual_record(self, record: Dict[str, Any]) -> None:
        self._candidate_records.append(record)

    def _main_loop(self) -> None:
        """Main sequential loop that runs all tasks in sequence."""
        logger.info("BRD主循环启动")
        
        while not self._stop_event.is_set():
            try:
                # Run inbound processing
                if self.enable_inbound:
                    self._process_inbound_chats()
                
                # Run recommendation processing
                if self.enable_recommend:
                    self._process_recommendations()
                
                # Run followup processing
                if self.enable_followup:
                    self._process_followup_cycle()
                
                # Run reporting
                self._flush_weekly_report()
                
                # Wait before next iteration
                self._wait(120)  # 2 minutes between cycles
                
            except Exception as exc:
                logger.exception("BRD主循环异常: %s", exc)
                self._wait(60)  # Wait 1 minute on error before retrying
        
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
        response = self.session.get(
            f"{self.base_url}/chat/dialogs",
            params={"limit": self.inbound_limit},
            timeout=30,
        )
        data = self._safe_json(response)
        if not data:
            return
        messages = data.get("messages") or []
        for entry in messages:
            chat_id = str(entry.get("id") or entry.get("chat_id") or "").strip()
            if not chat_id or chat_id in self._processed_chats:
                continue
            snippet = (entry.get("text") or "").strip()
            record = self._evaluate_chat(chat_id, snippet, source="inbound")
            self._processed_chats[chat_id] = record

    def _evaluate_chat(self, chat_id: str, snippet: str, source: str) -> Dict[str, Any]:
        resume_text, resume_meta = self._fetch_resume(chat_id)
        if not resume_text:
            decision = "pending_resume"
            score = 0.0
            details = "无法获取在线简历"
        else:
            score_info = self._score_resume(resume_text)
            score = score_info["score"]
            details = score_info["explanation"]
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
        self._candidate_records.append(record)
        logger.info(
            "[%s] %s 分数 %.1f -> %s", source, chat_id, score * 100, decision
        )
        return record

    def _fetch_resume(self, chat_id: str) -> tuple[str, Dict[str, Any]]:
        try:
            response = self.session.post(
                f"{self.base_url}/resume/online",
                json={"chat_id": chat_id},
                timeout=60,
            )
        except requests.RequestException as exc:  # pragma: no cover - defensive
            logger.warning("获取在线简历异常(%s): %s", chat_id, exc)
            return "", {"error": str(exc)}

        data = self._safe_json(response)
        if not data or not data.get("success"):
            return "", data or {}
        text = self._extract_resume_text(data.get("text"))
        return text, data

    def _request_resume(self, chat_id: str) -> bool:
        response = self.session.post(
            f"{self.base_url}/resume/request",
            json={"chat_id": chat_id},
            timeout=20,
        )
        data = self._safe_json(response)
        ok = bool(data and data.get("success"))
        if not ok:
            logger.warning("求简历失败: %s -> %s", chat_id, data)
        return ok

    def _discard_candidate(self, chat_id: str) -> bool:
        response = self.session.post(
            f"{self.base_url}/candidate/discard",
            json={"chat_id": chat_id},
            timeout=20,
        )
        data = self._safe_json(response)
        ok = bool(data and data.get("success"))
        if not ok:
            logger.warning("标记不合适失败: %s -> %s", chat_id, data)
        return ok

    # ------------------------------------------------------------------
    # Recommendation processing
    # ------------------------------------------------------------------
    def _process_recommendations(self) -> None:
        response = self.session.get(
            f"{self.base_url}/recommend/candidates",
            params={"limit": self.recommend_limit},
            timeout=30,
        )
        data = self._safe_json(response)
        if not data:
            return
        candidates = data.get("candidates") or []
        for index, entry in enumerate(candidates):
            label = (entry.get("text") or "").strip() or f"candidate-{index}"
            candidate_id = self._build_candidate_id("recommend", index, label)
            key = candidate_id
            if key in self._recommended_history:
                continue

            resume_payload = self._fetch_recommend_resume(index)
            resume_text = resume_payload.get("text", "")
            analysis = self._analyze_candidate_resume(resume_text, label)
            overall = self._extract_overall_score(analysis)
            decision = "no_resume" if not resume_text else "discarded"
            chat_id: Optional[str] = None

            metadata = {
                "source": "recommendation",
                "index": index,
                "label": label,
                "resume_meta": resume_payload.get("raw"),
            }

            if resume_text and overall >= self.overall_threshold:
                greeting_message = self._generate_greeting(label, resume_text, resume_payload.get("raw"))
                chat_id = self._greet_recommendation(index, label, greeting=greeting_message)
                if chat_id:
                    decision = "greeted"
                    if self.enable_followup:
                        followup_at = datetime.utcnow() + timedelta(seconds=3600)  # 1 hour
                        self._pending_followups[chat_id] = {
                            "candidate_id": candidate_id,
                            "index": index,
                            "label": label,
                            "next": followup_at,
                            "status": "awaiting_reply",
                            "score": overall,
                            "analysis": analysis,
                            "resume": resume_text,
                            "metadata": metadata,
                        }
                    self._log_candidate_action(
                        candidate_id,
                        chat_id,
                        action_type="greet",
                        score=overall,
                        summary=analysis.get("summary", ""),
                        extra=metadata,
                        embedding_source=resume_text,
                    )
                else:
                    decision = "greet_failed"
                    self._log_candidate_action(
                        candidate_id,
                        chat_id,
                        action_type="greet_failed",
                        score=overall,
                        summary="自动打招呼失败",
                        extra=metadata,
                        embedding_source=resume_text,
                    )
            elif resume_text:
                decision = "discarded"
                self._log_candidate_action(
                    candidate_id,
                    chat_id,
                    action_type="discard",
                    score=overall,
                    summary=analysis.get("summary", "不满足阈值"),
                    extra=metadata,
                    embedding_source=resume_text,
                )
            else:
                self._log_candidate_action(
                    candidate_id,
                    chat_id,
                    action_type="missing_resume",
                    score=None,
                    summary="未抓取到在线简历",
                    extra=metadata,
                )

            self._record_candidate_profile(
                candidate_id,
                chat_id,
                decision,
                overall,
                analysis,
                resume_text,
                metadata,
            )

            record = {
                "chat_id": chat_id,
                "candidate_id": candidate_id,
                "source": "recommendation",
                "index": index,
                "snippet": label,
                "score": overall,
                "decision": decision,
                "analysis": analysis,
                "timestamp": datetime.utcnow().isoformat(),
            }
            self._candidate_records.append(record)
            self._recommended_history[key] = record
            logger.info("[recommend] #%s overall=%.1f -> %s", index, overall, decision)

    def _fetch_recommend_resume(self, index: int) -> Dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/recommend/candidate/{index}/resume",
            timeout=45,
        )
        data = self._safe_json(response)
        if not data or not data.get("success"):
            return {"text": "", "raw": data or {}, "success": False}
        return {
            "text": self._extract_resume_text(data.get("text")),
            "raw": data,
            "success": True,
        }

    def _greet_recommendation(
        self,
        index: int,
        label: str,
        *,
        greeting: Optional[str] = None,
    ) -> Optional[str]:
        payload = {
            "message": (greeting or self.greeting_template.format(position=self.role_position)),
        }
        response = self.session.post(
            f"{self.base_url}/recommend/candidate/{index}/greet",
            json=payload,
            timeout=30,
        )
        data = self._safe_json(response)
        if data and data.get("success"):
            chat_id = data.get("chat_id")
            if chat_id:
                logger.info("对推荐候选人发送打招呼成功: %s", chat_id)
            return chat_id
        logger.warning("打招呼失败 #%s: %s", index, data)
        return None

    # ------------------------------------------------------------------
    # Follow-up processing
    # ------------------------------------------------------------------
    def _process_followup_cycle(self) -> None:
        now = datetime.utcnow()
        for chat_id, state in list(self._pending_followups.items()):
            if now < state.get("next", now):
                continue

            status = state.get("status", "awaiting_reply")
            history = self._fetch_chat_history(chat_id)
            metadata = dict(state.get("metadata", {}))

            if status == "awaiting_reply":
                if self._has_positive_reply(history) and self._request_resume(chat_id):
                    metadata["stage"] = "resume_requested"
                    state.update({
                        "status": "resume_requested",
                        "next": now + timedelta(seconds=3600),  # 1 hour
                        "last_history": history,
                        "metadata": metadata,
                    })
                    self._log_candidate_action(
                        state.get("candidate_id", chat_id),
                        chat_id,
                        action_type="resume_requested",
                        score=state.get("score"),
                        summary="候选人回复积极，已自动求简历",
                        extra=metadata,
                    )
                    self._record_candidate_profile(
                        state.get("candidate_id", chat_id),
                        chat_id,
                        "resume_requested",
                        state.get("score", 0.0),
                        state.get("analysis"),
                        state.get("resume", ""),
                        metadata,
                    )
                    continue
                # No positive reply yet -> postpone
                state["next"] = now + timedelta(seconds=3600)  # 1 hour
                logger.info("候选人暂无回复，保留跟进计划: %s", chat_id)
                continue

            if status == "resume_requested":
                if self._check_full_resume(chat_id):
                    full_resume = self._view_full_resume(chat_id)
                    if full_resume:
                        analysis = self._analyze_candidate_resume(
                            full_resume,
                            state.get("label", ""),
                        )
                        overall = self._extract_overall_score(analysis)
                        metadata["stage"] = "resume_received"
                        self._log_candidate_action(
                            state.get("candidate_id", chat_id),
                            chat_id,
                            action_type="resume_received",
                            score=overall,
                            summary=analysis.get("summary", ""),
                            extra=metadata,
                            embedding_source=full_resume,
                        )
                        self._record_candidate_profile(
                            state.get("candidate_id", chat_id),
                            chat_id,
                            "resume_received",
                            overall,
                            analysis,
                            full_resume,
                            metadata,
                        )
                        notified = False
                        if overall >= self.overall_threshold:
                            notified = self._notify_hr(
                                candidate_id=state.get("candidate_id", chat_id),
                                chat_id=chat_id,
                                label=state.get("label", ""),
                                analysis=analysis,
                                resume_text=full_resume,
                            )
                        if notified:
                            metadata["stage"] = "notify_hr"
                            self._log_candidate_action(
                                state.get("candidate_id", chat_id),
                                chat_id,
                                action_type="notify_hr",
                                score=overall,
                                summary="已通知HR获取完整简历",
                                extra=metadata,
                                embedding_source=full_resume,
                            )
                        self._pending_followups.pop(chat_id, None)
                        continue
                # No resume yet, reschedule check
                state["next"] = now + timedelta(seconds=3600)  # 1 hour
                continue

            # Unknown status, clean up to avoid stale records
            self._pending_followups.pop(chat_id, None)

    def _fetch_chat_history(self, chat_id: str) -> str:
        response = self.session.get(
            f"{self.base_url}/chat/{chat_id}/messages",
            timeout=30,
        )
        data = self._safe_json(response)
        if not data:
            return ""
        messages = data.get("messages")
        if isinstance(messages, list):
            return "\n".join(str(item) for item in messages)
        if isinstance(messages, str):
            return messages
        return ""

    def _has_positive_reply(self, history: str) -> bool:
        if not history:
            return False
        keywords = ["好的", "可以", "有兴趣", "感兴趣", "聊聊", "简历"]
        return any(keyword in history for keyword in keywords)

    def _check_full_resume(self, chat_id: str) -> bool:
        response = self.session.post(
            f"{self.base_url}/resume/check_full",
            json={"chat_id": chat_id},
            timeout=20,
        )
        data = self._safe_json(response)
        return bool(data and (data.get("available") or data.get("success")))

    def _view_full_resume(self, chat_id: str) -> str:
        response = self.session.post(
            f"{self.base_url}/resume/view_full",
            json={"chat_id": chat_id},
            timeout=60,
        )
        data = self._safe_json(response)
        if not data or not data.get("success"):
            return ""
        content = data.get("content") or data.get("text") or ""
        if isinstance(content, list):  # pages list
            return "\n".join(str(item) for item in content)
        if isinstance(content, dict):
            return self._extract_resume_text(content)
        return str(content)

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
        overall = self._extract_overall_score(analysis)
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
        try:
            response = requests.post(self.dingtalk_webhook, json=payload, timeout=15)
            if response.ok:
                logger.info("已通知HR，候选人:%s", candidate_id)
                return True
            logger.warning("通知HR失败(%s): %s", response.status_code, response.text)
        except Exception as exc:  # pragma: no cover - network operations
            logger.warning("通知HR异常: %s", exc)
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
        if not resume_text:
            return {}
        if self.assistant and getattr(self.assistant, "client", None):
            try:
                analysis = self.assistant.analyze_candidate(
                    job_info=self.job_snapshot,
                    candidate_resume=resume_text,
                    candidate_summary=candidate_summary,
                    chat_history={},
                )
                if analysis:
                    return analysis
            except Exception as exc:
                logger.warning("AI分析失败，回退规则评分: %s", exc)
        fallback = self._score_resume(resume_text)
        overall = round(float(fallback.get("score", 0.0)) * 10, 2)
        return {
            "overall": overall,
            "skill": None,
            "startup_fit": None,
            "willingness": None,
            "summary": fallback.get("explanation", ""),
        }

    def _extract_overall_score(self, analysis: Optional[Dict[str, Any]]) -> float:
        if not analysis:
            return 0.0
        overall = analysis.get("overall")
        try:
            return float(overall)
        except (TypeError, ValueError):
            return 0.0

    def _generate_greeting(
        self,
        label: str,
        resume_text: str,
        raw_resume: Optional[Dict[str, Any]] = None,
    ) -> str:
        if self.assistant and getattr(self.assistant, "client", None):
            try:
                message = self.assistant.generate_greeting_message(
                    candidate_summary=label,
                    candidate_resume=resume_text,
                    job_info=self.job_snapshot,
                )
                if message:
                    return message
            except Exception as exc:
                logger.warning("AI打招呼生成失败，使用模板: %s", exc)
        return self.greeting_template.format(position=self.job_snapshot.get("position", "AI岗位"))

    def _record_candidate_profile(
        self,
        candidate_id: str,
        chat_id: Optional[str],
        status: str,
        overall: float,
        analysis: Optional[Dict[str, Any]],
        resume_text: str,
        metadata: Optional[Dict[str, Any]],
    ) -> None:
        if not self.assistant:
            return
        extra = dict(metadata or {})
        extra.update({"status": status, "chat_id": chat_id})
        self.assistant.upsert_candidate(
            candidate_id=candidate_id,
            job_applied=self.job_snapshot.get("position", "AI岗位"),
            resume_text=resume_text,
            scores=analysis,
            metadata_extra=extra,
        )

    def _log_candidate_action(
        self,
        candidate_id: str,
        chat_id: Optional[str],
        *,
        action_type: str,
        score: Optional[float],
        summary: str,
        extra: Optional[Dict[str, Any]] = None,
        embedding_source: Optional[str] = None,
    ) -> None:
        if not self.assistant:
            return
        self.assistant.record_candidate_action(
            candidate_id=candidate_id,
            chat_id=chat_id,
            action_type=action_type,
            score=score,
            summary=summary,
            metadata=extra,
            embedding_source=embedding_source,
        )


    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def _flush_weekly_report(self) -> None:
        if (datetime.utcnow() - self._last_report_at).total_seconds() < self.report_interval:
            return
        path = Path("data") / "brd_weekly_stats.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = list(self._candidate_records)
        if not rows:
            logger.debug("暂无数据生成周报")
            return
        fieldnames = [
            "timestamp",
            "source",
            "chat_id",
            "index",
            "snippet",
            "score",
            "decision",
            "details",
        ]
        with path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})
        self._last_report_at = datetime.utcnow()
        logger.info("周报已更新: %s", path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_resume_text(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            parts = [str(value) for value in payload.values() if isinstance(value, str)]
            return "\n".join(parts)
        if isinstance(payload, list):
            parts = [str(item) for item in payload if isinstance(item, str)]
            return "\n".join(parts)
        return ""

    def _score_resume(self, text: str) -> Dict[str, Any]:
        text_lower = text.lower()
        filters = self.job_snapshot.get("filters", {})
        must_have = [str(item).lower() for item in filters.get("must_have", [])]
        nice_to_have = [str(item).lower() for item in filters.get("nice_to_have", [])]
        must_not = [str(item).lower() for item in filters.get("must_not", [])]

        penalty = any(keyword in text_lower for keyword in must_not)
        skills_base = 0.0
        if must_have:
            hits = sum(1 for keyword in must_have if keyword in text_lower)
            skills_base = hits / len(must_have)
        bonus = 0.0
        if nice_to_have:
            bonus_hits = sum(1 for keyword in nice_to_have if keyword in text_lower)
            bonus = min(0.3, bonus_hits * 0.05)
        skills_score = min(1.0, skills_base + bonus)

        experience_score = self._score_experience(text_lower)
        project_score = self._score_projects(text_lower)
        education_score = self._score_education(text_lower)

        weighted_score = 0.0
        weighted_score += skills_score * 0.35
        weighted_score += experience_score * 0.35
        weighted_score += project_score * 0.2
        weighted_score += education_score * 0.1
        if penalty:
            weighted_score *= 0.5

        explanation = (
            f"skills={skills_score:.2f}, exp={experience_score:.2f}, proj={project_score:.2f}, "
            f"edu={education_score:.2f}, penalty={'Y' if penalty else 'N'}"
        )
        return {"score": weighted_score, "explanation": explanation}

    def _score_experience(self, text_lower: str) -> float:
        import re

        years = 0
        matches = re.findall(r"(\d+)(?:\s*年)", text_lower)
        if matches:
            years = max(int(num) for num in matches)
        if years == 0:
            return 0.2
        if years < 3:
            return 0.5
        if 3 <= years <= 8:
            return 1.0
        if years <= 12:
            return 0.8
        return 0.6

    def _score_projects(self, text_lower: str) -> float:
        keywords = [
            "项目", "算法", "模型", "优化", "部署", "推理", "训练", "llm", "rag", "lora"
        ]
        hits = sum(1 for keyword in keywords if keyword in text_lower)
        if hits >= 6:
            return 1.0
        if hits >= 4:
            return 0.8
        if hits >= 2:
            return 0.6
        if hits >= 1:
            return 0.4
        return 0.2

    def _score_education(self, text_lower: str) -> float:
        if "博士" in text_lower or "phd" in text_lower:
            return 1.0
        if "硕士" in text_lower or "master" in text_lower:
            return 0.9
        if "本科" in text_lower or "bachelor" in text_lower:
            return 0.7
        if "大专" in text_lower or "college" in text_lower:
            return 0.5
        return 0.3

    def _safe_json(self, response: Response | None) -> Dict[str, Any]:
        if not response:
            return {}
        try:
            response.raise_for_status()
            return response.json()
        except Exception:  # pragma: no cover - defensive
            logger.debug("解析响应失败: %s", getattr(response, "text", ""))
            return {}


__all__ = ["BRDWorkScheduler"]
