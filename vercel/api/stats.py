#!/usr/bin/env python3
"""Vercel serverless function for statistics API.
Connects directly to Zilliz and calculates statistics without backend dependency.
"""

import os
import sys
import json
import time
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Iterable
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict

import requests
from pymilvus import MilvusClient

# --- JSON safety utilities (must be defined early) ----------------------------------------

_KEY_TYPES = (str, int, float, bool, type(None))


def _safe_key(key: Any) -> Any:
    """Convert mapping keys to JSON-safe primitives (str/int/float/bool/None).

    Vercel's Python runtime uses ``json.dumps`` on the ASGI result; if any
    dictionary key is ``bytes`` (a pattern we've hit when upstream data
    contains binary field names), encoding fails with::

        TypeError: keys must be str, int, float, bool or None, not bytes

    This helper normalizes keys before FastAPI encodes the response.
    """

    if isinstance(key, _KEY_TYPES):
        return key
    if isinstance(key, bytes):
        try:
            return key.decode("utf-8")
        except Exception:
            return key.hex()
    # Fallback: string representation keeps structure readable.
    return str(key)


def _json_safe(obj: Any) -> Any:
    """Recursively make an object JSON-serializable and safe for Vercel.

    - Converts mapping keys via ``_safe_key``
    - Decodes ``bytes`` values to UTF-8 (hex fallback)
    - Serializes ``datetime/date`` to ISO strings
    - Leaves other primitives untouched; sequences are processed element-wise
    """

    if isinstance(obj, dict):
        return { _safe_key(k): _json_safe(v) for k, v in obj.items() }
    if isinstance(obj, (list, tuple, set)):
        return [ _json_safe(v) for v in obj ]
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except Exception:
            return obj.hex()
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    return obj

# --- End JSON safety utilities ------------------------------------------------------------

