"""
Vercel serverless function for jobs API
Connects directly to Zilliz using environment variables
"""

import os
import sys
import json
import re
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

# Import Milvus client with error handling
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
COLLECTION_NAME = os.environ.get('ZILLIZ_JOB_COLLECTION_NAME', 'CN_jobs')
OPT_COLLECTION_NAME = os.environ.get('ZILLIZ_JOB_OPTIMIZATION_COLLECTION_NAME', 'CN_job_optimizations')
DEFAULT_OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
DEFAULT_OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-5.2')
EMBEDDING_DIM = int(os.environ.get('ZILLIZ_EMBEDDING_DIM', '1536'))

# Initialize Zilliz client
_client = None

# Requests is already a dependency for Vercel stats; reuse it here to call OpenAI.
import requests

# --- JSON safety utilities (mirrors vercel/api/stats.py) -----------------------------

_KEY_TYPES = (str, int, float, bool, type(None))


def _safe_key(key: Any) -> Any:
    if isinstance(key, _KEY_TYPES):
        return key
    if isinstance(key, bytes):
        try:
            return key.decode("utf-8")
        except Exception:
            return key.hex()
    return str(key)


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {_safe_key(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except Exception:
            return obj.hex()
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    return obj

# --- End JSON safety utilities -------------------------------------------------------

def _truncate_utf8(text: Any, max_bytes: int) -> str:
    """Truncate text by UTF-8 byte length (Milvus VARCHAR max_length is strict)."""
    if text is None:
        return ""
    s = str(text)
    b = s.encode("utf-8")
    if len(b) <= max_bytes:
        return s
    return b[:max_bytes].decode("utf-8", errors="ignore")


def _parse_version_from_job_id(job_id: str) -> int:
    m = re.search(r"_v(\d+)$", job_id or "")
    if not m:
        return 0
    try:
        return int(m.group(1))
    except Exception:
        return 0


def _validate_requirements_text(requirements: str) -> tuple[bool, str]:
    text = (requirements or "").strip()
    if not text:
        return False, "评分标准不能为空"
    if len(text.encode("utf-8")) > 5000:
        return False, "评分标准过长（超过 5000 字节），请精简"
    return True, ""


def _normalize_job_text_fields(job_data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure all VARCHAR fields are truncated to schema max_length."""
    out = dict(job_data)
    out["position"] = _truncate_utf8(out.get("position", ""), 200)
    out["background"] = _truncate_utf8(out.get("background", ""), 5000)
    out["description"] = _truncate_utf8(out.get("description", ""), 5000)
    out["responsibilities"] = _truncate_utf8(out.get("responsibilities", ""), 5000)
    out["requirements"] = _truncate_utf8(out.get("requirements", ""), 5000)
    out["target_profile"] = _truncate_utf8(out.get("target_profile", ""), 5000)
    # `drill_down_questions` is larger in schema; keep conservative to avoid surprises.
    out["drill_down_questions"] = _truncate_utf8(out.get("drill_down_questions", ""), 30000)
    return out

def _validate_notification_required(notification: Any) -> tuple[bool, str]:
    if not isinstance(notification, dict):
        return False, "notification is required (dingtalk webhook url + secret)"
    url = (notification.get("url") or "").strip()
    secret = (notification.get("secret") or "").strip()
    if not url or not secret:
        return False, "notification.url and notification.secret are required"
    return True, ""

# --- Job portrait optimization (OpenAI + CN_job_optimizations) -----------------------

def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _truncate_field(value: Any, max_bytes: int) -> str:
    return _truncate_utf8("" if value is None else value, max_bytes)


_OPT_READABLE_FIELDS = [
    "id",
    "job_id",
    "job_applied",
    "candidate_id",
    "conversation_id",
    "candidate_name",
    "current_analysis",
    "target_scores",
    "suggestion",
    "status",
    "closed_at_job_id",
    "created_at",
    "updated_at",
]


def _list_feedback(job_id: str, *, limit: int = 200, include_closed: bool = False) -> list[dict[str, Any]]:
    job_id = (job_id or "").strip()
    if not job_id:
        return []
    filter_expr = f'job_id == "{job_id}"'
    if not include_closed:
        filter_expr = f'{filter_expr} and (status != "closed")'
    try:
        results = get_client().query(
            collection_name=OPT_COLLECTION_NAME,
            filter=filter_expr,
            output_fields=_OPT_READABLE_FIELDS,
            limit=1000,
        )
    except Exception as exc:
        print(f"Failed to list optimizations: {exc}", file=sys.stderr)
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


def _count_feedback(job_id: str, *, include_closed: bool = False) -> int:
    job_id = (job_id or "").strip()
    if not job_id:
        return 0
    filter_expr = f'job_id == "{job_id}"'
    if not include_closed:
        filter_expr = f'{filter_expr} and (status != "closed")'
    try:
        results = get_client().query(
            collection_name=OPT_COLLECTION_NAME,
            filter=filter_expr,
            output_fields=["id"],
            limit=1000,
        )
        return len(results or [])
    except Exception as exc:
        print(f"Failed to count optimizations: {exc}", file=sys.stderr)
        return 0


def _get_feedback(item_id: str) -> Optional[dict[str, Any]]:
    item_id = (item_id or "").strip()
    if not item_id:
        return None
    try:
        results = get_client().query(
            collection_name=OPT_COLLECTION_NAME,
            filter=f'id == "{item_id}"',
            output_fields=_OPT_READABLE_FIELDS + ["feedback_vector"],
            limit=1,
        )
    except Exception:
        return None
    if not results:
        return None
    rec = results[0] or {}
    return {k: v for k, v in rec.items() if v or v == 0}


def _upsert_feedback(record: dict[str, Any]) -> dict[str, Any]:
    get_client().upsert(collection_name=OPT_COLLECTION_NAME, data=[record], partial_update=True)
    return record


def _close_feedback_items(job_id: str, item_ids: list[str], closed_at_job_id: Optional[str] = None) -> int:
    job_id = (job_id or "").strip()
    ids = [i.strip() for i in (item_ids or []) if i and i.strip()]
    if not job_id or not ids:
        return 0
    now = _utc_now()
    updated = 0
    for item_id in ids:
        existing = _get_feedback(item_id)
        if not existing:
            continue
        if (existing.get("job_id") or "").strip() != job_id:
            continue
        patch = {
            "id": _truncate_field(item_id, 64),
            "status": "closed",
            "closed_at_job_id": _truncate_field(closed_at_job_id, 64) if closed_at_job_id else None,
            "updated_at": _truncate_field(now, 64),
        }
        if "feedback_vector" in existing:
            patch["feedback_vector"] = existing.get("feedback_vector") or [0.0, 0.0]
        try:
            get_client().upsert(collection_name=OPT_COLLECTION_NAME, data=[patch], partial_update=True)
            updated += 1
        except Exception as exc:
            print(f"Failed to close optimization item {item_id}: {exc}", file=sys.stderr)
    return updated


_DOWNSTREAM_USAGE = """
岗位肖像会被系统用于两类动作：
1) ANALYZE：根据 requirements（文本，一行一个评分项/维度）逐行打分（confirmed + potential，potential 只按 50% 计入），并给出 overall/skill/background/startup_fit（1-10）与阶段建议（PASS/CHAT/SEEK/CONTACT）。
2) CHAT/FOLLOWUP：从 drill_down_questions 中挑 1 个主问题（线上甄别），避免做题式连环追问；PASS 候选人不发消息；不聊薪资、不约时间、不替 HR 安排面试。
""".strip()


def _openai_generate_job_portrait_optimization(current_job: dict[str, Any], feedback_items: list[dict[str, Any]]) -> dict[str, Any]:
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY env var")
    base_url = (os.environ.get("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL).strip()
    model = (os.environ.get("OPENAI_MODEL_OPTIMIZATION") or DEFAULT_OPENAI_MODEL or "gpt-5.2").strip()

    # Schema: strict JSON output for job portrait + per-field rationale.
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["job_portrait", "rationale"],
        "properties": {
            "job_portrait": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "position",
                    "description",
                    "responsibilities",
                    "requirements",
                    "target_profile",
                    "keywords",
                    "drill_down_questions",
                    "candidate_filters",
                ],
                "properties": {
                    "position": {"type": "string"},
                    "description": {"type": "string"},
                    "responsibilities": {"type": "string"},
                    "requirements": {"type": "string"},
                    "target_profile": {"type": "string"},
                    "drill_down_questions": {"type": "string"},
                    "candidate_filters": {"type": ["string", "null"]},
                    "keywords": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["positive", "negative"],
                        "properties": {
                            "positive": {"type": "array", "items": {"type": "string"}},
                            "negative": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
            "rationale": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "description",
                    "responsibilities",
                    "requirements",
                    "target_profile",
                    "keywords",
                    "drill_down_questions",
                    "candidate_filters",
                    "overall_notes",
                ],
                "properties": {
                    "description": {"type": "string"},
                    "responsibilities": {"type": "string"},
                    "requirements": {"type": "string"},
                    "target_profile": {"type": "string"},
                    "keywords": {"type": "string"},
                    "drill_down_questions": {"type": "string"},
                    "candidate_filters": {"type": "string"},
                    "overall_notes": {"type": "string"},
                },
            },
        },
    }

    prompt = f"""
你是招聘策略与岗位画像优化专家。请基于“当前岗位肖像”和“人类反馈清单”，输出一版更适合线上甄别候选人的岗位肖像，要求评分更稳定、更少幻觉、更能筛掉不匹配人群。

【硬约束（必须遵守）】
1) position 必须保持不变（与 current_job_portrait.position 完全一致）。
2) requirements 必须是文本评分标准：严格 4 行，每行以权重数字开头（40/30/20/10），权重之和=100；每行写可判定信号（强信号/红旗），避免正确废话。
3) drill_down_questions 仅用于线上甄别：每行 1 个问题；问题必须逼候选人讲“亲历+过程+关键取舍+指标变化+你负责的部分”；不问管理/绩效/组织类问题；不问能直接查标准答案的问题；不让候选人画图/交材料。
4) keywords 必须保留 positive/negative 两组语义：每个元素一个短语；不要随意清空/大量删除；若删改必须在 rationale.keywords 说明原因。
5) candidate_filters 输出必须为 null（系统会继承上一版，不允许本次优化修改）。
6) 强调底层核心能力与边界问题处理经验（取舍/边界/故障与恢复/一致性/版本兼容/成本与性能/机制化治理），不要只写“私有化交付”这类表层能力。

