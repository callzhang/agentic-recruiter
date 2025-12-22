"""Job profile management routes for web UI."""

import asyncio
import difflib
import json
import re
from typing import Any, Optional, Set

from fastapi import APIRouter, Query, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.global_logger import get_logger
from src.jobs_store import (
    get_all_jobs, get_job_by_id, insert_job, update_job as update_job_store,
    delete_job as delete_job_store, delete_job_version,
    get_job_versions, switch_job_version, get_base_job_id
)
from src.job_optimization_feedback_store import (
    TargetScores,
    count_feedback,
    count_feedback_advanced,
    close_feedback_items,
    delete_feedback,
    get_feedback,
    list_feedback,
    list_feedback_advanced,
    upsert_feedback,
)
from src.assistant_utils import _openai_client
from src.config import get_openai_config
from src.prompts.assistant_actions_prompts import ACTION_PROMPTS as ASSISTANT_ACTION_PROMPTS, AnalysisSchema
from src.prompts.job_portrait_optimization_prompts import (
    JOB_PORTRAIT_OPTIMIZATION_PROMPT,
    JobPortraitOptimizationSchema,
)

logger = get_logger()
router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

def _validate_requirements_scorecard(requirements: str) -> tuple[bool, str]:
    text = (requirements or "").strip()
    if not text:
        return False, "评分标准不能为空"
    if len(text.encode("utf-8")) > 5000:
        return False, "评分标准过长（超过 5000 字节），请精简"
    return True, ""

def _validate_notification(notification: dict | None) -> tuple[bool, str]:
    if not isinstance(notification, dict):
        return False, "请配置钉钉机器人 Webhook URL 和 Secret（必填）"
    url = (notification.get("url") or "").strip()
    secret = (notification.get("secret") or "").strip()
    if not url or not secret:
        return False, "请配置钉钉机器人 Webhook URL 和 Secret（必填）"
    return True, ""

def _normalize_keywords(value: Any) -> dict[str, list[str]]:
    """Normalize keywords to {positive: [...], negative: [...]}.

    This keeps backward compatibility with older job portraits where keywords
    may be stored as a list of strings.
    """
    def _clean_list(v: Any) -> list[str]:
        if not isinstance(v, list):
            return []
        out: list[str] = []
        for item in v:
            s = str(item).strip()
            if s:
                out.append(s)
        return out

    if isinstance(value, list):
        return {"positive": _clean_list(value), "negative": []}
    if isinstance(value, str):
        lines = [ln.strip() for ln in value.splitlines() if ln.strip()]
        return {"positive": lines, "negative": []}
    if isinstance(value, dict):
        # Standard shape: {positive: [...], negative: [...]}
        if "positive" in value or "negative" in value:
            return {
                "positive": _clean_list(value.get("positive")),
                "negative": _clean_list(value.get("negative")),
            }
        # Fallback shape: try common legacy key names.
        if "keywords" in value:
            return {"positive": _clean_list(value.get("keywords")), "negative": []}
    return {"positive": [], "negative": []}

def _extract_job_portrait(job: dict[str, Any]) -> dict[str, Any]:
    """Extract the editable job portrait payload (excluding ids/version/notification)."""
    if not isinstance(job, dict):
        return {}
    return {
        "position": job.get("position", "") or "",
        "description": job.get("description", "") or "",
        "responsibilities": job.get("responsibilities", "") or "",
        "requirements": job.get("requirements", "") or "",
        "target_profile": job.get("target_profile", "") or "",
        "keywords": _normalize_keywords(job.get("keywords")),
        "drill_down_questions": job.get("drill_down_questions", "") or "",
        # For OpenAI strict JSON schema: represent candidate_filters as JSON string or null.
        "candidate_filters": (
            json.dumps(job.get("candidate_filters"), ensure_ascii=False, indent=2)
            if job.get("candidate_filters") is not None
            else None
        ),
    }


def _clamp_score(value: Any) -> Optional[int]:
    """Best-effort parse and clamp a score to [1, 10]."""
    if value is None or value == "":
        return None
    try:
        v = int(value)
    except Exception:
        return None
    return max(1, min(10, v))


