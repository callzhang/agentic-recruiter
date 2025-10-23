"""Job profile management routes for web UI."""

from __future__ import annotations

from pathlib import Path
import yaml
import re
from typing import Set

from fastapi import APIRouter, Query, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


def load_jobs():
    """Load jobs from config file."""
    path = Path(settings.BOSS_CRITERIA_PATH)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("roles"), list):
        return data["roles"]
    return []


def save_jobs(jobs):
    """Save jobs to config file."""
    path = Path(settings.BOSS_CRITERIA_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    data = {"roles": jobs}
    path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")


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
    
    # Validate required fields
    if not job_id or not position:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "岗位ID和岗位名称不能为空"}
        )
    
    # Load existing jobs
    jobs = load_jobs()
    existing_ids = {job.get("id", "") for job in jobs if job.get("id")}
    
    # Check if job_id already exists
    if job_id in existing_ids:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"岗位ID '{job_id}' 已存在"}
        )
    
    # Create new job
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
        }
    }
    
    # Add extra configuration if provided
    if extra_yaml:
        try:
            extra_data = yaml.safe_load(extra_yaml)
            if extra_data:
                new_job.update(extra_data)
        except yaml.YAMLError as e:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"YAML格式错误: {str(e)}"}
            )
    
    jobs.append(new_job)
    save_jobs(jobs)
    
    return JSONResponse(content={"success": True, "data": new_job})


@router.post("/{job_id}/update", response_class=JSONResponse)
async def update_job(job_id: str, request: Request):
    """Update existing job."""
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
    
    # Validate required fields
    if not new_job_id or not position:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "岗位ID和岗位名称不能为空"}
        )
    
    # Load existing jobs
    jobs = load_jobs()
    job_index = next((i for i, j in enumerate(jobs) if j.get("id") == job_id), None)
    
    if job_index is None:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "岗位未找到"}
        )
    
    # Check if new job_id conflicts with existing jobs (excluding current job)
    if new_job_id != job_id:
        existing_ids = {j.get("id", "") for i, j in enumerate(jobs) if i != job_index}
        if new_job_id in existing_ids:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"岗位ID '{new_job_id}' 已存在"}
            )
    
    # Update job
    updated_job = {
        "id": new_job_id,
        "position": position,
        "background": background,
        "responsibilities": responsibilities,
        "requirements": requirements,
        "description": description,
        "target_profile": target_profile,
        "keywords": {
            "positive": positive_keywords,
            "negative": negative_keywords
        }
    }
    
    # Add extra configuration if provided
    if extra_yaml:
        try:
            extra_data = yaml.safe_load(extra_yaml)
            if extra_data:
                updated_job.update(extra_data)
        except yaml.YAMLError as e:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"YAML格式错误: {str(e)}"}
            )
    
    jobs[job_index] = updated_job
    save_jobs(jobs)
    
    return JSONResponse(content={"success": True, "data": updated_job})


@router.delete("/{job_id}/delete", response_class=JSONResponse)
async def delete_job(job_id: str):
    """Delete job."""
    jobs = load_jobs()
    
    job_to_delete = next((j for j in jobs if j.get("id") == job_id), None)
    if not job_to_delete:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "岗位不存在"}
        )
    
    updated_jobs = [j for j in jobs if j.get("id") != job_id]
    
    save_jobs(updated_jobs)
    
    return JSONResponse(
        content={"success": True, "message": f"岗位 '{job_to_delete.get('position', '')}' 已删除"}
    )


@router.get("/api/list", response_class=JSONResponse)
async def api_list_jobs():
    """API endpoint to list all jobs."""
    jobs = load_jobs()
    return JSONResponse(content={"success": True, "data": jobs})


@router.get("/api/{job_id}", response_class=JSONResponse)
async def api_get_job(job_id: str):
    """API endpoint to get specific job."""
    jobs = load_jobs()
    job = next((j for j in jobs if j.get("id") == job_id), None)
    
    if not job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "岗位不存在"}
        )
    
    return JSONResponse(content={"success": True, "data": job})