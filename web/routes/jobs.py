"""Job profile management routes for web UI."""

import asyncio
import json
import re
from typing import Set

from fastapi import APIRouter, Query, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.global_logger import get_logger
from src.jobs_store import (
    get_all_jobs, get_job_by_id, insert_job, update_job as update_job_store,
    delete_job as delete_job_store, delete_job_version,
    get_job_versions, switch_job_version, get_base_job_id
)

logger = get_logger()
router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


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
    
    # Extract notification config (can be provided directly or built from dingtalk_url/dingtalk_secret)
    notification = json_data.get("notification")
    if not notification:
        dingtalk_url = json_data.get("dingtalk_url", "").strip()
        dingtalk_secret = json_data.get("dingtalk_secret", "").strip()
        if dingtalk_url and dingtalk_secret:
            notification = {"url": dingtalk_url, "secret": dingtalk_secret}
    
    # Validate required fields
    if not new_job_id or not position:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "岗位ID和岗位名称不能为空"}
        )
    
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