class AddOptimizationFeedbackRequest(BaseModel):
    job_id: str = Field(description="base_job_id")
    candidate_id: str
    conversation_id: str
    candidate_name: str = ""
    job_applied: str = ""
    current_analysis: dict[str, Any] = Field(default_factory=dict)
    target_scores: dict[str, Any] = Field(default_factory=dict)
    suggestion: str


class UpdateOptimizationFeedbackRequest(BaseModel):
    id: str
    target_scores: dict[str, Any] = Field(default_factory=dict)
    suggestion: str


class GenerateOptimizationRequest(BaseModel):
    job_id: str = Field(description="base_job_id")
    item_ids: list[str] = Field(default_factory=list)


class PublishOptimizedPortraitRequest(BaseModel):
    job_id: str = Field(description="base_job_id")
    job_portrait: dict[str, Any] = Field(default_factory=dict)
    item_ids: list[str] = Field(default_factory=list, description="optimization feedback ids to close after publish")


def load_jobs():
    """Load jobs from Zilliz Cloud."""
    return get_all_jobs()


def generate_job_id(position: str) -> str:
    """Generate a job ID from position name."""
    # Convert to lowercase and replace non-alphanumeric characters with underscores
    job_id = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '_', position.lower())
    # Remove multiple consecutive underscores
    job_id = re.sub(r'_+', '_', job_id)
    # Remove leading/trailing underscores
    job_id = job_id.strip('_')
    return job_id


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def jobs_page(request: Request):
    """Main jobs management page."""
    # Load jobs (database query, no browser lock needed)
    jobs = load_jobs()
    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "jobs": jobs
    })

@router.get("/optimize", response_class=HTMLResponse)
async def jobs_optimize_page(
    request: Request,
    job_id: str = Query(..., description="base_job_id"),
):
    """Job portrait optimization page for a given job."""
    base_job_id = get_base_job_id(job_id)
    job = get_job_by_id(base_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")

    items = list_feedback(base_job_id)
    return templates.TemplateResponse(
        "job_optimize.html",
        {
            "request": request,
            "base_job_id": base_job_id,
            "job": job,
            "items": items,
        },
    )


@router.get("/optimize/generate", response_class=HTMLResponse)
async def jobs_optimize_generate_page(
    request: Request,
    job_id: str = Query(..., description="base_job_id"),
    item_ids: str = Query("", description="comma separated optimization item ids"),
):
    """Generation page with progress bar for creating an optimized job portrait."""
    base_job_id = get_base_job_id(job_id)
    job = get_job_by_id(base_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")

    ids = [s.strip() for s in (item_ids or "").split(",") if s and s.strip()]
    selected_items = []
    for item_id in ids[:20]:
        it = get_feedback(item_id)
        if it and it.get("job_id") == base_job_id:
            selected_items.append(it)

    return templates.TemplateResponse(
        "job_optimize_generate.html",
        {
            "request": request,
            "base_job_id": base_job_id,
            "job": job,
            "item_ids": ids,
            "items": selected_items,
        },
    )


@router.post("/create", response_class=JSONResponse)
async def create_job(request: Request):
    """Create new job."""
    json_data = await request.json()
    
    job_id = json_data.get("job_id", "").strip()
    position = json_data.get("position", "").strip()
    background = json_data.get("background", "").strip()
    responsibilities = json_data.get("responsibilities", "").strip()
    requirements = json_data.get("requirements", "").strip()
    description = json_data.get("description", "").strip()
    target_profile = json_data.get("target_profile", "").strip()
    extra_yaml = json_data.get("extra_yaml", "").strip()
    
    # Extract keywords from JSON
    keywords = json_data.get("keywords", {})
    positive_keywords = keywords.get("positive", [])
    negative_keywords = keywords.get("negative", [])
    
    # Extract drill down questions as string
    drill_down_questions = json_data.get("drill_down_questions", "").strip()
    
    # Validate required fields
    if not job_id or not position:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "岗位ID和岗位名称不能为空"}
        )

    ok, err = _validate_requirements_scorecard(requirements)
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "error": err})
    
    # Check if job_id already exists (database query, no browser lock needed)
    existing_job = get_job_by_id(job_id)
    if existing_job:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"岗位ID '{job_id}' 已存在"}
        )
    
    # Extract candidate filters from JSON
    candidate_filters = json_data.get("candidate_filters")
    
    # Extract notification config (can be provided directly or built from dingtalk_url/dingtalk_secret)
    notification = json_data.get("notification")
    if not notification:
        dingtalk_url = json_data.get("dingtalk_url", "").strip()
        dingtalk_secret = json_data.get("dingtalk_secret", "").strip()
        if dingtalk_url and dingtalk_secret:
            notification = {"url": dingtalk_url, "secret": dingtalk_secret}

    ok, err = _validate_notification(notification)
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "error": err})
    
    # Create new job data
    new_job = {
        "id": job_id,
        "position": position,
        "background": background,
        "responsibilities": responsibilities,
        "requirements": requirements,
        "description": description,
        "target_profile": target_profile,
        "keywords": {
            "positive": positive_keywords,
            "negative": negative_keywords
        },
        "drill_down_questions": drill_down_questions,
        "candidate_filters": candidate_filters
    }
    
    # Add notification if provided
    if notification:
        new_job["notification"] = notification
    
    # Add extra configuration if provided
    if extra_yaml:
        try:
            import yaml
            extra_data = yaml.safe_load(extra_yaml)
            if extra_data:
                new_job.update(extra_data)
        except yaml.YAMLError as e:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"YAML格式错误: {str(e)}"}
            )
    
    # Insert job into Zilliz (database operation, no browser lock needed)
    if insert_job(**new_job):
        return JSONResponse(content={"success": True, "data": new_job})
    else:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "创建岗位失败"}
        )


