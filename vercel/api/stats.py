#!/usr/bin/env python3
"""Vercel serverless function for statistics API.
Connects directly to Zilliz and calculates statistics without backend dependency.
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Iterable
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict

# Import Milvus client
try:
    from pymilvus import MilvusClient
except ImportError as e:
    print(f"ERROR: Failed to import MilvusClient: {e}", file=sys.stderr)
    raise

# Configuration from environment variables
ZILLIZ_ENDPOINT = os.environ.get('ZILLIZ_ENDPOINT')
ZILLIZ_TOKEN = os.environ.get('ZILLIZ_TOKEN', '')
ZILLIZ_USER = os.environ.get('ZILLIZ_USER')
ZILLIZ_PASSWORD = os.environ.get('ZILLIZ_PASSWORD')
CANDIDATE_COLLECTION_NAME = os.environ.get('ZILLIZ_CANDIDATE_COLLECTION_NAME', 'CN_candidates')
JOB_COLLECTION_NAME = os.environ.get('ZILLIZ_JOB_COLLECTION_NAME', 'CN_jobs')
EMBEDDING_DIM = int(os.environ.get('ZILLIZ_EMBEDDING_DIM', '1536'))

# Stage definitions (from candidate_stages.py)
STAGE_PASS = "PASS"
STAGE_CHAT = "CHAT"
STAGE_SEEK = "SEEK"
STAGE_CONTACT = "CONTACT"
HIGH_SCORE_THRESHOLD = 7

# Initialize Zilliz clients
_candidate_client = None
_job_client = None

def get_candidate_client():
    """Get or create candidate collection Zilliz client"""
    global _candidate_client
    if _candidate_client is None:
        missing = []
        if not ZILLIZ_ENDPOINT:
            missing.append('ZILLIZ_ENDPOINT')
        if not ZILLIZ_USER:
            missing.append('ZILLIZ_USER')
        if not ZILLIZ_PASSWORD:
            missing.append('ZILLIZ_PASSWORD')
        
        if missing:
            raise ValueError(f'Zilliz credentials not configured. Missing: {", ".join(missing)}. Please set these environment variables in Vercel.')
        
        try:
            # Create client - MilvusClient connects automatically on creation
            # Match the exact pattern from main codebase: src/candidate_store.py
            # It passes token=_zilliz_config.get("token", '') which is empty string
            # and it works, so we do the same
            print(f"Creating MilvusClient with endpoint: {ZILLIZ_ENDPOINT[:50]}...", file=sys.stderr)
            print(f"User: {ZILLIZ_USER}, Token provided: {bool(ZILLIZ_TOKEN and ZILLIZ_TOKEN.strip())}", file=sys.stderr)
            
            # Match main codebase exactly: pass token (empty string if not provided), user, and password
            # Main codebase: token=_zilliz_config.get("token", ''), user=..., password=...
            token_value = ZILLIZ_TOKEN if (ZILLIZ_TOKEN and ZILLIZ_TOKEN.strip()) else ''
            print(f"Creating MilvusClient: uri={ZILLIZ_ENDPOINT[:50]}..., user={ZILLIZ_USER}, token={'***' if token_value else '(empty)'}", file=sys.stderr)
            
            _candidate_client = MilvusClient(
                uri=ZILLIZ_ENDPOINT,
                token=token_value,  # Empty string if not provided, matching main codebase
                user=ZILLIZ_USER,
                password=ZILLIZ_PASSWORD,
                secure=ZILLIZ_ENDPOINT.startswith('https://'),
            )
            # Verify connection by checking if we can list collections
            # This ensures the connection is actually established
            try:
                collections = _candidate_client.list_collections()
                print(f"Successfully connected to Zilliz. Available collections: {collections}", file=sys.stderr)
            except Exception as conn_err:
                print(f"Error: Connection verification failed: {conn_err}", file=sys.stderr)
                import traceback
                traceback.print_exc(file=sys.stderr)
                # Reset client to None so it will be recreated on next attempt
                _candidate_client = None
                raise ValueError(f'Failed to verify Zilliz connection: {str(conn_err)}')
        except Exception as e:
            print(f"Failed to create Zilliz client: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            raise ValueError(f'Failed to connect to Zilliz: {str(e)}')
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
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except Exception:
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
    dist_dict = {int(k): int(v) for k, v in zip(*np.unique(arr, return_counts=True))}

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
    return sum(1 for i in items if predicate(i))

def build_daily_series(candidates: List[Dict[str, Any]], days: int = 7) -> List[Dict[str, Any]]:
    today = datetime.now().date()
    start = today - timedelta(days=days - 1)

    bucket = defaultdict(lambda: {"new": 0, "seek": 0})
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

    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        data = bucket.get(d, {"new": 0, "seek": 0})
        series.append({"date": d.isoformat(), **data})
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
    
    sortable_fields = {"updated_at", "name", "job_applied", "stage"}
    sort_by_normalized = sort_by if sort_by in sortable_fields else "updated_at"
    sort_dir = "DESC" if sort_direction.lower() != "asc" else "ASC"
    order_clause = f"{sort_by_normalized} {sort_dir}"
    
    try:
        results = client.query(
            collection_name=CANDIDATE_COLLECTION_NAME,
            filter=filter_expr,
            output_fields=fields,
            limit=limit,
            order_by=order_clause,
        )
        return results or []
    except Exception as e:
        print(f"Error querying candidates: {e}", file=sys.stderr)
        return []

def get_all_jobs() -> List[Dict[str, Any]]:
    """Get all current jobs from Zilliz."""
    try:
        client = get_job_client()
        
        # First, verify the collection exists
        collections = client.list_collections()
        print(f"Available collections for jobs: {collections}", file=sys.stderr)
        
        if JOB_COLLECTION_NAME not in collections:
            print(f"Warning: Collection {JOB_COLLECTION_NAME} not found. Available: {collections}", file=sys.stderr)
            return []
        
        results = client.query(
            collection_name=JOB_COLLECTION_NAME,
            filter='current == true',
            output_fields=["job_id", "position"],
            limit=1000
        )
        
        jobs = []
        for job in results:
            job_dict = {k: v for k, v in job.items() if v or v == 0}
            jobs.append(job_dict)
        
        jobs.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        print(f"Found {len(jobs)} jobs", file=sys.stderr)
        return jobs
    except Exception as e:
        print(f"Error querying jobs: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        # Reset clients to force reconnection on next call
        global _candidate_client, _job_client
        _candidate_client = None
        _job_client = None
        return []

def get_candidate_count() -> int:
    """Get total candidate count."""
    try:
        client = get_candidate_client()
        
        # First, verify the collection exists
        collections = client.list_collections()
        print(f"Available collections: {collections}", file=sys.stderr)
        
        if CANDIDATE_COLLECTION_NAME not in collections:
            print(f"Warning: Collection {CANDIDATE_COLLECTION_NAME} not found. Available: {collections}", file=sys.stderr)
            return 0
        
        # Get collection stats
        stats = client.get_collection_stats(collection_name=CANDIDATE_COLLECTION_NAME)
        print(f"Collection stats response: {stats}, type: {type(stats)}", file=sys.stderr)
        
        # Handle different response formats
        if isinstance(stats, dict):
            row_count = stats.get('row_count', 0)
        elif isinstance(stats, (int, str)):
            row_count = int(stats) if isinstance(stats, str) else stats
        else:
            # Try to get from nested structure
            row_count = stats.get('row_count', 0) if hasattr(stats, 'get') else 0
        
        print(f"Extracted row_count: {row_count}", file=sys.stderr)
        return row_count
    except Exception as e:
        print(f"Error getting candidate count: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        # Reset client to force reconnection on next call
        global _candidate_client
        _candidate_client = None
        return 0

def fetch_job_candidates(job_name: str, days: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fetch candidates for a job with optional time range."""
    updated_from = None
    if days:
        start_dt = datetime.now() - timedelta(days=days)
        updated_from = start_dt.isoformat()
    return search_candidates_advanced(
        job_applied=job_name,
        fields=["candidate_id", "job_applied", "stage", "analysis", "updated_at"],
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
    recent_7days_metric = (len(recent_7days_candidates) + recent_7days_seek) * score_summary.quality_score / 10

    return {
        "job": job_name,
        "daily": daily,
        "conversions": conversions,
        "score_summary": asdict(score_summary),
        "today": {
            "count": len(recent_7days_candidates),
            "high": recent_7days_high,
            "seek": recent_7days_seek,
            "metric": round(recent_7days_metric, 2),
        },
        "total": len(candidates),
    }

def compile_all_jobs() -> Dict[str, Any]:
    """Compile statistics for all jobs."""
    jobs = get_all_jobs() or []
    stats: List[Dict[str, Any]] = []
    for job in jobs:
        position = job.get("position") or job.get("job_id")
        if not position:
            continue
        try:
            stats.append(compile_job_stats(position))
        except Exception as exc:
            print(f"统计岗位 {position} 失败: {exc}", file=sys.stderr)
    best = max(stats, key=lambda s: s["today"]["metric"], default=None)
    return {"jobs": stats, "best": best}

def convert_score_analysis(obj):
    """Recursively convert ScoreAnalysis objects to dictionaries."""
    if isinstance(obj, ScoreAnalysis):
        return asdict(obj)
    elif isinstance(obj, dict):
        return {k: convert_score_analysis(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_score_analysis(item) for item in obj]
    return obj

# Vercel handler
from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler for /api/stats."""
    
    def _send_json_response(self, status_code, data):
        """Helper to send JSON response"""
        response_body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)
    
    def do_GET(self):
        """Handle GET request to /api/stats."""
        try:
            print("Starting stats API request...", file=sys.stderr)
            
            # Check environment variables
            print(f"ZILLIZ_ENDPOINT: {ZILLIZ_ENDPOINT[:50] if ZILLIZ_ENDPOINT else 'NOT SET'}...", file=sys.stderr)
            print(f"ZILLIZ_USER: {ZILLIZ_USER if ZILLIZ_USER else 'NOT SET'}", file=sys.stderr)
            print(f"CANDIDATE_COLLECTION_NAME: {CANDIDATE_COLLECTION_NAME}", file=sys.stderr)
            
            # Get candidate count
            print("Getting candidate count...", file=sys.stderr)
            total_candidates = get_candidate_count()
            print(f"Total candidates: {total_candidates}", file=sys.stderr)
            
            # Get job statistics
            print("Compiling job statistics...", file=sys.stderr)
            stats_data = compile_all_jobs()
            jobs = stats_data.get("jobs", [])
            best = stats_data.get("best")
            print(f"Found {len(jobs)} jobs", file=sys.stderr)
            
            # Convert ScoreAnalysis objects to dictionaries
            jobs_serialized = convert_score_analysis(jobs)
            best_serialized = convert_score_analysis(best) if best else None
            
            response_data = {
                "success": True,
                "quick_stats": {
                    "total_candidates": total_candidates,
                    "running_workflows": 0,  # Placeholder
                },
                "best": best_serialized,
                "jobs": jobs_serialized,
            }
            
            print("Sending response...", file=sys.stderr)
            self._send_json_response(200, response_data)
            
        except Exception as e:
            error_response = {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
            print(f"Error in stats API: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            self._send_json_response(500, error_response)
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass
