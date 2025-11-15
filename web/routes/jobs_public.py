"""Public standalone job editor route for non-HR managers.

This module provides a simplified interface for updating job descriptions
without requiring access to the full HR management system.
"""

import os
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.jobs_store import (
    get_all_jobs, get_job_by_id, update_job as update_job_store,
    get_base_job_id
)

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

# Simple token-based authentication
# In production, store this in secrets.yaml or environment variable
PUBLIC_JOBS_TOKEN = os.environ.get("PUBLIC_JOBS_TOKEN", "change-me-in-production")


def verify_token(token: Optional[str]) -> bool:
    """Verify the access token.
    
    Args:
        token: Token from query parameter or header
        
    Returns:
        bool: True if token is valid
    """
    if not PUBLIC_JOBS_TOKEN or PUBLIC_JOBS_TOKEN == "change-me-in-production":
        # In development, allow access without token
        return True
    if not token:
        return False
    return token == PUBLIC_JOBS_TOKEN


@router.get("/public", response_class=HTMLResponse)
async def public_jobs_editor(request: Request, token: Optional[str] = Query(None)):
    """Public standalone job editor page for non-HR managers.
    
    Access via: /jobs/public?token=YOUR_TOKEN
    
    This is a simplified interface that allows updating job descriptions
    without access to the full HR management system.
    
    Args:
        request: FastAPI request object
        token: Access token (optional in development)
        
    Returns:
        HTMLResponse: Rendered public jobs editor page
    """
    if not verify_token(token):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing access token. Please provide a valid token."
        )
    
    jobs = get_all_jobs()
    return templates.TemplateResponse("jobs_public.html", {
        "request": request,
        "jobs": jobs,
        "token": token
    })


@router.get("/public/api/list", response_class=JSONResponse)
async def public_api_list_jobs(token: Optional[str] = Query(None)):
    """API endpoint to list all jobs (public access).
    
    Args:
        token: Access token
        
    Returns:
        JSONResponse: List of jobs
    """
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid access token")
    
    jobs = get_all_jobs()
    return JSONResponse(content={"success": True, "data": jobs})


@router.get("/public/api/{job_id}", response_class=JSONResponse)
async def public_api_get_job(job_id: str, token: Optional[str] = Query(None)):
    """API endpoint to get specific job (public access).
    
    Args:
        job_id: Job ID
        token: Access token
        
    Returns:
        JSONResponse: Job data
    """
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid access token")
    
    base_job_id = get_base_job_id(job_id)
    job = get_job_by_id(base_job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JSONResponse(content={"success": True, "data": job})


@router.post("/public/api/{job_id}/update", response_class=JSONResponse)
async def public_api_update_job(job_id: str, request: Request, token: Optional[str] = Query(None)):
    """API endpoint to update job (public access, simplified fields only).
    
    Only allows updating description fields, not keywords, filters, or versioning.
    
    Args:
        job_id: Job ID
        request: FastAPI request object
        token: Access token
        
    Returns:
        JSONResponse: Updated job data
    """
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid access token")
    
    json_data = await request.json()
    
    # Extract only editable fields (description-related)
    position = json_data.get("position", "").strip()
    background = json_data.get("background", "").strip()
    responsibilities = json_data.get("responsibilities", "").strip()
    requirements = json_data.get("requirements", "").strip()
    description = json_data.get("description", "").strip()
    target_profile = json_data.get("target_profile", "").strip()
    
    # Validate required fields
    if not position:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "岗位名称不能为空"}
        )
    
    base_job_id = get_base_job_id(job_id)
    existing_job = get_job_by_id(base_job_id)
    if not existing_job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "岗位未找到"}
        )
    
    # Update only description fields (preserve keywords, filters, etc.)
    updated_job = {
        "position": position,
        "background": background,
        "responsibilities": responsibilities,
        "requirements": requirements,
        "description": description,
        "target_profile": target_profile,
    }
    
    # Update job in Zilliz (creates new version automatically)
    if update_job_store(base_job_id, **updated_job):
        new_current_job = get_job_by_id(base_job_id)
        return JSONResponse(content={"success": True, "data": new_current_job})
    else:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "更新岗位失败"}
        )

