"""Local store for job-portrait optimization feedback.

This is intentionally file-backed (under `data/`) to support an iterative prompt/portrait
optimization workflow without touching the Milvus schema.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .global_logger import logger


_STORE_PATH = Path("data/job_optimization_feedback.json")
_LOCK = threading.Lock()


@dataclass(frozen=True)
class TargetScores:
    overall: Optional[int] = None
    skill: Optional[int] = None
    background: Optional[int] = None
    startup_fit: Optional[int] = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TargetScores":
        def _get_int(key: str) -> Optional[int]:
            v = payload.get(key)
            if v is None or v == "":
                return None
            try:
                return int(v)
            except Exception:
                return None

        return cls(
            overall=_get_int("overall"),
            skill=_get_int("skill"),
            background=_get_int("background"),
            startup_fit=_get_int("startup_fit"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "skill": self.skill,
            "background": self.background,
            "startup_fit": self.startup_fit,
        }


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _load_store_unlocked() -> dict[str, Any]:
    if not _STORE_PATH.exists():
        return {"version": 1, "items": []}
    try:
        payload = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read optimization store, re-initializing: %s", str(_STORE_PATH))
        return {"version": 1, "items": []}
    if not isinstance(payload, dict):
        return {"version": 1, "items": []}
    if "items" not in payload or not isinstance(payload.get("items"), list):
        payload["items"] = []
    payload.setdefault("version", 1)
    return payload


def _save_store_unlocked(payload: dict[str, Any]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def list_feedback(job_id: str) -> list[dict[str, Any]]:
    """List feedback items for a base_job_id (most recent first)."""
    job_id = (job_id or "").strip()
    if not job_id:
        return []
    with _LOCK:
        store = _load_store_unlocked()
        items = [it for it in store.get("items", []) if it.get("job_id") == job_id]
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return items


def count_feedback(job_id: str) -> int:
    return len(list_feedback(job_id))


def get_feedback(item_id: str) -> Optional[dict[str, Any]]:
    item_id = (item_id or "").strip()
    if not item_id:
        return None
    with _LOCK:
        store = _load_store_unlocked()
        for it in store.get("items", []):
            if it.get("id") == item_id:
                return it
    return None


def upsert_feedback(
    *,
    item_id: Optional[str],
    job_id: str,
    candidate_id: str,
    conversation_id: str,
    candidate_name: str,
    job_applied: str,
    current_analysis: dict[str, Any],
    suggestion: str,
    target_scores: TargetScores,
) -> dict[str, Any]:
    """Create or update a feedback item."""
    job_id = (job_id or "").strip()
    candidate_id = (candidate_id or "").strip()
    conversation_id = (conversation_id or "").strip()
    candidate_name = (candidate_name or "").strip()
    suggestion = (suggestion or "").strip()

    if not job_id:
        raise ValueError("job_id is required")
    if not candidate_id:
        raise ValueError("candidate_id is required")
    if not conversation_id:
        raise ValueError("conversation_id is required")
    if not suggestion:
        raise ValueError("suggestion is required")

    now = _utc_now()
    with _LOCK:
        store = _load_store_unlocked()
        items: list[dict[str, Any]] = store.get("items", [])

        existing: Optional[dict[str, Any]] = None
        if item_id:
            for it in items:
                if it.get("id") == item_id:
                    existing = it
                    break

        if existing is None:
            item_id = str(uuid.uuid4())
            existing = {
                "id": item_id,
                "created_at": now,
            }
            items.append(existing)

        existing.update(
            {
                "job_id": job_id,
                "job_applied": job_applied,
                "candidate_id": candidate_id,
                "conversation_id": conversation_id,
                "candidate_name": candidate_name,
                "current_analysis": current_analysis or {},
                "target_scores": target_scores.to_dict(),
                "suggestion": suggestion,
                "updated_at": now,
                "status": "open",
            }
        )
        store["items"] = items
        _save_store_unlocked(store)
        return existing


def delete_feedback(item_id: str) -> bool:
    item_id = (item_id or "").strip()
    if not item_id:
        return False
    with _LOCK:
        store = _load_store_unlocked()
        items = store.get("items", [])
        new_items = [it for it in items if it.get("id") != item_id]
        if len(new_items) == len(items):
            return False
        store["items"] = new_items
        _save_store_unlocked(store)
    return True