@router.post("/{job_id}/update", response_class=JSONResponse)
async def update_job(job_id: str, request: Request):
    """Update existing job (creates new version automatically)."""
    json_data = await request.json()
    
    new_job_id = json_data.get("job_id", "").strip()
    position = json_data.get("position", "").strip()
    background = json_data.get("background", "").strip()
    responsibilities = json_data.get("responsibilities", "").strip()
    requirements = json_data.get("requirements", "").strip()
    description = json_data.get("description", "").strip()
    target_profile = json_data.get("target_profile", "").strip()
    extra_yaml = json_data.get("extra_yaml", "").strip()
    
    # Extract keywords from JSON
    keywords = json_data.get("keywords", {})
    positive_keywords = keywords.get("positive", [])
    negative_keywords = keywords.get("negative", [])
    
    # Extract drill down questions as string
    drill_down_questions = json_data.get("drill_down_questions", "").strip()
    
    # Extract candidate filters from JSON
    candidate_filters = json_data.get("candidate_filters")
    
    # Extract status and metadata
    status = json_data.get("status", "").strip()
    metadata = json_data.get("metadata")  # metadata can be dict or None
    
    # Extract notification config (can be provided directly or built from dingtalk_url/dingtalk_secret)
    notification = json_data.get("notification")
    if not notification:
        dingtalk_url = json_data.get("dingtalk_url", "").strip()
        dingtalk_secret = json_data.get("dingtalk_secret", "").strip()
        if dingtalk_url and dingtalk_secret:
            notification = {"url": dingtalk_url, "secret": dingtalk_secret}

    ok, err = _validate_notification(notification)
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "error": err})
    
    # Validate required fields
    if not new_job_id or not position:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "岗位ID和岗位名称不能为空"}
        )

    ok, err = _validate_requirements_scorecard(requirements)
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "error": err})
    
    # Extract base job_id from path parameter (remove _vN suffix if present)
    base_job_id = get_base_job_id(job_id)
    
    # Extract base job_id from new_job_id (remove _vN suffix if present)
    new_base_job_id = get_base_job_id(new_job_id)
    
    # Check if job exists (database query, no browser lock needed)
    existing_job = get_job_by_id(base_job_id)
    if not existing_job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "岗位未找到"}
        )
    
    # Check if new base_job_id conflicts with existing jobs (excluding current job)
    if new_base_job_id != base_job_id:
        existing_job_with_new_id = get_job_by_id(new_base_job_id)
        if existing_job_with_new_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"岗位ID '{new_base_job_id}' 已存在"}
            )
    
    # Update job data
    updated_job = {
        "id": new_base_job_id,  # Use base job_id (without version suffix)
        "position": position,
        "background": background,
        "responsibilities": responsibilities,
        "requirements": requirements,
        "description": description,
        "target_profile": target_profile,
        "keywords": {
            "positive": positive_keywords,
            "negative": negative_keywords
        },
        "drill_down_questions": drill_down_questions,
        "candidate_filters": candidate_filters
    }
    
    # Add status if provided
    if status:
        updated_job["status"] = status
    
    # Add metadata if provided
    if metadata is not None:
        updated_job["metadata"] = metadata
    
    # Add notification if provided
    if notification:
        updated_job["notification"] = notification
    
    # Add extra configuration if provided
    if extra_yaml:
        try:
            import yaml
            extra_data = yaml.safe_load(extra_yaml)
            if extra_data:
                updated_job.update(extra_data)
        except yaml.YAMLError as e:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"YAML格式错误: {str(e)}"}
            )
    
    # Remove 'id' field from updated_job as update_job() doesn't expect it
    # (job_id is passed as the first positional argument)
    updated_job.pop("id", None)
    
    # Update job in Zilliz (creates new version automatically) (database operation, no browser lock needed)
    if update_job_store(base_job_id, **updated_job):
        # Return the new current version
        new_current_job = get_job_by_id(new_base_job_id)
        return JSONResponse(content={"success": True, "data": new_current_job})
    else:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "更新岗位失败"}
        )