【输入】
current_job_portrait = {json.dumps(_json_safe(current_job), ensure_ascii=False)}
feedback_items = {json.dumps(_json_safe(feedback_items), ensure_ascii=False)}
downstream_usage = {_json_safe(_DOWNSTREAM_USAGE)!r}

【输出（强制 JSON，且必须满足给定 schema）】
""".strip()

    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "只输出 JSON，不要 markdown，不要解释。严格遵守 schema。"},
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "JobPortraitOptimizationSchema", "schema": schema, "strict": True},
        },
        "temperature": 0.2,
    }
    # NOTE: do not set a client-side timeout here; some providers can take minutes for long outputs.
    # If you want to enforce a timeout anyway, set OPENAI_HTTP_TIMEOUT_SECONDS (float).
    timeout_raw = (os.environ.get("OPENAI_HTTP_TIMEOUT_SECONDS") or "").strip()
    timeout: Optional[float] = None
    if timeout_raw:
        timeout = float(timeout_raw)

    request_kwargs: Dict[str, Any] = {
        "url": url,
        "headers": {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        "json": payload,
    }
    if timeout is not None:
        request_kwargs["timeout"] = timeout

    resp = requests.post(**request_kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenAI error {resp.status_code}: {resp.text[:800]}")
    data = resp.json()
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    try:
        parsed = json.loads(content)
    except Exception:
        raise RuntimeError("OpenAI returned non-JSON content")
    return parsed


def get_client():
    """Get or create Zilliz client"""
    global _client
    if _client is None:
        missing = []
        if not ZILLIZ_ENDPOINT:
            missing.append('ZILLIZ_ENDPOINT')
        if not ZILLIZ_USER:
            missing.append('ZILLIZ_USER')
        if not ZILLIZ_PASSWORD:
            missing.append('ZILLIZ_PASSWORD')
        
        if missing:
            raise RuntimeError(f'Zilliz credentials not configured. Missing: {", ".join(missing)}. Please set these environment variables in Vercel.')
        
        try:
            # Match the working pattern from stats.py
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
            
            _client = MilvusClient(**client_kwargs)
        except Exception as e:
            raise RuntimeError(f'Failed to connect to Zilliz: {str(e)}')
    return _client

def get_base_job_id(job_id: str) -> str:
    """Extract base job_id by removing version suffix"""
    return re.sub(r'_v\d+$', '', job_id)

def get_all_jobs() -> List[Dict[str, Any]]:
    """Get all jobs (current versions only)"""
    client = get_client()
    results = client.query(
        collection_name=COLLECTION_NAME,
        filter='current == true',
        output_fields=[
            'job_id', 'position', 'background', 'description', 'responsibilities',
            'requirements', 'target_profile', 'keywords', 'drill_down_questions',
            'candidate_filters', 'version', 'current', 'created_at', 'updated_at', 'notification'
        ],
        limit=1000
    )
    
    # De-dupe by base_job_id in case multiple versions are marked current.
    best_by_base: dict[str, Dict[str, Any]] = {}
    for job in results:
        job_dict = {k: v for k, v in job.items() if v is not None and v != ''}
        if 'job_id' in job_dict:
            job_dict['base_job_id'] = get_base_job_id(job_dict['job_id'])
        base_job_id = job_dict.get("base_job_id") or ""
        if not base_job_id:
            continue
        v = job_dict.get("version")
        version = int(v) if isinstance(v, (int, float)) else _parse_version_from_job_id(job_dict.get("job_id", ""))
        prev = best_by_base.get(base_job_id)
        if not prev:
            best_by_base[base_job_id] = job_dict
            continue
        prev_v = prev.get("version")
        prev_version = int(prev_v) if isinstance(prev_v, (int, float)) else _parse_version_from_job_id(prev.get("job_id", ""))
        if version >= prev_version:
            best_by_base[base_job_id] = job_dict
    
    jobs = list(best_by_base.values())
    jobs.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
    return jobs

def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    """Get specific job by job_id (can be base_job_id or versioned_job_id)
    If versioned_job_id is provided, returns that specific version.
    If base_job_id is provided, returns the current version.
    """
    client = get_client()
    
    # Check if job_id is already versioned (contains _v followed by digits)
    if re.match(r'.+_v\d+$', job_id):
        # It's a versioned job_id, fetch that specific version
        versioned_job_id = job_id
        base_job_id = get_base_job_id(job_id)
    else:
        # It's a base_job_id, fetch current version
        base_job_id = job_id
        versioned_job_id = None
    
    # Build filter
    if versioned_job_id:
        # Fetch specific version
        filter_expr = f'job_id == "{versioned_job_id}"'
    else:
        # Fetch current version
        filter_expr = f'job_id >= "{base_job_id}_v" && job_id < "{base_job_id}_w" && current == true'
    
    results = client.query(
        collection_name=COLLECTION_NAME,
        filter=filter_expr,
        output_fields=[
            'job_id', 'position', 'background', 'description', 'responsibilities',
            'requirements', 'target_profile', 'keywords', 'drill_down_questions',
            'candidate_filters', 'version', 'current', 'created_at', 'updated_at', 'notification'
        ],
        limit=100
    )
    
    if versioned_job_id:
        for job in results:
            if job.get("job_id") == versioned_job_id:
                job_dict = {k: v for k, v in job.items() if v is not None and v != ""}
                job_dict["base_job_id"] = base_job_id
                return job_dict
        return None

    # Base job_id: choose the highest version among "current == true" rows (defensive).
    candidates: list[Dict[str, Any]] = []
    for job in results:
        job_id_value = job.get("job_id", "")
        if not job_id_value.startswith(f"{base_job_id}_v"):
            continue
        if not re.match(rf"^{re.escape(base_job_id)}_v\d+$", job_id_value):
            continue
        candidates.append(job)

    if not candidates:
        return None

    def _version_of(row: Dict[str, Any]) -> int:
        v = row.get("version")
        if isinstance(v, (int, float)):
            return int(v)
        return _parse_version_from_job_id(row.get("job_id", ""))

    best = max(candidates, key=_version_of)
    job_dict = {k: v for k, v in best.items() if v is not None and v != ""}
    job_dict["base_job_id"] = base_job_id
    return job_dict
    

def insert_job(**job_data) -> bool:
    """Insert a new job"""
    client = get_client()
    job_id = job_data.get('job_id') or job_data.get('id', '')
    if not job_id:
        raise RuntimeError('job_id is required')
    base_job_id = get_base_job_id(job_id)
    versioned_job_id = f'{base_job_id}_v1'
    if len(versioned_job_id.encode("utf-8")) > 64:
        raise RuntimeError("job_id 过长（含版本后超过 64 字节），请缩短岗位 ID")
    
    normalized = _normalize_job_text_fields(job_data)
    ok, err = _validate_notification_required(job_data.get("notification"))
    if not ok:
        raise RuntimeError(err)
    ok, err = _validate_requirements_text(normalized.get("requirements", ""))
    if not ok:
        raise RuntimeError(err)

    now = datetime.now().isoformat()
    
    insert_data = {
        'job_id': versioned_job_id,
        'position': normalized.get("position") or "",
        'background': normalized.get("background") or "",
        'description': normalized.get("description") or "",
        'responsibilities': normalized.get("responsibilities") or "",
        'requirements': normalized.get("requirements") or "",
        'target_profile': normalized.get("target_profile") or "",
        'keywords': job_data.get('keywords', {'positive': [], 'negative': []}),
        'drill_down_questions': normalized.get("drill_down_questions") or "",
        'candidate_filters': job_data.get('candidate_filters'),
        'notification': job_data.get('notification'),
        'job_embedding': [0.0] * EMBEDDING_DIM,
        'version': 1,
        'current': True,
        'created_at': now,
        'updated_at': now,
    }
    
    client.insert(collection_name=COLLECTION_NAME, data=[insert_data])
    return True

def update_job(job_id: str, **job_data) -> Optional[str]:
    """Update job (creates new version)"""
    client = get_client()
    base_job_id = get_base_job_id(job_id)
    
    # Get current job
    current_job = get_job_by_id(base_job_id)
    if not current_job:
        return False
    
    # Get all versions
    all_versions = get_job_versions(base_job_id)
    max_version = max([v.get('version', 0) for v in all_versions], default=0)
    next_version = max_version + 1
    new_versioned_job_id = f'{base_job_id}_v{next_version}'
    if len(new_versioned_job_id.encode("utf-8")) > 64:
        raise RuntimeError("job_id 过长（含版本后超过 64 字节），请缩短岗位 ID")

    # Create new version
    now = datetime.now().isoformat()
    merged = dict(current_job)
    merged.update(job_data)
    normalized = _normalize_job_text_fields(merged)
    ok, err = _validate_notification_required(merged.get("notification"))
    if not ok:
        raise RuntimeError(err)
    ok, err = _validate_requirements_text(normalized.get("requirements", ""))
    if not ok:
        raise RuntimeError(err)

    new_version_data = {
        'job_id': new_versioned_job_id,
        'position': normalized.get('position', '') or '',
        'background': normalized.get('background', '') or '',
        'description': normalized.get('description', '') or '',
        'responsibilities': normalized.get('responsibilities', '') or '',
        'requirements': normalized.get('requirements', '') or '',
        'target_profile': normalized.get('target_profile', '') or '',
        'keywords': merged.get('keywords', current_job.get('keywords', {'positive': [], 'negative': []})),
        'drill_down_questions': normalized.get('drill_down_questions', '') or '',
        'candidate_filters': merged.get('candidate_filters', current_job.get('candidate_filters')),
        'notification': merged.get('notification') if 'notification' in merged else current_job.get('notification'),
        'job_embedding': [0.0] * EMBEDDING_DIM,
        'version': next_version,
        'current': True,
        'created_at': current_job.get('created_at', now),
        'updated_at': now,
    }
    
    # Insert first, then flip old currents to avoid "no current" state if insert fails.
    client.insert(collection_name=COLLECTION_NAME, data=[new_version_data])

    # Mark any previous current versions as non-current (defensive).
    try:
        current_results = client.query(
            collection_name=COLLECTION_NAME,
            filter=f'job_id >= "{base_job_id}_v" && job_id < "{base_job_id}_w" && current == true',
            output_fields=["job_id", "position"],
            limit=1000,
        )
        for row in current_results:
            jid = row.get("job_id")
            if not jid or jid == new_versioned_job_id:
                continue
            pos = row.get("position") or current_job.get("position") or ""
            if not pos:
                continue
            client.upsert(
                collection_name=COLLECTION_NAME,
                data=[{"job_id": jid, "position": _truncate_utf8(pos, 200), "current": False}],
                partial_update=True,
            )
    except Exception:
        # If this cleanup fails, get_all_jobs/get_job_by_id will still pick latest version.
        pass
    return new_versioned_job_id

def get_job_versions(base_job_id: str) -> List[Dict[str, Any]]:
    """Get all versions of a job"""
    client = get_client()
    results = client.query(
        collection_name=COLLECTION_NAME,
        filter=f'job_id >= "{base_job_id}_v" && job_id < "{base_job_id}_w"',
        output_fields=[
            'job_id', 'position', 'version', 'current', 'created_at', 'updated_at'
        ],
        limit=1000
    )
    
    versions = [
        {k: v for k, v in job.items() if v is not None and v != ''}
        for job in results
        if job.get('job_id', '').startswith(f'{base_job_id}_v') and re.match(rf'^{re.escape(base_job_id)}_v\d+$', job.get('job_id', ''))
    ]
    
    versions.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return versions

def switch_job_version(base_job_id: str, version: int) -> bool:
    """Switch the current version"""
    client = get_client()
    all_versions = get_job_versions(base_job_id)
    
    target_job_id = f'{base_job_id}_v{version}'
    target_version = next((v for v in all_versions if v.get('job_id') == target_job_id), None)
    
    if not target_version:
        return False
    
    # Get full job data for all versions to ensure we have all required fields
    # Query all versions to get complete data
    results = client.query(
        collection_name=COLLECTION_NAME,
        filter=f'job_id >= "{base_job_id}_v" && job_id < "{base_job_id}_w"',
        output_fields=['job_id', 'position', 'current'],
        limit=1000
    )
    
    # Create a map of job_id to position for quick lookup
    job_positions = {job.get('job_id'): job.get('position', '') for job in results if job.get('job_id')}
    
    # Set all versions' current=False (include position to avoid DataNotMatchException)
    for v in all_versions:
        if v.get('job_id'):
            job_position = job_positions.get(v['job_id'], '')
            if job_position:  # Only update if we have the position
                client.upsert(
                    collection_name=COLLECTION_NAME,
                    data=[{'job_id': v['job_id'], 'position': job_position, 'current': False}],
                    partial_update=True
                )
    
    # Set target version's current=True (include position to avoid DataNotMatchException)
    target_position = job_positions.get(target_job_id, '')
    if target_position:
        client.upsert(
            collection_name=COLLECTION_NAME,
            data=[{'job_id': target_job_id, 'position': target_position, 'current': True}],
            partial_update=True
        )
    else:
        # Fallback: query the specific job to get its position
        target_job = get_job_by_id(target_job_id)
        if target_job and target_job.get('position'):
            client.upsert(
                collection_name=COLLECTION_NAME,
                data=[{'job_id': target_job_id, 'position': target_job['position'], 'current': True}],
                partial_update=True
            )
        else:
            return False
    
    return True

def delete_job_version(base_job_id: str, version: int) -> bool:
    """Delete a specific version"""
    client = get_client()
    versioned_job_id = f'{base_job_id}_v{version}'
    client.delete(collection_name=COLLECTION_NAME, filter=f'job_id == "{versioned_job_id}"')
    return True

# Vercel handler - must inherit from BaseHTTPRequestHandler
# See: https://vercel.com/docs/functions/runtimes/python
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote

class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler - inherits from BaseHTTPRequestHandler"""
    
    def _send_json_response(self, status_code, data):
        """Helper to send JSON response"""
        response_body = json.dumps(_json_safe(data), ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)
    
    def _get_query_params(self):
        """Extract query parameters from path"""
        if '?' in self.path:
            query_string = self.path.split('?', 1)[1]
            return parse_qs(query_string)
        return {}
    
    def _get_body(self):
        """Read and parse request body"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        
        body_bytes = self.rfile.read(content_length)
        try:
            body_str = body_bytes.decode('utf-8')
            return json.loads(body_str) if body_str else {}
        except:
            return {}
    
    def _extract_job_id(self, path, query):
        """Extract job_id from path or query"""
        # Check query params (parse_qs returns lists)
        if 'job_id' in query:
            job_id_val = query['job_id']
            if isinstance(job_id_val, list) and job_id_val:
                # Query params may be URL-encoded
                return unquote(job_id_val[0])
            return unquote(job_id_val) if job_id_val else None
        # Try to extract from path: /api/jobs/{job_id}/...
        # Path is already URL-decoded in do_GET/do_POST/do_DELETE
        parts = path.split('/')
        if len(parts) >= 4 and parts[2] == 'jobs':
            return parts[3]
        return None
    
    def _handle_route(self, method, path, query, body):
        """Handle routing logic"""
        try:
            print(f"DEBUG: Method={method}, Path={path}, Query={query}", file=sys.stderr)

            # ------------------------------------------------------------------
            # Job portrait optimization APIs (CN_job_optimizations)
            # ------------------------------------------------------------------
            if path.startswith("/api/jobs/optimizations"):
                # GET /api/jobs/optimizations/count?job_id=...
                if method == "GET" and path.endswith("/count"):
                    job_id = self._extract_job_id(path, query) or (query.get("job_id", [None])[0] if "job_id" in query else None)
                    job_id = unquote(job_id) if job_id else ""
                    base_job_id = get_base_job_id(job_id)
                    count = _count_feedback(base_job_id, include_closed=False)
                    self._send_json_response(200, {"success": True, "data": {"job_id": base_job_id, "count": count}})
                    return

                # GET /api/jobs/optimizations/list?job_id=...
                if method == "GET" and path.endswith("/list"):
                    job_id = self._extract_job_id(path, query) or (query.get("job_id", [None])[0] if "job_id" in query else None)
                    job_id = unquote(job_id) if job_id else ""
                    base_job_id = get_base_job_id(job_id)
                    items = _list_feedback(base_job_id, limit=500, include_closed=False)
                    self._send_json_response(200, {"success": True, "data": items})
                    return

                # POST /api/jobs/optimizations/add
                if method == "POST" and path.endswith("/add"):
                    job_id = get_base_job_id((body.get("job_id") or "").strip())
                    candidate_id = (body.get("candidate_id") or "").strip()
                    conversation_id = (body.get("conversation_id") or "").strip()
                    candidate_name = (body.get("candidate_name") or "").strip()
                    job_applied = (body.get("job_applied") or "").strip()
                    suggestion = (body.get("suggestion") or "").strip()
                    current_analysis = body.get("current_analysis") or {}
                    target_scores = body.get("target_scores") or {}

                    if not job_id:
                        self._send_json_response(400, {"success": False, "error": "job_id is required"})
                        return
                    if not candidate_id:
                        self._send_json_response(400, {"success": False, "error": "candidate_id is required"})
                        return
                    if not conversation_id:
                        self._send_json_response(400, {"success": False, "error": "conversation_id is required"})
                        return
                    if not suggestion:
                        self._send_json_response(400, {"success": False, "error": "suggestion is required"})
                        return

                    # Must provide at least one target score.
                    has_any_score = any(v is not None and v != "" for v in target_scores.values())
                    if not has_any_score:
                        self._send_json_response(400, {"success": False, "error": "at least one target score is required"})
                        return

                    now = _utc_now()
                    item_id = str(uuid.uuid4())
                    record = {
                        "id": _truncate_field(item_id, 64),
                        "feedback_vector": [0.0, 0.0],
                        "job_id": _truncate_field(job_id, 64),
                        "job_applied": _truncate_field(job_applied, 200),
                        "candidate_id": _truncate_field(candidate_id, 64),
                        "conversation_id": _truncate_field(conversation_id, 128),
                        "candidate_name": _truncate_field(candidate_name, 200),
                        "current_analysis": current_analysis or {},
                        "target_scores": target_scores or {},
                        "suggestion": _truncate_field(suggestion, 5000),
                        "status": "open",
                        "created_at": _truncate_field(now, 64),
                        "updated_at": _truncate_field(now, 64),
                    }
                    try:
                        _upsert_feedback(record)
                        self._send_json_response(200, {"success": True, "data": record})
                    except Exception as exc:
                        self._send_json_response(500, {"success": False, "error": str(exc)})
                    return

                # POST /api/jobs/optimizations/update
                if method == "POST" and path.endswith("/update"):
                    item_id = (body.get("id") or "").strip()
                    if not item_id:
                        self._send_json_response(400, {"success": False, "error": "id is required"})
                        return
                    existing = _get_feedback(item_id)
                    if not existing:
                        self._send_json_response(404, {"success": False, "error": "item not found"})
                        return
                    suggestion = (body.get("suggestion") or "").strip()
                    target_scores = body.get("target_scores") or {}
                    if suggestion:
                        existing["suggestion"] = _truncate_field(suggestion, 5000)
                    if target_scores:
                        has_any_score = any(v is not None and v != "" for v in target_scores.values())
                        if not has_any_score:
                            self._send_json_response(400, {"success": False, "error": "at least one target score is required"})
                            return
                        existing["target_scores"] = target_scores
                    existing["updated_at"] = _truncate_field(_utc_now(), 64)
                    try:
                        _upsert_feedback(existing)
                        self._send_json_response(200, {"success": True, "data": existing})
                    except Exception as exc:
                        self._send_json_response(500, {"success": False, "error": str(exc)})
                    return

                # POST /api/jobs/optimizations/generate
                if method == "POST" and path.endswith("/generate"):
                    job_id = get_base_job_id((body.get("job_id") or "").strip())
                    item_ids = body.get("item_ids") or []
                    if not job_id:
                        self._send_json_response(400, {"success": False, "error": "job_id is required"})
                        return
                    if not item_ids:
                        self._send_json_response(400, {"success": False, "error": "item_ids is required"})
                        return
                    current_job = get_job_by_id(job_id)
                    if not current_job:
                        self._send_json_response(404, {"success": False, "error": "job not found"})
                        return
                    feedback_items = []
                    for iid in item_ids:
                        it = _get_feedback(str(iid))
                        if not it:
                            continue
                        if get_base_job_id(it.get("job_id", "")) != job_id:
                            continue
                        feedback_items.append(it)
                    
                    # Check if any items are already closed
                    closed_items = [it for it in feedback_items if it.get("status") == "closed"]
                    if closed_items:
                        first_closed = closed_items[0]
                        ver = first_closed.get("closed_at_job_id") or "unknown"
                        self._send_json_response(400, {
                            "success": False, 
                            "error": f"所选反馈已归档（已用于生成版本 {ver}），无法再次生成。",
                            "code": "FEEDBACK_CLOSED"
                        })
                        return

                    if not feedback_items:
                        self._send_json_response(400, {"success": False, "error": "no valid feedback items"})
                        return
                    try:
                        out = _openai_generate_job_portrait_optimization(current_job, feedback_items)
                        self._send_json_response(200, {"success": True, "data": out})
                    except Exception as exc:
                        self._send_json_response(500, {"success": False, "error": str(exc)})
                    return

                # POST /api/jobs/optimizations/publish
                if method == "POST" and path.endswith("/publish"):
                    job_id = get_base_job_id((body.get("job_id") or "").strip())
                    item_ids = body.get("item_ids") or []
                    job_portrait = body.get("job_portrait") or {}
                    if not job_id:
                        self._send_json_response(400, {"success": False, "error": "job_id is required"})
                        return
                    if not item_ids:
                        self._send_json_response(400, {"success": False, "error": "item_ids is required"})
                        return
                    current_job = get_job_by_id(job_id)
                    if not current_job:
                        self._send_json_response(404, {"success": False, "error": "job not found"})
                        return

                    # Defensive merges: candidate_filters + notification + background must be preserved.
                    merged = {
                        "position": current_job.get("position", ""),
                        "description": job_portrait.get("description", current_job.get("description", "")),
                        "responsibilities": job_portrait.get("responsibilities", current_job.get("responsibilities", "")),
                        "requirements": job_portrait.get("requirements", current_job.get("requirements", "")),
                        "target_profile": job_portrait.get("target_profile", current_job.get("target_profile", "")),
                        "drill_down_questions": job_portrait.get("drill_down_questions", current_job.get("drill_down_questions", "")),
                        "keywords": job_portrait.get("keywords") or current_job.get("keywords") or {"positive": [], "negative": []},
                        "candidate_filters": current_job.get("candidate_filters"),
                        "notification": current_job.get("notification"),
                        "background": current_job.get("background", ""),
                    }
                    # If generator accidentally clears keywords, keep current.
                    kw = merged.get("keywords") or {}
                    if not (kw.get("positive") or kw.get("negative")):
                        merged["keywords"] = current_job.get("keywords") or {"positive": [], "negative": []}

                    try:
                        new_versioned_id = update_job(job_id, **merged)
                        if not new_versioned_id:
                            self._send_json_response(500, {"success": False, "error": "failed to publish job"})
                            return
                        closed = _close_feedback_items(job_id, item_ids, closed_at_job_id=new_versioned_id)
                        updated_job = get_job_by_id(job_id)
                        self._send_json_response(200, {"success": True, "data": {"job": updated_job, "closed": closed}})
                    except Exception as exc:
                        self._send_json_response(500, {"success": False, "error": str(exc)})
                    return
            
            # Route handling
            if method == 'GET' and (path.endswith('/list') or path == '/api/jobs' or '/list' in path):
                # GET /api/jobs/list
                try:
                    jobs = get_all_jobs()
                    self._send_json_response(200, {'success': True, 'data': jobs})
                    return
                except Exception as e:
                    error_msg = str(e)
                    print(f"Error in get_all_jobs: {error_msg}", file=sys.stderr)
                    import traceback
                    traceback.print_exc(file=sys.stderr)
                    self._send_json_response(500, {'success': False, 'error': error_msg})
                    return
            
            elif method == 'POST' and path.endswith('/create'):
                # POST /api/jobs/create
                if not body.get('job_id') or not body.get('position'):
                    self._send_json_response(400, {'success': False, 'error': 'job_id and position are required'})
                    return

                ok, err = _validate_requirements_text(body.get("requirements", "") or "")
                if not ok:
                    self._send_json_response(400, {'success': False, 'error': err})
                    return
                
                base_job_id = get_base_job_id(body['job_id'])
                existing = get_job_by_id(base_job_id)
                if existing:
                    self._send_json_response(400, {'success': False, 'error': f"Job ID '{base_job_id}' already exists"})
                    return
                
                try:
                    if insert_job(**body):
                        new_job = get_job_by_id(base_job_id)
                        self._send_json_response(200, {'success': True, 'data': new_job})
                    else:
                        self._send_json_response(500, {'success': False, 'error': 'Failed to create job'})
                except RuntimeError as e:
                    self._send_json_response(400, {'success': False, 'error': str(e)})
                return
            
            elif method == 'GET' and '/versions' in path:
                # GET /api/jobs/[job_id]/versions
                job_id = self._extract_job_id(path, query)
                if not job_id:
                    self._send_json_response(400, {'success': False, 'error': 'job_id is required'})
                    return
                
                base_job_id = get_base_job_id(job_id)
                versions = get_job_versions(base_job_id)
                self._send_json_response(200, {'success': True, 'data': versions})
                return
            
            elif method == 'POST' and '/switch-version' in path:
                # POST /api/jobs/[job_id]/switch-version
                job_id = self._extract_job_id(path, query)
                version = body.get('version')
                
                if not job_id:
                    self._send_json_response(400, {'success': False, 'error': 'job_id is required'})
                    return
                
                if version is None:
                    self._send_json_response(400, {'success': False, 'error': 'version is required'})
                    return
                
                try:
                    version = int(version)
                except (ValueError, TypeError):
                    self._send_json_response(400, {'success': False, 'error': 'version must be a number'})
                    return
                
                base_job_id = get_base_job_id(job_id)
                if switch_job_version(base_job_id, version):
                    updated_job = get_job_by_id(base_job_id)
                    self._send_json_response(200, {'success': True, 'data': updated_job})
                else:
                    self._send_json_response(404, {'success': False, 'error': f'Version {version} not found'})
                return
            
            elif method == 'DELETE' and '/delete' in path:
                # DELETE /api/jobs/[job_id]/delete
                job_id = self._extract_job_id(path, query)
                version = body.get('version')
                
                if not job_id:
                    self._send_json_response(400, {'success': False, 'error': 'job_id is required'})
                    return
                
                if version is None:
                    self._send_json_response(400, {'success': False, 'error': 'version is required'})
                    return
                
                try:
                    version = int(version)
                except (ValueError, TypeError):
                    self._send_json_response(400, {'success': False, 'error': 'version must be a number'})
                    return
                
                base_job_id = get_base_job_id(job_id)
                all_versions = get_job_versions(base_job_id)
                
                # Allow deletion even if only 1 version left (frontend handles confirmation)
                # No need to prevent it at API level
                
                # Check if the version to delete exists and if it's the current version
                version_to_delete = next((v for v in all_versions if v.get('version') == version), None)
                if not version_to_delete:
                    self._send_json_response(404, {'success': False, 'error': f'Version v{version} not found'})
                    return
                
                is_deleting_current = version_to_delete.get('current', False)
                
                if delete_job_version(base_job_id, version):
                    remaining_versions = get_job_versions(base_job_id)
                    if remaining_versions:
                        # Always ensure there's a current version after deletion
                        current_version = next((v for v in remaining_versions if v.get('current')), None)
                        
                        if not current_version or is_deleting_current:
                            # No current version found, or we deleted the current version
                            if is_deleting_current:
                                # If we deleted the current version N, try to set N-1 as current
                                # If N-1 doesn't exist, set the highest remaining version
                                version_minus_one = next((v for v in remaining_versions if v.get('version') == version - 1), None)
                                if version_minus_one:
                                    # Set N-1 as current
                                    switch_job_version(base_job_id, version - 1)
                                else:
                                    # N-1 doesn't exist, set the highest remaining version as current
                                    remaining_versions_sorted = sorted(remaining_versions, key=lambda v: v.get('version', 0), reverse=True)
                                    if remaining_versions_sorted:
                                        switch_job_version(base_job_id, remaining_versions_sorted[0].get('version'))
                            else:
                                # We deleted a non-current version, but there's no current version
                                # Set the highest remaining version as current
                                remaining_versions_sorted = sorted(remaining_versions, key=lambda v: v.get('version', 0), reverse=True)
                                if remaining_versions_sorted:
                                    switch_job_version(base_job_id, remaining_versions_sorted[0].get('version'))
                        
                        self._send_json_response(200, {'success': True, 'message': f'Version v{version} deleted'})
                    else:
                        # Last version deleted - job is completely removed
                        self._send_json_response(200, {'success': True, 'message': 'Job deleted (last version removed)'})
                else:
                    self._send_json_response(500, {'success': False, 'error': 'Failed to delete version'})
                return
            
            elif method == 'POST' and '/update' in path:
                # POST /api/jobs/[job_id]/update
                job_id = self._extract_job_id(path, query)
                
                if not job_id:
                    self._send_json_response(400, {'success': False, 'error': 'job_id is required'})
                    return
                
                if not body.get('position'):
                    self._send_json_response(400, {'success': False, 'error': 'position is required'})
                    return

                if "requirements" in body:
                    ok, err = _validate_requirements_text(body.get("requirements", "") or "")
                    if not ok:
                        self._send_json_response(400, {'success': False, 'error': err})
                        return
                
                base_job_id = get_base_job_id(job_id)
                new_base_job_id = get_base_job_id(body.get('job_id', job_id))
                
                existing = get_job_by_id(base_job_id)
                if not existing:
                    self._send_json_response(404, {'success': False, 'error': 'Job not found'})
                    return
                
                if new_base_job_id != base_job_id:
                    conflict = get_job_by_id(new_base_job_id)
                    if conflict:
                        self._send_json_response(400, {'success': False, 'error': f"Job ID '{new_base_job_id}' already exists"})
                        return
                
                # Remove job_id from body to avoid conflict with positional argument
                job_data = {k: v for k, v in body.items() if k != 'job_id'}
                try:
                    if update_job(base_job_id, **job_data):
                        updated_job = get_job_by_id(new_base_job_id)
                        self._send_json_response(200, {'success': True, 'data': updated_job})
                    else:
                        self._send_json_response(500, {'success': False, 'error': 'Failed to update job'})
                except RuntimeError as e:
                    self._send_json_response(400, {'success': False, 'error': str(e)})
                return
            
            else:
                # GET /api/jobs/[job_id] - Get specific job
                job_id = self._extract_job_id(path, query)
                if not job_id:
                    self._send_json_response(400, {'success': False, 'error': 'job_id is required'})
                    return
                
                job = get_job_by_id(job_id)
                if not job:
                    self._send_json_response(404, {'success': False, 'error': 'Job not found'})
                    return
                
                self._send_json_response(200, {'success': True, 'data': job})
                return
        
        except Exception as e:
            import traceback
            error_msg = str(e)
            error_type = type(e).__name__
            traceback_str = traceback.format_exc()
            
            print(f"ERROR: {error_type}: {error_msg}", file=sys.stderr)
            print(traceback_str, file=sys.stderr)
            sys.stderr.flush()
            
            self._send_json_response(500, {
                'success': False, 
                'error': error_msg,
                'type': error_type
            })
    
    def do_GET(self):
        """Handle GET requests"""
        path = unquote(self.path.split('?')[0])
        query = self._get_query_params()
        body = {}
        self._handle_route('GET', path, query, body)
    
    def do_POST(self):
        """Handle POST requests"""
        path = unquote(self.path.split('?')[0])
        query = self._get_query_params()
        body = self._get_body()
        self._handle_route('POST', path, query, body)
    
    def do_DELETE(self):
        """Handle DELETE requests"""
        path = unquote(self.path.split('?')[0])
        query = self._get_query_params()
        body = self._get_body()
        self._handle_route('DELETE', path, query, body)
    
    def do_OPTIONS(self):
        """Handle CORS preflight requests"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
