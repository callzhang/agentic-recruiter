"""Zilliz/Milvus-backed store for job-portrait optimization feedback.

This store supports the "评分不准 -> 优化岗位肖像" workflow and is intended to
work in multi-instance environments (e.g. Vercel) where local file storage is not
reliable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from pymilvus import CollectionSchema, DataType, FieldSchema
from pymilvus.milvus_client.index import IndexParams

from .candidate_store import _client, truncate_field
from .config import get_zilliz_config
from .global_logger import logger


_zilliz_config = get_zilliz_config()
_collection_name = _zilliz_config.get("job_optimization_collection_name", "CN_job_optimizations")
_vector_dim = 2  # Minimal vector dimension required by Zilliz Serverless collections.


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


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


def get_collection_schema() -> list[FieldSchema]:
    """Schema for job optimization feedback items."""
    return [
        FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
        FieldSchema(name="feedback_vector", dtype=DataType.FLOAT_VECTOR, dim=_vector_dim),
        FieldSchema(name="job_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="job_applied", dtype=DataType.VARCHAR, max_length=200, nullable=True),
        FieldSchema(name="candidate_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="conversation_id", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="candidate_name", dtype=DataType.VARCHAR, max_length=200, nullable=True),
        FieldSchema(name="current_analysis", dtype=DataType.JSON, nullable=True),
        FieldSchema(name="target_scores", dtype=DataType.JSON, nullable=True),
        FieldSchema(name="suggestion", dtype=DataType.VARCHAR, max_length=5000),
        FieldSchema(name="status", dtype=DataType.VARCHAR, max_length=32, nullable=True),
        FieldSchema(name="closed_at_job_id", dtype=DataType.VARCHAR, max_length=64, nullable=True),
        FieldSchema(name="created_at", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64),
    ]


_readable_fields = [f.name for f in get_collection_schema() if f.dtype != DataType.FLOAT_VECTOR]


def create_collection(collection_name: Optional[str] = None) -> bool:
    """Create the optimization feedback collection if it doesn't exist."""
    collection_name = collection_name or _collection_name
    try:
        if _client.has_collection(collection_name=collection_name):
            logger.info("Collection %s already exists", collection_name)
            _ensure_indexes(collection_name)
            return True

        logger.info("Creating collection %s...", collection_name)
        schema = CollectionSchema(fields=get_collection_schema(), description="Job portrait optimization feedback")
        _client.create_collection(
            collection_name=collection_name,
            dimension=_vector_dim,
            primary_field_name="id",
            id_type="string",
            vector_field_name="feedback_vector",
            metric_type="IP",
            auto_id=False,
            max_length=64,
            schema=schema,
        )

        logger.info("Creating indexes...")
        index_params = IndexParams()
        index_params.add_index(field_name="feedback_vector", index_type="AUTOINDEX", metric_type="IP")
        index_params.add_index(field_name="job_id", index_type="INVERTED")
        index_params.add_index(field_name="candidate_id", index_type="INVERTED")
        index_params.add_index(field_name="updated_at", index_type="INVERTED")
        _client.create_index(collection_name=collection_name, index_params=index_params)

        logger.info("✅ Collection %s created successfully", collection_name)
        return True
    except Exception as exc:
        logger.exception("Failed to create collection %s: %s", collection_name, exc)
        return False


def _ensure_indexes(collection_name: str) -> None:
    """Best-effort ensure indexes exist for this collection."""
    try:
        index_params = IndexParams()
        index_params.add_index(field_name="feedback_vector", index_type="AUTOINDEX", metric_type="IP")
        index_params.add_index(field_name="job_id", index_type="INVERTED")
        index_params.add_index(field_name="candidate_id", index_type="INVERTED")
        index_params.add_index(field_name="updated_at", index_type="INVERTED")
        _client.create_index(collection_name=collection_name, index_params=index_params)
        logger.info("✅ Indexes ensured for %s", collection_name)
    except Exception as exc:
        logger.warning("Skip ensuring indexes for %s: %s", collection_name, exc)