@router.delete("/{job_id}/delete", response_class=JSONResponse)
async def delete_job(job_id: str, request: Request):
    """Delete a specific version of a job.
    
    Args:
        job_id: Base job ID (without version suffix)
    """
    # Extract base job_id (remove _vN suffix if present)
    base_job_id = get_base_job_id(job_id)
    
    # Get version from request body
    version = None
    try:
        body = await request.body()
        if body:
            json_data = json.loads(body)
            version = json_data.get("version")
    except Exception:
        version = None
    
    if version is None:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "版本号不能为空"}
        )
    
    if not isinstance(version, int):
        try:
            version = int(version)
        except (ValueError, TypeError):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "版本号必须是整数"}
            )
    
    # Check if job exists (database query, no browser lock needed)
    existing_job = get_job_by_id(base_job_id)
    if not existing_job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "岗位不存在"}
        )
    
    # Get all versions (allow deletion even if only 1 version left - frontend handles confirmation)
    # Database query, no browser lock needed
    all_versions = get_job_versions(base_job_id)
    
    # Check if the version exists
    version_exists = any(v.get("version") == version for v in all_versions)
    if not version_exists:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"版本 v{version} 不存在"}
        )
    
    # Check if the version to delete is the current one
    version_to_delete = next((v for v in all_versions if v.get("version") == version), None)
    if not version_to_delete:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"版本 v{version} 不存在"}
        )
    
    is_deleting_current = version_to_delete.get("current", False)
    
    # Delete the specific version (database operation, no browser lock needed)
    if delete_job_version(base_job_id, version):
        remaining_versions = get_job_versions(base_job_id)
        if remaining_versions:
            # Always ensure there's a current version after deletion
            current_version = next((v for v in remaining_versions if v.get("current")), None)
            
            if not current_version or is_deleting_current:
                # No current version found, or we deleted the current version
                if is_deleting_current:
                    # If we deleted the current version N, try to set N-1 as current
                    # If N-1 doesn't exist, set the highest remaining version
                    version_minus_one = next((v for v in remaining_versions if v.get("version") == version - 1), None)
                    if version_minus_one:
                        # Set N-1 as current
                        switch_job_version(base_job_id, version - 1)
                    else:
                        # N-1 doesn't exist, set the highest remaining version as current
                        remaining_versions_sorted = sorted(remaining_versions, key=lambda v: v.get("version", 0), reverse=True)
                        if remaining_versions_sorted:
                            switch_job_version(base_job_id, remaining_versions_sorted[0].get("version"))
                else:
                    # We deleted a non-current version, but there's no current version
                    # Set the highest remaining version as current
                    remaining_versions_sorted = sorted(remaining_versions, key=lambda v: v.get("version", 0), reverse=True)
                    if remaining_versions_sorted:
                        await asyncio.to_thread(switch_job_version, base_job_id, remaining_versions_sorted[0].get("version"))
            
            return JSONResponse(
                content={"success": True, "message": f"版本 v{version} 已删除"}
            )
        else:
            # Last version deleted - job is completely removed
            return JSONResponse(
                content={"success": True, "message": "岗位已删除 (最后版本已移除)"}
            )
    else:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "删除版本失败"}
        )