def _env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read env var as string, stripping whitespace and optional surrounding quotes."""
    value = os.environ.get(name, default)
    if value is None:
        return None
    s = str(value).strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        s = s[1:-1]
    return s


def _env_int(name: str, default: int) -> int:
    """Read env var as int, supporting values wrapped in quotes."""
    raw = _env_str(name, str(default))
    return int(str(raw).strip())


# Configuration from environment variables
ZILLIZ_ENDPOINT = _env_str("ZILLIZ_ENDPOINT")
ZILLIZ_TOKEN = _env_str("ZILLIZ_TOKEN", "") or ""
ZILLIZ_USER = _env_str("ZILLIZ_USER")
ZILLIZ_PASSWORD = _env_str("ZILLIZ_PASSWORD")
CANDIDATE_COLLECTION_NAME = _env_str("ZILLIZ_CANDIDATE_COLLECTION_NAME", "CN_candidates") or "CN_candidates"
JOB_COLLECTION_NAME = _env_str("ZILLIZ_JOB_COLLECTION_NAME", "CN_jobs") or "CN_jobs"
EMBEDDING_DIM = _env_int("ZILLIZ_EMBEDDING_DIM", 1536)

# Stage definitions (from candidate_stages.py)
STAGE_PASS = "PASS"
STAGE_CHAT = "CHAT"
STAGE_SEEK = "SEEK"
STAGE_CONTACT = "CONTACT"
HIGH_SCORE_THRESHOLD = 7

# Initialize Zilliz clients - try to create on module load if credentials are available
# This ensures connection is available early, similar to candidate_store.py
_candidate_client = None
_job_client = None

def _create_candidate_client() -> MilvusClient:
    """Create and return a MilvusClient instance.
    
    Raises:
        ValueError: If credentials are missing or connection fails.
    """
    missing = []
    if not ZILLIZ_ENDPOINT:
        missing.append('ZILLIZ_ENDPOINT')
    if not ZILLIZ_USER:
        missing.append('ZILLIZ_USER')
    if not ZILLIZ_PASSWORD:
        missing.append('ZILLIZ_PASSWORD')
    
    if missing:
        raise RuntimeError(f'Zilliz credentials not configured. Missing: {", ".join(missing)}. Please set these environment variables in Vercel.')
    
    # Create client - will raise exception if connection fails
    # Only pass token if it's provided and not empty
    # When using user/password auth, token should not be passed
    token_value = ZILLIZ_TOKEN if (ZILLIZ_TOKEN and ZILLIZ_TOKEN.strip()) else None
    
    client_kwargs = {
        'uri': ZILLIZ_ENDPOINT,
        'user': ZILLIZ_USER,
        'password': ZILLIZ_PASSWORD,
        'secure': ZILLIZ_ENDPOINT.startswith('https://'),
    }
    # Only add token if it's explicitly provided (for API key auth)
    if token_value:
        client_kwargs['token'] = token_value
    
    client = MilvusClient(**client_kwargs)
    
    # Verify connection - will raise exception if verification fails
    # This ensures the connection is actually established before returning
    client.list_collections()
    
    return client

# Lazy init: do not connect to Zilliz at module import time.
# This prevents Vercel/ASGI runtime init from crashing before we can serve requests.
# We still fail fast on first use (get_candidate_client()).
_candidate_client = None

def get_candidate_client() -> MilvusClient:
    """Get candidate collection Zilliz client.
    
    Creates client on first call if not already created.
    Raises exception if connection fails - ensures client is always valid when returned.
    
    Returns:
        MilvusClient: Valid, connected client instance
        
    Raises:
        ValueError: If credentials are missing or connection fails
    """
    global _candidate_client
    
    # Lazy initialization: create client only if None
    # This allows retry after connection failures (when reset to None)
    if _candidate_client is None:
        _candidate_client = _create_candidate_client()
    
    # If we reach here, client is guaranteed to be valid
    return _candidate_client

def get_job_client():
    """Get or create job collection Zilliz client (reuse same connection)"""
    global _job_client
    if _job_client is None:
        # Reuse candidate client connection
        _job_client = get_candidate_client()
    return _job_client

# Stage utilities (from candidate_stages.py)
def normalize_stage(stage: Optional[str]) -> str:
    """Normalize stage name to uppercase standard form."""
    if not stage:
        return ""
    stage_upper = stage.upper().strip()
    valid_stages = {STAGE_PASS, STAGE_CHAT, STAGE_SEEK, STAGE_CONTACT}
    return stage_upper if stage_upper in valid_stages else ""

# Statistics calculation functions (from stats_service.py)
def _parse_dt(value: str) -> Optional[datetime]:
    """Parse ISO timestamp stored in Milvus records."""
    if not value:
        return None
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except Exception as e:
        # Data quality issue: some records may contain non-ISO timestamps (e.g. "guzgc80j5h").
        # We skip those records instead of crashing the whole endpoint.
        return None

@dataclass
class ScoreAnalysis:
    count: int
    average: float
    high_share: float
    distribution: Dict[int, int]
    quality_score: float
    comment: str

def _score_quality(scores: List[int]) -> ScoreAnalysis:
    """计算肖像得分，用于评估岗位画像质量。"""
    if not scores:
        return ScoreAnalysis(0, 0.0, 0.0, {}, 0.0, "暂无评分数据")
    
    import numpy as np
    
    arr = np.clip(np.array(scores, dtype=int), 1, 10)
    avg = float(arr.mean())
    # Ensure keys are Python int, not numpy int types (which might cause serialization issues)
    unique_vals, counts = np.unique(arr, return_counts=True)
    dist_dict = {int(k): int(v) for k, v in zip(unique_vals, counts)}

    focus = arr[(arr >= 3) & (arr <= 8)]
    if focus.size:
        counts = np.bincount(focus, minlength=11)[3:9]
        max_dev = (counts.max() - counts.min()) / max(1, counts.sum())
        uniform_score = max(0.0, 1 - max_dev * 1.5)
    else:
        uniform_score = 0.1

    high_share = float((arr >= HIGH_SCORE_THRESHOLD).mean())

    high_penalty = max(0.0, (high_share - 0.25) / 0.75)
    center_score = max(0.0, 1 - abs(avg - 6) / 6)

    quality = (uniform_score * 0.4) + ((1 - high_penalty) * 0.3) + (center_score * 0.3)
    quality_score = round(max(1.0, min(10.0, quality * 10)), 1)

    comment = (
        "分布集中在高分段，需优化画像" if high_penalty > 0.1
        else "分布均衡，画像质量良好" if uniform_score > 0.6
        else "分布略偏，可再细化画像"
    )

    return ScoreAnalysis(
        count=sum(dist_dict.values()),
        average=round(avg, 2),
        high_share=round(high_share, 3),
        distribution=dist_dict,
        quality_score=quality_score,
        comment=comment,
    )

def dist_count(items: Iterable[int], predicate) -> int:
    """Count how many items satisfy a predicate."""
    return sum(1 for i in items if predicate(i))

def build_daily_series(candidates: List[Dict[str, Any]], days: int = 7) -> List[Dict[str, Any]]:
    """Build a per-day series for the last N days for a job: new candidates and SEEK stage counts."""
    today = datetime.now().date()
    start = today - timedelta(days=days - 1)

    bucket = defaultdict(lambda: {"new": 0, "seek": 0, "processed": 0})
    for cand in candidates:
        dt = _parse_dt(cand.get("updated_at"))
        if not dt:
            continue
        day = dt.date()
        if day < start:
            continue
        bucket[day]["new"] += 1
        if normalize_stage(cand.get("stage")) == STAGE_SEEK:
            bucket[day]["seek"] += 1
        # Check if processed: strictly contacted metadata
        contacted = cand.get("metadata", {}).get("contacted")
        if contacted:
            bucket[day]["processed"] += 1

    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        data = bucket.get(d, {"new": 0, "seek": 0, "processed": 0})
        series.append({"date": d.isoformat(), **data})
    return series

def build_daily_candidate_counts(candidates: List[Dict[str, Any]], total_count: int, days: int = 30) -> List[Dict[str, Any]]:
    """Build daily cumulative candidate counts for historical chart.
    
    Note: Candidate collection only has updated_at field, not created_at.
    We use updated_at as the date for counting.
    
    Args:
        candidates: List of candidate records (limited by Milvus query limit)
        total_count: Total number of candidates in the collection
        days: Number of days to show in the chart
    """
    today = datetime.now().date()
    start = today - timedelta(days=days - 1)
    
    # Count candidates by updated_at date (candidate collection doesn't have created_at)
    daily_counts = defaultdict(int)
    candidates_without_date = 0
    candidates_in_period = 0
    
    for cand in candidates:
        # Candidate collection only has updated_at, not created_at
        dt = _parse_dt(cand.get("updated_at"))
        if not dt:
            candidates_without_date += 1
            continue
        day = dt.date()
        if day >= start:
            daily_counts[day] += 1
            candidates_in_period += 1
    
    # Calculate candidates before the period
    # Since we can only fetch 16384 candidates, we estimate:
    # total_count - candidates_in_period - candidates_without_date = candidates_before_start
    candidates_before_start = max(0, total_count - candidates_in_period - candidates_without_date)
    
    # NOTE: Keep this function quiet; it runs on many requests.
    
    # Build cumulative series starting from candidates before the period
    series = []
    cumulative = candidates_before_start
    for i in range(days):
        d = start + timedelta(days=i)
        count = daily_counts.get(d, 0)
        cumulative += count
        series.append({
            "date": d.isoformat(),
            "count": cumulative,
            "new": count
        })
    return series

def conversion_table(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Calculate stage conversion rates."""
    stage_counts = Counter(normalize_stage(cand.get("stage")) or "" for cand in candidates)
    rows: List[Dict[str, Any]] = []
    
    pass_count = stage_counts.get(STAGE_PASS, 0)
    chat_count = stage_counts.get(STAGE_CHAT, 0)
    seek_count = stage_counts.get(STAGE_SEEK, 0)
    contact_count = stage_counts.get(STAGE_CONTACT, 0)
    
    total_screened = pass_count + chat_count + seek_count + contact_count
    
    rows.append({
        "stage": STAGE_PASS,
        "count": pass_count,
        "previous": total_screened,
        "rate": round(pass_count / (total_screened or 1), 3),
    })
    
    rows.append({
        "stage": STAGE_CHAT,
        "count": chat_count,
        "previous": total_screened,
        "rate": round((chat_count + seek_count + contact_count) / (total_screened or 1), 3),
    })
    
    rows.append({
        "stage": STAGE_SEEK,
        "count": seek_count,
        "previous": chat_count,
        "rate": round((seek_count + contact_count) / (chat_count or 1), 3),
    })
    
    rows.append({
        "stage": STAGE_CONTACT,
        "count": contact_count,
        "previous": seek_count,
        "rate": round(contact_count / (seek_count or 1), 3),
    })
    
    return rows

