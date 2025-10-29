"""Job profile management routes for web UI."""

from __future__ import annotations

import re
from typing import Set

from fastapi import APIRouter, Query, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.config import settings
from src.jobs_store import jobs_store

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


def load_jobs():
    """Load jobs from Zilliz Cloud."""
    return jobs_store.get_all_jobs()


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
    
    # Extract drill down questions as string
    drill_down_questions = json_data.get("drill_down_questions", "").strip()
    
    # Validate required fields
    if not job_id or not position:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "岗位ID和岗位名称不能为空"}
        )
    
    # Check if job_id already exists
    existing_job = jobs_store.get_job_by_id(job_id)
    if existing_job:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"岗位ID '{job_id}' 已存在"}
        )
    
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
        "drill_down_questions": drill_down_questions
    }
    
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
    
    # Insert job into Zilliz
    if jobs_store.insert_job(**new_job):
        return JSONResponse(content={"success": True, "data": new_job})
    else:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "创建岗位失败"}
        )


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
    
    # Extract drill down questions as string
    drill_down_questions = json_data.get("drill_down_questions", "").strip()
    
    # Validate required fields
    if not new_job_id or not position:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "岗位ID和岗位名称不能为空"}
        )
    
    # Check if job exists
    existing_job = jobs_store.get_job_by_id(job_id)
    if not existing_job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "岗位未找到"}
        )
    
    # Check if new job_id conflicts with existing jobs (excluding current job)
    if new_job_id != job_id:
        existing_job_with_new_id = jobs_store.get_job_by_id(new_job_id)
        if existing_job_with_new_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"岗位ID '{new_job_id}' 已存在"}
            )
    
    # Update job data
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
        },
        "drill_down_questions": drill_down_questions
    }
    
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
    
    # Update job in Zilliz
    if jobs_store.update_job(job_id, **updated_job):
        return JSONResponse(content={"success": True, "data": updated_job})
    else:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "更新岗位失败"}
        )


@router.delete("/{job_id}/delete", response_class=JSONResponse)
async def delete_job(job_id: str):
    """Delete job."""
    # Check if job exists
    existing_job = jobs_store.get_job_by_id(job_id)
    if not existing_job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "岗位不存在"}
        )
    
    # Delete job from Zilliz
    if jobs_store.delete_job(job_id):
        return JSONResponse(
            content={"success": True, "message": f"岗位 '{existing_job.get('position', '')}' 已删除"}
        )
    else:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "删除岗位失败"}
        )


@router.get("/api/list", response_class=JSONResponse)
async def api_list_jobs():
    """API endpoint to list all jobs."""
    jobs = load_jobs()
    return JSONResponse(content={"success": True, "data": jobs})


@router.get("/api/{job_id}", response_class=JSONResponse)
async def api_get_job(job_id: str):
    """API endpoint to get specific job."""
    job = jobs_store.get_job_by_id(job_id)
    
    if not job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "岗位不存在"}
        )
    
    return JSONResponse(content={"success": True, "data": job})