@router.get("/list-simple", response_class=HTMLResponse)
async def list_jobs_simple():
    """Get jobs as HTML options for select."""
    # Load jobs (database query, no browser lock needed)
    jobs = load_jobs()
    
    if not jobs:
        return HTMLResponse(content='<option>无岗位</option>')
    
    html = ""
    for job in jobs:
        job_id = job.get("job_id") or job.get("id", "")
        position = job.get("position", "未知")
        html += f'<option value="{job_id}" data-title="{position}">{position}</option>'
    
    return HTMLResponse(content=html)


@router.get("/api/list", response_class=JSONResponse)
async def api_list_jobs():
    """API endpoint to list all jobs."""
    # Load jobs (database query, no browser lock needed)
    jobs = load_jobs()
    return JSONResponse(content={"success": True, "data": jobs})


@router.get("/api/{job_id}", response_class=JSONResponse)
async def api_get_job(job_id: str):
    """API endpoint to get specific job (returns current version)."""
    # Extract base job_id (remove _vN suffix if present) - pure function, very fast
    base_job_id = get_base_job_id(job_id)
    
    # Get job (database query, no browser lock needed)
    job = get_job_by_id(base_job_id)
    
    if not job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "岗位不存在"}
        )
    
    return JSONResponse(content={"success": True, "data": job})


@router.get("/{job_id}/versions", response_class=JSONResponse)
async def get_job_versions_endpoint(job_id: str):
    """Get all versions of a job.
    
    Args:
        job_id: Job ID (can be base_job_id or versioned job_id)
    """
    # Extract base job_id (remove _vN suffix if present)
    base_job_id = get_base_job_id(job_id)
    # Get job versions (database query, no browser lock needed)
    versions = get_job_versions(base_job_id)
    
    return JSONResponse(content={"success": True, "data": versions})


@router.post("/{job_id}/switch-version", response_class=JSONResponse)
async def switch_job_version_endpoint(job_id: str, request: Request):
    """Switch the current version of a job.
    
    Args:
        job_id: Job ID (can be base_job_id or versioned job_id)
    """
    # Extract base job_id (remove _vN suffix if present)
    base_job_id = get_base_job_id(job_id)
    
    json_data = await request.json()
    version = json_data.get("version")
    
    if version is None:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "版本号不能为空"}
        )
    
    if not isinstance(version, int):
        try:
            version = int(version)
        except (ValueError, TypeError):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "版本号必须是整数"}
            )
    
    # Switch job version (database operation, no browser lock needed)
    if switch_job_version(base_job_id, version):
        # Return updated job data
        updated_job = get_job_by_id(base_job_id)
        return JSONResponse(content={"success": True, "data": updated_job})
    else:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"版本 {version} 不存在"}
        )