def search_candidates_advanced(
    job_applied: Optional[str] = None,
    updated_from: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 10000,
    sort_by: str = "updated_at",
    sort_direction: str = "desc",
) -> List[Dict[str, Any]]:
    """Search candidates from Zilliz."""
    client = get_candidate_client()
    
    _quote = lambda value: f"'{value.strip()}'" if value else ''
    
    fields = fields or ["candidate_id", "job_applied", "stage", "analysis", "updated_at"]
    
    conditions = []
    if job_applied:
        conditions.append(f"job_applied == {_quote(job_applied)}")
    if updated_from:
        conditions.append(f"updated_at >= {_quote(updated_from)}")
    
    filter_expr = " and ".join(conditions) if conditions else None
    
    sortable_fields = {"updated_at", "created_at", "name", "job_applied", "stage"}
    sort_by_normalized = sort_by if sort_by in sortable_fields else "updated_at"
    sort_dir = "DESC" if sort_direction.lower() != "asc" else "ASC"
    order_clause = f"{sort_by_normalized} {sort_dir}"
    
    results = client.query(
        collection_name=CANDIDATE_COLLECTION_NAME,
        filter=filter_expr,
        output_fields=fields,
        limit=limit,
        order_by=order_clause,
    )
    # Clean Milvus results immediately to prevent bytes keys from propagating
    if results:
        cleaned_results = []
        for result in results:
            cleaned_result = _json_safe(result)
            # If analysis is a JSON string, parse and clean it
            if "analysis" in cleaned_result and isinstance(cleaned_result["analysis"], str):
                try:
                    analysis_dict = json.loads(cleaned_result["analysis"])
                    cleaned_result["analysis"] = _json_safe(analysis_dict)
                except:
                    pass  # Keep as string if parsing fails
            cleaned_results.append(cleaned_result)
        
        # Sort in memory to ensure consistency (Milvus query order_by might not be reliable)
        reverse = sort_direction.lower() != "asc"
        cleaned_results.sort(key=lambda c: c.get(sort_by_normalized) or "", reverse=reverse)
        
        return cleaned_results
    return []

def get_all_jobs() -> List[Dict[str, Any]]:
    """Get all current jobs from Zilliz."""
    client = get_job_client()

    # First, verify the collection exists
    collections = client.list_collections()

    if JOB_COLLECTION_NAME not in collections:
        raise RuntimeError(f"Collection {JOB_COLLECTION_NAME} not found. Available: {collections}")

    results = client.query(
        collection_name=JOB_COLLECTION_NAME,
        filter="current == true",
        output_fields=["job_id", "position", "notification", "status"],
        limit=1000,
    )
    
    # Clean Milvus results immediately to prevent bytes keys from propagating
    jobs: List[Dict[str, Any]] = []
    for job in results:
        # Clean the job dictionary to remove bytes keys
        job_cleaned = _json_safe(job)
        job_dict = {k: v for k, v in job_cleaned.items() if v or v == 0}
        jobs.append(job_dict)

    jobs.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    # Intentionally no verbose logging here.
    return jobs