def list_feedback(job_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """List feedback items for a base_job_id (most recent first)."""
    return list_feedback_advanced(job_id, limit=limit, include_closed=False)


def list_feedback_advanced(job_id: str, *, limit: int = 200, include_closed: bool = False) -> list[dict[str, Any]]:
    """List feedback items for a base_job_id (most recent first).

    Args:
        job_id: Base job_id.
        limit: Max number of items to return.
        include_closed: If False, filters out status == 'closed'.
    """
    job_id = (job_id or "").strip()
    if not job_id:
        return []
    filter_expr = f'job_id == "{job_id}"'
    if not include_closed:
        filter_expr = f'{filter_expr} and (status != "closed")'
    try:
        # NOTE: MilvusClient.query does not support server-side sorting for this client.
        # Some code used `output_fields_order`, but it's not a real PyMilvus parameter
        # and will be ignored via **kwargs, resulting in unpredictable ordering.
        # We fetch a reasonably large window and sort client-side by `updated_at`.
        fetch_limit = 1000
        results = _client.query(
            collection_name=_collection_name,
            filter=filter_expr,
            output_fields=_readable_fields,
            limit=fetch_limit,
        )
    except Exception as exc:
        # Fallback: try querying without 'closed_at_job_id' in case schema is outdated
        try:
            legacy_fields = [f for f in _readable_fields if f != "closed_at_job_id"]
            results = _client.query(
                collection_name=_collection_name,
                filter=filter_expr,
                output_fields=legacy_fields,
                limit=fetch_limit,
            )
        except Exception as exc2:
            logger.exception("Failed to list feedback (retry also failed): %s", exc2)
            return []

    cleaned = [{k: v for k, v in (r or {}).items() if v or v == 0} for r in results or []]
    cleaned.sort(
        key=lambda r: (
            str(r.get("updated_at") or ""),
            str(r.get("created_at") or ""),
            str(r.get("id") or ""),
        ),
        reverse=True,
    )
    max_out = min(max(int(limit or 0), 1), 500)
    return cleaned[:max_out]


def count_feedback(job_id: str) -> int:
    return count_feedback_advanced(job_id, include_closed=False)


def count_feedback_advanced(job_id: str, *, include_closed: bool = False) -> int:
    job_id = (job_id or "").strip()
    if not job_id:
        return 0
    filter_expr = f'job_id == "{job_id}"'
    if not include_closed:
        filter_expr = f'{filter_expr} and (status != "closed")'
    try:
        results = _client.query(
            collection_name=_collection_name,
            filter=filter_expr,
            output_fields=["id"],
            limit=1000,
        )
        return len(results or [])
    except Exception as exc:
        logger.exception("Failed to count feedback: %s", exc)
        return 0


def get_feedback(item_id: str) -> Optional[dict[str, Any]]:
    item_id = (item_id or "").strip()
    if not item_id:
        return None
    try:
        results = _client.query(
            collection_name=_collection_name,
            filter=f'id == "{item_id}"',
            output_fields=_readable_fields,
            limit=1,
        )
    except Exception as exc:
        # Fallback: try querying without 'closed_at_job_id'
        try:
            legacy_fields = [f for f in _readable_fields if f != "closed_at_job_id"]
            results = _client.query(
                collection_name=_collection_name,
                filter=f'id == "{item_id}"',
                output_fields=legacy_fields,
                limit=1,
            )
        except Exception as exc2:
            logger.exception("Failed to get feedback (retry also failed): %s", exc2)
            return None
    if not results:
        return None
    rec = results[0] or {}
    return {k: v for k, v in rec.items() if v or v == 0}


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
    """Create or update a feedback item (upsert by primary key)."""
    job_id = (job_id or "").strip()
    candidate_id = (candidate_id or "").strip()
    conversation_id = (conversation_id or "").strip()
    candidate_name = (candidate_name or "").strip()
    job_applied = (job_applied or "").strip()
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
    if not item_id:
        item_id = str(uuid.uuid4())
        created_at = now
    else:
        existing = get_feedback(item_id)
        created_at = (existing or {}).get("created_at") or now

    record = {
        "id": truncate_field(item_id, 64),
        "feedback_vector": [0.0] * _vector_dim,
        "job_id": truncate_field(job_id, 64),
        "job_applied": truncate_field(job_applied, 200),
        "candidate_id": truncate_field(candidate_id, 64),
        "conversation_id": truncate_field(conversation_id, 128),
        "candidate_name": truncate_field(candidate_name, 200),
        "current_analysis": current_analysis or {},
        "target_scores": target_scores.to_dict(),
        "suggestion": truncate_field(suggestion, 5000),
        "status": "open",
        "created_at": truncate_field(created_at, 64),
        "updated_at": truncate_field(now, 64),
    }

    try:
        _client.upsert(collection_name=_collection_name, data=[record], partial_update=True)
    except Exception as exc:
        # Fallback: try upserting without 'closed_at_job_id'
        if "closed_at_job_id" in record:
            del record["closed_at_job_id"]
            try:
                _client.upsert(collection_name=_collection_name, data=[record], partial_update=True)
            except Exception as exc2:
                logger.exception("Failed to upsert feedback (retry also failed): %s", exc2)
                raise
        else:
            logger.exception("Failed to upsert feedback: %s", exc)
            raise

    return record


def delete_feedback(item_id: str) -> bool:
    item_id = (item_id or "").strip()
    if not item_id:
        return False
    try:
        _client.delete(collection_name=_collection_name, filter=f'id == "{item_id}"')
        return True
    except Exception as exc:
        logger.exception("Failed to delete feedback: %s", exc)
        return False


def close_feedback_items(job_id: str, item_ids: list[str], closed_at_job_id: Optional[str] = None) -> int:
    """Mark feedback items as closed (best-effort).

    Args:
        job_id: Base job ID.
        item_ids: List of feedback item IDs to close.
        closed_at_job_id: Optional versioned job_id (e.g. foo_v3) where this was optimized.

    Returns number of items updated.
    """
    job_id = (job_id or "").strip()
    ids = [i.strip() for i in (item_ids or []) if i and i.strip()]
    if not job_id or not ids:
        return 0

    now = _utc_now()
    updated = 0
    for item_id in ids:
        existing = get_feedback(item_id)
        if not existing:
            continue
        if (existing.get("job_id") or "").strip() != job_id:
            continue
        patch = {
            "id": truncate_field(item_id, 64),
            "status": "closed",
            "closed_at_job_id": truncate_field(closed_at_job_id, 64) if closed_at_job_id else None,
            "updated_at": truncate_field(now, 64),
        }
        # Include required vector field if the backend rejects partial updates without it.
        if "feedback_vector" in (existing or {}):
            patch["feedback_vector"] = existing.get("feedback_vector") or [0.0] * _vector_dim
        
        try:
            _client.upsert(collection_name=_collection_name, data=[patch], partial_update=True)
            updated += 1
        except Exception as exc:
            # Fallback: try closing without 'closed_at_job_id'
            if "closed_at_job_id" in patch:
                del patch["closed_at_job_id"]
                try:
                    _client.upsert(collection_name=_collection_name, data=[patch], partial_update=True)
                    updated += 1
                except Exception:
                    logger.warning("Failed to close feedback item %s: %s", item_id, exc)
            else:
                logger.warning("Failed to close feedback item %s: %s", item_id, exc)
    return updated