@router.get("/api/optimizations/count", response_class=JSONResponse)
async def api_optimization_count(job_id: str = Query(..., description="base_job_id")):
    """Return optimization feedback count for a job."""
    base_job_id = get_base_job_id(job_id)
    include_closed = False
    return JSONResponse(
        content={
            "success": True,
            "data": {"job_id": base_job_id, "count": count_feedback_advanced(base_job_id, include_closed=include_closed)},
        }
    )


@router.get("/api/optimizations/list", response_class=JSONResponse)
async def api_optimization_list(job_id: str = Query(..., description="base_job_id")):
    """List optimization feedback items for a job (most recent first)."""
    base_job_id = get_base_job_id(job_id)
    include_closed = False
    return JSONResponse(content={"success": True, "data": list_feedback_advanced(base_job_id, include_closed=include_closed)})


@router.post("/api/optimizations/add", response_class=JSONResponse)
async def api_optimization_add(payload: AddOptimizationFeedbackRequest):
    """Add a new optimization feedback item."""
    base_job_id = get_base_job_id(payload.job_id)
    if not get_job_by_id(base_job_id):
        return JSONResponse(status_code=404, content={"success": False, "error": "岗位不存在"})

    scores = TargetScores.from_dict(payload.target_scores or {})
    # Clamp to 1-10 (if provided)
    scores = TargetScores(
        overall=_clamp_score(scores.overall),
        skill=_clamp_score(scores.skill),
        background=_clamp_score(scores.background),
        startup_fit=_clamp_score(scores.startup_fit),
    )

    try:
        item = upsert_feedback(
            item_id=None,
            job_id=base_job_id,
            candidate_id=payload.candidate_id,
            conversation_id=payload.conversation_id,
            candidate_name=payload.candidate_name,
            job_applied=payload.job_applied,
            current_analysis=payload.current_analysis or {},
            suggestion=payload.suggestion,
            target_scores=scores,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})

    return JSONResponse(content={"success": True, "data": item})


@router.post("/api/optimizations/update", response_class=JSONResponse)
async def api_optimization_update(payload: UpdateOptimizationFeedbackRequest):
    """Update an existing optimization feedback item."""
    existing = get_feedback(payload.id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "记录不存在"})

    scores = TargetScores.from_dict(payload.target_scores or {})
    scores = TargetScores(
        overall=_clamp_score(scores.overall),
        skill=_clamp_score(scores.skill),
        background=_clamp_score(scores.background),
        startup_fit=_clamp_score(scores.startup_fit),
    )

    try:
        item = upsert_feedback(
            item_id=payload.id,
            job_id=existing.get("job_id") or "",
            candidate_id=existing.get("candidate_id") or "",
            conversation_id=existing.get("conversation_id") or "",
            candidate_name=existing.get("candidate_name") or "",
            job_applied=existing.get("job_applied") or "",
            current_analysis=existing.get("current_analysis") or {},
            suggestion=payload.suggestion,
            target_scores=scores,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})

    return JSONResponse(content={"success": True, "data": item})


@router.delete("/api/optimizations/{item_id}", response_class=JSONResponse)
async def api_optimization_delete(item_id: str):
    """Delete an optimization feedback item."""
    ok = delete_feedback(item_id)
    return JSONResponse(content={"success": ok})