def get_candidate_count() -> int:
    """Get total candidate count."""
    client = get_candidate_client()

    # First, verify the collection exists
    collections = client.list_collections()

    if CANDIDATE_COLLECTION_NAME not in collections:
        raise RuntimeError(f"Collection {CANDIDATE_COLLECTION_NAME} not found. Available: {collections}")

    # Get collection stats
    stats = client.get_collection_stats(collection_name=CANDIDATE_COLLECTION_NAME)

    # Clean stats immediately to prevent bytes keys from propagating
    if isinstance(stats, dict):
        stats = _json_safe(stats)

    # Handle different response formats
    if isinstance(stats, dict):
        row_count = stats.get("row_count", 0)
    elif isinstance(stats, (int, str)):
        row_count = int(stats) if isinstance(stats, str) else stats
    else:
        row_count = stats.get("row_count", 0) if hasattr(stats, "get") else 0

    return int(row_count)

def fetch_job_candidates(job_name: str, days: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fetch candidates for a job with optional time range."""
    updated_from = None
    if days:
        start_dt = datetime.now() - timedelta(days=days)
        updated_from = start_dt.isoformat()
    return search_candidates_advanced(
        job_applied=job_name,
        fields=["candidate_id", "job_applied", "stage", "analysis", "updated_at", "metadata"],
        updated_from=updated_from,
        sort_by="updated_at",
        sort_direction="desc",
    )

def compile_job_stats(job_name: str) -> Dict[str, Any]:
    """Compile statistics for a single job."""
    candidates = fetch_job_candidates(job_name, days=7)
    
    recent_scores = [
        (cand.get("analysis") or {}).get("overall")
        for cand in candidates
        if (cand.get("analysis") or {}).get("overall") is not None
    ][:100]
    score_summary = _score_quality(recent_scores)

    daily = build_daily_series(candidates, days=7)
    conversions = conversion_table(candidates)

    recent_7days_candidates = candidates
    recent_7days_high = dist_count(
        [
            (c.get("analysis") or {}).get("overall")
            for c in recent_7days_candidates
            if (c.get("analysis") or {}).get("overall") is not None
        ],
        lambda s: s >= HIGH_SCORE_THRESHOLD,
    )
    recent_7days_seek = sum(1 for c in recent_7days_candidates if normalize_stage(c.get("stage")) == STAGE_SEEK)
    recent_7days_contacted = sum(1 for c in recent_7days_candidates if normalize_stage(c.get("stage")) == STAGE_CONTACT)
    recent_7days_metric = (len(recent_7days_candidates) + recent_7days_seek + recent_7days_contacted * 10) * score_summary.quality_score / 10

    # Convert score_summary to dict
    score_summary_dict = asdict(score_summary)
    
    return {
        "job": job_name,
        "daily": daily,
        "conversions": conversions,
        "score_summary": score_summary_dict,
        "today": {
            "count": len(recent_7days_candidates),
            "high": recent_7days_high,
            "seek": recent_7days_seek,
            "contacted": recent_7days_contacted,
            "metric": round(recent_7days_metric, 2),
        },
        "total": len(candidates),
    }

def compile_all_jobs() -> Dict[str, Any]:
    """Compile statistics for all jobs."""
    jobs = get_all_jobs() or []
    stats: List[Dict[str, Any]] = []
    skipped_inactive_jobs = 0
    for job in jobs:
        position = job.get("position") or job.get("job_id")
        if not position:
            continue
        status = str(job.get("status", "active") or "active").strip().lower()
        if status == "inactive":
            skipped_inactive_jobs += 1
            continue
        job_stats = compile_job_stats(position)
        # Add job status to stats for filtering
        job_stats["status"] = status
        stats.append(job_stats)
    best = max(stats, key=lambda s: s["today"]["metric"], default=None)
    result: Dict[str, Any] = {"jobs": stats, "best": best}
    if skipped_inactive_jobs:
        result["skipped_inactive_jobs"] = skipped_inactive_jobs
    return result

def convert_score_analysis(obj):
    """Recursively convert ScoreAnalysis objects to dictionaries."""
    if isinstance(obj, ScoreAnalysis):
        return asdict(obj)
    elif isinstance(obj, dict):
        return {k: convert_score_analysis(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_score_analysis(item) for item in obj]
    return obj

def format_homepage_stats_report(
    total_candidates: int,
    daily_candidate_counts: List[Dict[str, Any]],
    jobs: List[Dict[str, Any]],
    best: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """Format homepage statistics as Markdown report.
    
    Args:
        total_candidates: Total number of candidates
        daily_candidate_counts: List of daily candidate counts (last 30 days)
        jobs: List of job statistics
        best: Best performing job (optional)
        
    Returns:
        Dict with 'title' and 'message' keys
    """
    today = datetime.now().date()
    today_str = today.isoformat()
    
    # Calculate today's new candidates
    today_new = 0
    if daily_candidate_counts:
        last_day = daily_candidate_counts[-1]
        today_new = last_day.get("new", 0)
    
    # Calculate 7-day and 30-day totals
    last_7_days = daily_candidate_counts[-7:] if len(daily_candidate_counts) >= 7 else daily_candidate_counts
    last_30_days = daily_candidate_counts[-30:] if len(daily_candidate_counts) >= 30 else daily_candidate_counts
    
    new_7days = sum(d.get("new", 0) for d in last_7_days)
    new_30days = sum(d.get("new", 0) for d in last_30_days)
    
    # Calculate growth rates
    yesterday_new = 0
    last_week_same_day_new = 0
    if len(daily_candidate_counts) >= 2:
        yesterday_new = daily_candidate_counts[-2].get("new", 0)
    if len(daily_candidate_counts) >= 8:
        last_week_same_day_new = daily_candidate_counts[-8].get("new", 0)
    
    growth_yesterday = ((today_new - yesterday_new) / (yesterday_new or 1)) * 100 if yesterday_new > 0 else 0.0
    growth_last_week = ((today_new - last_week_same_day_new) / (last_week_same_day_new or 1)) * 100 if last_week_same_day_new > 0 else 0.0
    
    # Calculate average daily new in last 7 days
    avg_daily = new_7days / 7 if new_7days > 0 else 0.0
    
    # Build job statistics table
    job_rows = []
    for job in jobs:
        job_name = job.get("job", "未知岗位")
        daily = job.get("daily", [])
        
        # Get today's data from daily series
        today_job_new = 0
        today_job_seek = 0
        if daily:
            last_day = daily[-1]
            today_job_new = last_day.get("new", 0)
            today_job_seek = last_day.get("seek", 0)
            today_job_contacted = last_day.get("contacted", 0)  # Note: ensure this is in your daily series if needed
        
        # Calculate from job stat instead for consistency
        today_stat = job.get("today", {})
        today_job_new = today_stat.get("count", 0)
        today_job_seek = today_stat.get("seek", 0)
        today_job_contacted = today_stat.get("contacted", 0)
        
        total = job.get("total", 0)
        score_summary = job.get("score_summary", {})
        quality_score = score_summary.get("quality_score", 0.0)
        
        # Calculate progress score (similar to compile_job_stats)
        metric = (today_job_new + today_job_seek + today_job_contacted * 10) * quality_score / 10
        
        job_rows.append({
            "name": job_name,
            "today_new": today_job_new,
            "today_seek": today_job_seek,
            "today_contacted": today_job_contacted,
            "total": total,
            "quality": quality_score,
            "metric": round(metric, 2)
        })
    
    # Sort by metric descending
    job_rows.sort(key=lambda x: x["metric"], reverse=True)
    
    # Mark best job
    if best and job_rows:
        best_job_name = best.get("job", "")
        for row in job_rows:
            if row["name"] == best_job_name:
                row["name"] = f"🏆 {row['name']}"
                break
    
    # Build markdown message
    lines = []
    lines.append("### 📊 总体数据\n")
    lines.append(f"**候选人总数**: {total_candidates:,} 人\n")
    lines.append(f"**📈 今日新增**: {today_new} 人  ")
    lines.append(f"**📈 最近7天新增**: {new_7days} 人  ")
    lines.append(f"**📈 最近30天新增**: {new_30days} 人\n")
    lines.append(f"**📉 增长率**:")
    lines.append(f"- 较昨日: {growth_yesterday:+.1f}% (昨日新增 {yesterday_new} 人)")
    lines.append(f"- 较上周同期: {growth_last_week:+.1f}% (上周同期新增 {last_week_same_day_new} 人)\n")
    lines.append(f"**💡 趋势**: 候选人数量{'稳步增长' if avg_daily > 0 else '保持稳定'}，近7天平均每日新增约 {avg_daily:.1f} 人\n")
    lines.append("---\n")
    lines.append("### 💼 各岗位今日统计\n")
    lines.append("| 岗位 | 今日新增 | SEEK | 已联系 | 总数 | 画像质量 | 进展分 |")
    lines.append("|------|----------|------|--------|------|----------|--------|")
    
    for row in job_rows:
        lines.append(f"| {row['name']} | {row['today_new']} | {row['today_seek']} | {row['today_contacted']} | {row['total']} | {row['quality']}/10 | {row['metric']} |")
    
    lines.append("\n---\n")
    
    # Add detailed data
    if daily_candidate_counts:
        first_day = daily_candidate_counts[0]
        first_count = first_day.get("count", 0) - first_day.get("new", 0)  # Count before the period
        lines.append("**详细数据**:")
        lines.append(f"- 30天前累计: {first_count:,} 人")
        lines.append(f"- 当前累计: {total_candidates:,} 人")
        lines.append(f"- 30天净增长: {new_30days:,} 人")
    
    message = "\n".join(lines)
    title = f"每日首页统计 - {today_str}"
    
    return {"success": True, "title": title, "message": message}

def format_job_stats_report(job_stats: Dict[str, Any]) -> Dict[str, str]:
    """Format single job statistics as Markdown report.
    
    Args:
        job_stats: Job statistics dictionary
        
    Returns:
        Dict with 'title' and 'message' keys
    """
    job_name = job_stats.get("job", "未知岗位")
    today = datetime.now().date()
    today_str = today.isoformat()
    
    daily = job_stats.get("daily", [])
    today_stat = job_stats.get("today", {})
    today_new = today_stat.get("count", 0)
    today_seek = today_stat.get("seek", 0)
    today_contacted = today_stat.get("contacted", 0)
    
    total = job_stats.get("total", 0)
    score_summary = job_stats.get("score_summary", {})
    quality_score = score_summary.get("quality_score", 0.0)
    average_score = score_summary.get("average", 0.0)
    high_share = score_summary.get("high_share", 0.0)
    
    # Calculate progress score
    metric = (today_new + today_seek + today_contacted * 10) * quality_score / 10
    
    # Calculate 7-day trend
    new_7days = sum(d.get("new", 0) for d in daily[-7:]) if len(daily) >= 7 else sum(d.get("new", 0) for d in daily)
    seek_7days = sum(d.get("seek", 0) for d in daily[-7:]) if len(daily) >= 7 else sum(d.get("seek", 0) for d in daily)
    
    lines = []
    lines.append(f"### 💼 {job_name} - 今日统计\n")
    lines.append(f"**📈 今日新增**: {today_new} 人")
    lines.append(f"**📈 今日SEEK**: {today_seek} 人")
    lines.append(f"**📈 今日已联系**: {today_contacted} 人\n")
    lines.append(f"**总数**: {total} 人")
    lines.append(f"**画像质量**: {quality_score}/10")
    lines.append(f"**平均得分**: {average_score:.2f}")
    lines.append(f"**高分占比**: {high_share*100:.1f}%")
    lines.append(f"**进展分**: {metric:.2f} = (近7日 {today_new} + SEEK {today_seek} + Contacted {today_contacted} x 10) x {quality_score} / 10\n")
    lines.append(f"**最近7天**: 新增 {new_7days} 人，SEEK {seek_7days} 人")
    
    message = "\n".join(lines)
    title = f"{job_name} - 每日统计 - {today_str}"
    
    return {"success": True, "title": title, "message": message}

# Helper functions for statistics and notifications
def _get_statistics_data() -> Dict[str, Any]:
    """Get all statistics data (candidates, jobs, daily counts).
    
    Returns:
        Dict with 'total_candidates', 'jobs_serialized', 'best_serialized', 'daily_candidate_counts'
    """
    total_candidates = get_candidate_count()
    stats_data = compile_all_jobs()
    jobs = stats_data.get("jobs", [])
    best = stats_data.get("best")
    
    # Get daily candidate counts
    all_candidates = search_candidates_advanced(
        fields=["candidate_id", "updated_at"],
        limit=16384,  # Milvus max limit
        sort_by="updated_at",
        sort_direction="desc"
    )
    daily_candidate_counts = build_daily_candidate_counts(all_candidates, total_candidates, days=30)
    
    # Convert ScoreAnalysis objects to dictionaries
    jobs_serialized = convert_score_analysis(jobs)
    best_serialized = convert_score_analysis(best) if best else None
    
    result = {
        "total_candidates": total_candidates,
        "jobs_serialized": jobs_serialized,
        "best_serialized": best_serialized,
        "daily_candidate_counts": daily_candidate_counts
    }
    return result

def _get_job_notification_config(job_name: str, default_url: str, default_secret: str) -> Dict[str, Any]:
    """Get notification configuration for a job (job-specific or fallback).
    
    Args:
        job_name: Name of the job
        default_url: Fallback webhook URL from environment
        default_secret: Fallback secret from environment
        
    Returns:
        Dict with:
        - 'url': webhook url
        - 'secret': webhook secret
        - 'using_fallback': whether default env webhook is used
        - 'warning': optional human-readable reminder when fallback is used
    """
    # Get job notification config
    all_jobs = get_all_jobs()
    job_data = None
    for job in all_jobs:
        if (job.get("position") or job.get("job_id")) == job_name:
            job_data = job
            break
    
    # Determine webhook URL (priority: job.notification > default)
    job_dingtalk_url = None
    job_dingtalk_secret = None
    using_fallback = False
    warning: Optional[str] = None
    
    if job_data:
        notification = job_data.get("notification")
        if notification and isinstance(notification, dict):
            job_dingtalk_url = notification.get("url")
            job_dingtalk_secret = notification.get("secret")
    
    # Fallback to default config from environment variables
    if not job_dingtalk_url:
        job_dingtalk_url = default_url
        job_dingtalk_secret = default_secret
        using_fallback = True
        warning = (
            f"⚠️ 岗位「{job_name}」未在岗位配置(notification.url)中设置独立的钉钉通知地址，"
            f"本次已使用默认群(DINGTALK_WEBHOOK)发送。请HR在该岗位 profile 的 notification 字段里补充 url"
            f"（以及需要加签时的 secret），以便分岗位通知。"
        )
    
    return {
        "url": job_dingtalk_url,
        "secret": job_dingtalk_secret,
        "using_fallback": using_fallback,
        "warning": warning,
        "job_data": job_data
    }


def _prepend_job_fallback_notice(message: str, warning: Optional[str]) -> str:
    """Prepend a visible fallback reminder to job report message so HR sees it in DingTalk."""
    if not warning:
        return message
    # Keep this inside the markdown body (send_dingtalk_notification already renders title).
    return f"> {warning}\n\n{message}"

# DingTalk notification functions
def send_dingtalk_notification(
    title: str,
    message: str,
    webhook_url: str,
    secret: Optional[str] = None
) -> Dict[str, Any]:
    """Send notification to DingTalk group chat using webhook.
    
    Args:
        title: Title of the notification
        message: Message content to send
        webhook_url: DingTalk webhook URL
        secret: Optional secret for signature
        
    Returns:
        Dict with 'success' (bool) and 'result' (DingTalk API response or error message)
    """
    if not webhook_url:
        raise RuntimeError("DingTalk webhook URL is not configured")
    
    # Generate signature if secret is provided
    url = webhook_url
    if secret:
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode('utf-8'))
        
        # Append timestamp and signature to webhook URL
        separator = '&' if '?' in url else '?'
        url = f"{url}{separator}timestamp={timestamp}&sign={sign}"
    
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"## {title}\n\n{message}"
        }
    }
    
    response = requests.post(url, json=payload, timeout=10.0)
    response.raise_for_status()

    result = response.json()
    
    if result.get("errcode") != 0:
        errmsg = result.get("errmsg", "Unknown error")
        errcode = result.get("errcode", "Unknown")
        # Log minimal debug info on failure (masked webhook) to help diagnose token issues.
        try:
            import re
            masked_url = re.sub(r"access_token=[^&]+", "access_token=***", webhook_url)
            print(
                f"ERROR: DingTalk send failed: errcode={errcode}, errmsg={errmsg}; webhook={masked_url}",
                file=sys.stderr,
            )
        except Exception:
            print(
                f"ERROR: DingTalk send failed: errcode={errcode}, errmsg={errmsg}",
                file=sys.stderr,
            )
        raise RuntimeError(f"DingTalk API error: errcode={errcode}, errmsg={errmsg}")

    # Success: stay quiet to reduce log noise.
    return {"success": True, "result": result}

def send_overall_report(stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Send overall homepage statistics report to default DingTalk webhook.
    
    Args:
        stats: Optional pre-fetched statistics data. If None, will fetch it.
    
    Returns:
        Dict with 'success', 'type'='overall', 'sent', 'result', and optional 'warning'
    """
    # Get fallback URL and secret from environment variables
    default_dingtalk_url = _env_str("DINGTALK_WEBHOOK", "") or ""
    default_dingtalk_secret = _env_str("DINGTALK_SECRET", "") or ""
    
    if not default_dingtalk_url:
        raise RuntimeError("DINGTALK_WEBHOOK environment variable is not set")

    # Get statistics (reuse if provided, otherwise fetch)
    if stats is None:
        stats = _get_statistics_data()

    # Format report
    overall_report = format_homepage_stats_report(
        total_candidates=stats["total_candidates"],
        daily_candidate_counts=stats["daily_candidate_counts"],
        jobs=stats["jobs_serialized"],
        best=stats["best_serialized"],
    )

    # Send to DingTalk (raises on failure)
    send_result = send_dingtalk_notification(
        title=overall_report["title"],
        message=overall_report["message"],
        webhook_url=default_dingtalk_url,
        secret=default_dingtalk_secret,
    )

    result = {
        "success": True,
        "type": "overall",
        "sent": send_result["success"],
        "result": send_result["result"],
    }
    return result

def send_job_report(job_index: int, stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Send job-specific report to DingTalk.
    
    Args:
        job_index: Index of the job (0-based)
        stats: Optional pre-fetched statistics data. If None, will fetch it.
        
    Returns:
        Dict with 'success', 'type'='job', 'job_index', 'job_name', 'sent', 'result', 
        'using_fallback' (bool), and optional 'warning'
    """
    # Get fallback URL and secret from environment variables
    default_dingtalk_url = _env_str("DINGTALK_WEBHOOK", "") or ""
    default_dingtalk_secret = _env_str("DINGTALK_SECRET", "") or ""
    
    # Get job statistics (reuse if provided, otherwise fetch)
    if stats is None:
        stats = _get_statistics_data()
    jobs_serialized = stats["jobs_serialized"]

    if job_index < 0 or job_index >= len(jobs_serialized):
        raise RuntimeError(f"Job index {job_index} out of range (0-{len(jobs_serialized)-1})")

    job_stat = jobs_serialized[job_index]
    job_name = job_stat.get("job", "未知岗位")

    # Get job notification config (reuse common function)
    notification_config = _get_job_notification_config(
        job_name, default_dingtalk_url, default_dingtalk_secret
    )
    job_dingtalk_url = notification_config["url"]
    job_dingtalk_secret = notification_config["secret"]
    using_fallback = notification_config["using_fallback"]
    warning = notification_config.get("warning")

    if not job_dingtalk_url:
        raise RuntimeError("No DingTalk webhook configured (neither job-specific nor default)")

    # Format job report
    job_report = format_job_stats_report(job_stat)
    job_report["message"] = _prepend_job_fallback_notice(job_report["message"], warning)

    # Send to DingTalk (raises on failure)
    send_result = send_dingtalk_notification(
        title=job_report["title"],
        message=job_report["message"],
        webhook_url=job_dingtalk_url,
        secret=job_dingtalk_secret,
    )

    response = {
        "success": True,
        "type": "job",
        "job_index": job_index,
        "job_name": job_name,
        "sent": send_result["success"],
        "result": send_result["result"],
        "using_fallback": using_fallback,
    }

    if using_fallback:
        response["warning"] = warning or "⚠️ This job report used the default DingTalk webhook fallback."

    return response

def send_daily_reports() -> Dict[str, Any]:
    """Send daily reports: 1 overall report + N job reports.
    
    Returns:
        Dict with success count and error messages
    """
    results = {
        "overall_sent": False,
        "job_reports_sent": 0,
        "job_reports_failed": 0,
        "errors": []
    }
    
    # Get default DingTalk configuration from environment variables (fallback)
    default_dingtalk_url = _env_str("DINGTALK_WEBHOOK", "") or ""
    default_dingtalk_secret = _env_str("DINGTALK_SECRET", "") or ""

    if not default_dingtalk_url:
        raise RuntimeError("DINGTALK_WEBHOOK environment variable is not set or empty")

    # Get statistics once
    stats = _get_statistics_data()

    # 1. Send overall report (raises on failure)
    overall_result = send_overall_report(stats=stats)
    results["overall_sent"] = overall_result["sent"]

    # 2. Send individual job reports (raises on first failure)
    for job_index, job_stat in enumerate(stats["jobs_serialized"]):
        # Skip inactive jobs
        job_status = job_stat.get("status", "active")
        if job_status == "inactive":
            print(
                f"Skipping job report for inactive job: {job_stat.get('job', 'unknown')}",
                file=sys.stderr,
            )
            continue
        # Keep quiet per-job; failures will raise with context.
        job_result = send_job_report(job_index, stats=stats)
        results["job_reports_sent"] += 1 if job_result["sent"] else 0

    print(
        f"Daily reports completed. overall_sent={results['overall_sent']}, job_reports_sent={results['job_reports_sent']}",
        file=sys.stderr,
    )

    return results

# Vercel Python handler (BaseHTTPRequestHandler), mirroring jobs.py style
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs


def _send_json(handler_obj, status_code: int, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler_obj.send_response(status_code)
    handler_obj.send_header('Content-Type', 'application/json')
    handler_obj.send_header('Access-Control-Allow-Origin', '*')
    handler_obj.send_header('Content-Length', str(len(body)))
    handler_obj.end_headers()
    handler_obj.wfile.write(body)


def _parse_query(path: str) -> dict:
    if '?' not in path:
        return {}
    return parse_qs(path.split('?', 1)[1])


class handler(BaseHTTPRequestHandler):
    """Vercel entrypoint for stats endpoints."""

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        query = _parse_query(self.path)
        try:
            if path == '/api/stats':
                fmt = query.get('format', [None])[0]
                job_index_raw = query.get('job_index', [None])[0]
                job_index = int(job_index_raw) if job_index_raw is not None else None

                stats = _get_statistics_data()

                if fmt in ('report', 'text'):
                    report = format_homepage_stats_report(
                        total_candidates=stats['total_candidates'],
                        daily_candidate_counts=stats['daily_candidate_counts'],
                        jobs=stats['jobs_serialized'],
                        best=stats['best_serialized'],
                    )
                    _send_json(self, 200, report)
                    return

                if fmt == 'job_report':
                    if job_index is None or job_index < 0 or job_index >= len(stats['jobs_serialized']):
                        _send_json(self, 400, {'success': False, 'error': 'invalid or missing job_index'})
                        return
                    report = format_job_stats_report(stats['jobs_serialized'][job_index])
                    _send_json(self, 200, report)
                    return

                result = {
                    'success': True,
                    'quick_stats': {
                        'total_candidates': stats['total_candidates'],
                        'daily_candidate_counts': stats['daily_candidate_counts'],
                    },
                    'best': stats['best_serialized'],
                    'jobs': stats['jobs_serialized'],
                }
                _send_json(self, 200, result)
                return

            if path == '/api/send-report':
                rpt_type = query.get('type', [None])[0]
                job_index_raw = query.get('job_index', [None])[0]
                job_index = int(job_index_raw) if job_index_raw is not None else None

                if rpt_type == 'overall':
                    res = send_overall_report()
                elif rpt_type == 'job':
                    if job_index is None:
                        _send_json(self, 400, {'success': False, 'error': 'job_index required for type=job'})
                        return
                    res = send_job_report(job_index)
                else:
                    _send_json(self, 400, {'success': False, 'error': 'invalid type'})
                    return
                _send_json(self, 200, res)
                return

            if path == '/api/send-daily-report':
                res = send_daily_reports()
                _send_json(self, 200, res)
                return

            if path == '/api/public-url':
                # Get public URL from environment variables (most reliable in Vercel)
                public_url = ""
                
                # Try environment variables in order of preference
                env_vars = ["VERCEL_PUBLIC_URL", "PUBLIC_URL", "VERCEL_URL"]
                for env_var in env_vars:
                    value = _env_str(env_var)
                    if value:
                        public_url = str(value).strip()
                        break
                
                # Format URL if needed
                if public_url:
                    if not public_url.startswith('http'):
                        public_url = f"https://{public_url}"
                    public_url = public_url.rstrip('/')
                
                _send_json(self, 200, {"public_url": public_url})
                return

            _send_json(self, 404, {'success': False, 'error': 'Not found'})
        except Exception as e:
            _send_json(self, 500, {'success': False, 'error': f"{type(e).__name__}: {e}"})
