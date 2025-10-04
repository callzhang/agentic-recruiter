"""Scheduler for BRD-defined automation workflows."""

from __future__ import annotations

import csv
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml
from requests import Response

DEFAULT_GREETING_TEMPLATE = (
    "您好，我们是一家AI科技公司，是奔驰全球创新代表中唯一的中国公司，"
    "代表中国参加中德Autobahn汽车大会，是华为云自动驾驶战略合作伙伴中唯一创业公司，"
    "也是经过华为严选的唯一产品级AI数据合作伙伴。您对我们{position}岗位有没有兴趣？"
)


class BRDWorkScheduler:
    """Coordinates inbound/outbound recruitment workflows defined in the BRD."""

    def __init__(
        self,
        *,
        base_url: str,
        criteria_path: str | Path,
        role_id: str = "default",
        poll_interval: int = 120,
        recommend_interval: int = 600,
        followup_interval: int = 3600,
        report_interval: int = 86400 * 7,
        inbound_limit: int = 40,
        recommend_limit: int = 20,
        greeting_template: str | None = None,
        session: Optional[requests.Session] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.criteria_path = Path(criteria_path)
        self.role_id = role_id
        self.poll_interval = max(30, poll_interval)
        self.recommend_interval = max(120, recommend_interval)
        self.followup_interval = max(600, followup_interval)
        self.report_interval = max(3600, report_interval)
        self.inbound_limit = max(5, inbound_limit)
        self.recommend_limit = max(5, recommend_limit)
        self.session = session or requests.Session()
        self.logger = logger or logging.getLogger("brd_scheduler")
        self.greeting_template = greeting_template or DEFAULT_GREETING_TEMPLATE

        self._threads: List[threading.Thread] = []
        self._stop_event = threading.Event()
        self._processed_chats: Dict[str, Dict[str, Any]] = {}
        self._recommended_history: Dict[str, Dict[str, Any]] = {}
        self._pending_followups: Dict[str, Dict[str, Any]] = {}
        self._candidate_records: List[Dict[str, Any]] = []
        self._last_report_at = datetime.utcnow()

        self.criteria = self._load_role_criteria()
        scoring = self.criteria.get("scoring", {})
        self.threshold_greet = float(scoring.get("threshold", {}).get("greet", 0.7))
        self.threshold_borderline = float(scoring.get("threshold", {}).get("borderline", 0.6))
        self.weights = scoring.get("weights", {})
        self.role_position = self.criteria.get("position", "AI岗位")

        self.logger.debug(
            "BRD scheduler initialised: role=%s, greet>=%.2f", self.role_id, self.threshold_greet
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._threads:
            return
        self.logger.info("启动BRD自动化调度：%s", self.role_position)
        loops = [
            (self._inbound_loop, "brd-inbound"),
            (self._recommendation_loop, "brd-recommend"),
            (self._followup_loop, "brd-followup"),
            (self._reporting_loop, "brd-report"),
        ]
        for target, name in loops:
            thread = threading.Thread(target=target, name=name, daemon=True)
            self._threads.append(thread)
            thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()
        self.logger.info("BRD自动化调度已停止")

    def add_manual_record(self, record: Dict[str, Any]) -> None:
        self._candidate_records.append(record)

    # ------------------------------------------------------------------
    # Loops
    # ------------------------------------------------------------------
    def _inbound_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._process_inbound_chats()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.exception("处理牛人主动沟通失败: %s", exc)
            self._wait(self.poll_interval)

    def _recommendation_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._process_recommendations()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.exception("处理推荐牛人失败: %s", exc)
            self._wait(self.recommend_interval)

    def _followup_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._process_followups()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.exception("执行跟进策略失败: %s", exc)
            self._wait(self.followup_interval)

    def _reporting_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._flush_weekly_report()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.exception("生成周报失败: %s", exc)
            self._wait(3600)  # check hourly

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
        self.logger.info(
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
            self.logger.warning("获取在线简历异常(%s): %s", chat_id, exc)
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
            self.logger.warning("求简历失败: %s -> %s", chat_id, data)
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
            self.logger.warning("标记不合适失败: %s -> %s", chat_id, data)
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
            label = entry.get("text") or f"candidate-{index}"
            key = f"{index}:{hash(label)}"
            if key in self._recommended_history:
                continue
            resume = self._fetch_recommend_resume(index)
            score_info = self._score_resume(resume) if resume else {"score": 0.0, "explanation": ""}
            score = score_info["score"]
            decision = "skip"
            chat_id: Optional[str] = None

            if resume and score >= self.threshold_greet:
                chat_id = self._greet_recommendation(index, label)
                if chat_id:
                    decision = "greeted"
                    followup_at = datetime.utcnow() + timedelta(seconds=self.followup_interval)
                    self._pending_followups[chat_id] = {
                        "index": index,
                        "label": label,
                        "next": followup_at,
                        "score": score,
                    }
                else:
                    decision = "greet_failed"
            elif resume and score >= self.threshold_borderline:
                decision = "manual_review"
            elif resume:
                decision = "skipped_low_score"

            record = {
                "chat_id": chat_id,
                "source": "recommendation",
                "index": index,
                "snippet": label,
                "score": score,
                "decision": decision,
                "details": score_info.get("explanation", ""),
                "timestamp": datetime.utcnow().isoformat(),
            }
            self._candidate_records.append(record)
            self._recommended_history[key] = record
            self.logger.info("[recommend] #%s %.1f -> %s", index, score * 100, decision)

    def _fetch_recommend_resume(self, index: int) -> str:
        response = self.session.get(
            f"{self.base_url}/recommend/candidate/{index}/resume",
            timeout=45,
        )
        data = self._safe_json(response)
        if not data or not data.get("success"):
            return ""
        return self._extract_resume_text(data.get("text"))

    def _greet_recommendation(self, index: int, label: str) -> Optional[str]:
        payload = {
            "message": self.greeting_template.format(position=self.role_position),
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
                self.logger.info("对推荐候选人发送打招呼成功: %s", chat_id)
            return chat_id
        self.logger.warning("打招呼失败 #%s: %s", index, data)
        return None

    # ------------------------------------------------------------------
    # Follow-up processing
    # ------------------------------------------------------------------
    def _process_followups(self) -> None:
        now = datetime.utcnow()
        for chat_id, payload in list(self._pending_followups.items()):
            if now < payload.get("next", now):
                continue
            history = self._fetch_chat_history(chat_id)
            if self._has_positive_reply(history):
                if self._request_resume(chat_id):
                    self._pending_followups.pop(chat_id, None)
                    self.logger.info("回复积极，已自动求简历: %s", chat_id)
                continue
            # No reply yet -> schedule reminder
            payload["next"] = now + timedelta(seconds=self.followup_interval)
            self.logger.info("候选人暂无回复，保留跟进计划: %s", chat_id)

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
            self.logger.debug("暂无数据生成周报")
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
        self.logger.info("周报已更新: %s", path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _load_role_criteria(self) -> Dict[str, Any]:
        if not self.criteria_path.exists():
            raise FileNotFoundError(f"未找到岗位画像配置: {self.criteria_path}")
        data = yaml.safe_load(self.criteria_path.read_text(encoding="utf-8"))
        roles = data.get("roles") if isinstance(data, dict) else []
        for role in roles or []:
            if str(role.get("id")) == str(self.role_id):
                return role
        if roles:
            return roles[0]
        raise ValueError("画像配置缺少 roles")

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
        filters = self.criteria.get("filters", {})
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
        weighted_score += skills_score * float(self.weights.get("skills_match", 0.35))
        weighted_score += experience_score * float(self.weights.get("experience", 0.35))
        weighted_score += project_score * float(self.weights.get("projects", 0.2))
        weighted_score += education_score * float(self.weights.get("education", 0.1))
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
            self.logger.debug("解析响应失败: %s", getattr(response, "text", ""))
            return {}


__all__ = ["BRDWorkScheduler"]