@router.post("/api/optimizations/generate", response_class=JSONResponse)
async def api_optimization_generate(payload: GenerateOptimizationRequest):
    """Generate an optimized job portrait using GPT-5.2 (Responses API parse)."""
    base_job_id = get_base_job_id(payload.job_id)
    job = get_job_by_id(base_job_id)
    if not job:
        return JSONResponse(status_code=404, content={"success": False, "error": "岗位不存在"})

    items = []
    for item_id in payload.item_ids[:20]:
        it = get_feedback(item_id)
        if it and it.get("job_id") == base_job_id:
            items.append(it)
    if not items:
        return JSONResponse(status_code=400, content={"success": False, "error": "请先选择要用于优化的候选人反馈"})

    current_portrait = _extract_job_portrait(job)
    # Ensure position exists and stays stable
    if not current_portrait.get("position"):
        current_portrait["position"] = job.get("position", "") or ""

    openai_config = get_openai_config()
    model = openai_config.get("model") or "gpt-5.2"

    response = _openai_client.responses.parse(
        model=model,
        instructions=JOB_PORTRAIT_OPTIMIZATION_PROMPT,
        input=json.dumps(
            {
                "current_job_portrait": current_portrait,
                "feedback_items": items,
                "downstream_usage": {
                    "purpose": "ANALYZE_ACTION",
                    "prompt": ASSISTANT_ACTION_PROMPTS.get("ANALYZE_ACTION", ""),
                    "output_schema": AnalysisSchema.model_json_schema(),
                },
            },
            ensure_ascii=False,
        ),
        text_format=JobPortraitOptimizationSchema,
        tools=[],
    )
    result = response.output_parsed.model_dump()
    generated_portrait = (result or {}).get("job_portrait") or {}
    diff_text = "\n".join(
        difflib.unified_diff(
            json.dumps(current_portrait, ensure_ascii=False, indent=2, sort_keys=True).splitlines(),
            json.dumps(generated_portrait, ensure_ascii=False, indent=2, sort_keys=True).splitlines(),
            fromfile="current_job_portrait",
            tofile="generated_job_portrait",
            lineterm="",
        )
    )
    return JSONResponse(
        content={
            "success": True,
            "data": result,
            "current_job_portrait": current_portrait,
            "diff": diff_text,
        }
    )


@router.post("/api/optimizations/publish", response_class=JSONResponse)
async def api_optimization_publish(payload: PublishOptimizedPortraitRequest):
    """Publish the generated (or manually edited) job portrait as a new job version."""
    base_job_id = get_base_job_id(payload.job_id)
    current_job = get_job_by_id(base_job_id)
    if not current_job:
        return JSONResponse(status_code=404, content={"success": False, "error": "岗位不存在"})

    portrait = payload.job_portrait or {}
    # Keep position immutable (use current job position if missing or changed)
    portrait["position"] = current_job.get("position", "") or portrait.get("position", "")

    # candidate_filters is a BOSS system/HR-maintained filter: always inherit from the current job.
    portrait["candidate_filters"] = current_job.get("candidate_filters")

    # Normalize/merge keywords to prevent accidental data loss.
    current_keywords = _normalize_keywords(current_job.get("keywords"))
    incoming_keywords = None
    if "keywords" in portrait:
        incoming_keywords = _normalize_keywords(portrait.get("keywords"))
    if incoming_keywords is None:
        portrait["keywords"] = current_keywords
    else:
        incoming_empty = not (incoming_keywords.get("positive") or incoming_keywords.get("negative"))
        current_nonempty = bool(current_keywords.get("positive") or current_keywords.get("negative"))
        # Guardrail: if the publish payload would wipe keywords entirely, keep existing keywords.
        portrait["keywords"] = current_keywords if (incoming_empty and current_nonempty) else incoming_keywords

    ok, err = _validate_requirements_scorecard(str(portrait.get("requirements", "")))
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "error": err})

    # Preserve required notification config.
    notification = current_job.get("notification")
    ok, err = _validate_notification(notification)
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "error": err})
    portrait["notification"] = notification

    # Filter to allowed fields for update_job_store (it accepts partial updates).
    allowed_fields: set[str] = {
        "position",
        "description",
        "responsibilities",
        "requirements",
        "target_profile",
        "keywords",
        "drill_down_questions",
        "candidate_filters",
        "notification",
    }
    update_payload = {k: v for k, v in portrait.items() if k in allowed_fields}

    if not update_job_store(base_job_id, **update_payload):
        return JSONResponse(status_code=500, content={"success": False, "error": "发布失败（创建新版本失败）"})

    # Close selected optimization feedback items so they won't show up next time.
    if payload.item_ids:
        close_feedback_items(base_job_id, payload.item_ids)

    new_current_job = get_job_by_id(base_job_id)
    return JSONResponse(content={"success": True, "data": new_current_job})
