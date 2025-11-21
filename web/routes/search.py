"""Data search routes for web UI.
Allows searching candidates by name and job_applied for viewing by other colleagues.
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from src.candidate_store import get_candidates, get_candidate_by_dict
from src.jobs_store import get_all_jobs, get_job_by_id as get_job_by_id_from_store
from src.global_logger import logger

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def search_page(request: Request):
    """Main search page with form to search candidates by name and job."""
    # Load all jobs for the dropdown
    jobs = get_all_jobs()
    # Extract unique job positions for dropdown
    job_positions = sorted(set([job.get("position", "") for job in jobs if job.get("position")]))
    
    return templates.TemplateResponse("search.html", {
        "request": request,
        "jobs": jobs,
        "job_positions": job_positions,
    })


@router.get("/query", response_class=HTMLResponse)
async def search_candidates(
    request: Request,
    name: str = Query(..., description="Candidate name to search"),
    job_applied: str = Query(..., description="Job position filter"),
):
    """Search for candidates by name and job_applied, return candidate detail view."""
    if not name or not name.strip():
        return HTMLResponse(
            content='<div class="text-center text-red-500 py-12">请输入候选人姓名</div>',
            status_code=400
        )
    
    if not job_applied or not job_applied.strip():
        return HTMLResponse(
            content='<div class="text-center text-red-500 py-12">请选择岗位</div>',
            status_code=400
        )
    
    # Search candidates by name and job_applied
    candidates = get_candidates(
        names=[name.strip()],
        job_applied=job_applied.strip(),
        limit=1
    )
    
    if not candidates:
        return HTMLResponse(
            content=f'<div class="text-center text-gray-500 py-12">未找到候选人: {name} (岗位: {job_applied})</div>'
        )
    
    # Get the first matching candidate
    candidate = candidates[0]
    
    # Use the existing detail endpoint logic (same as candidates.py)
    stored_candidate = get_candidate_by_dict(candidate)
    if stored_candidate:
        if candidate.get('name') != stored_candidate.get('name'):
            logger.warning(f"name mismatch: {candidate.get('name')} != {stored_candidate.get('name')}")
        if candidate.get('chat_id') and stored_candidate.get('chat_id') and candidate.get('chat_id') != stored_candidate.get('chat_id'):
            logger.warning(f"chat_id mismatch: {candidate.get('chat_id')} != {stored_candidate.get('chat_id')}")
        else:
            candidate.update(stored_candidate)
    candidate['score'] = stored_candidate.get("analysis", {}).get("overall") if stored_candidate else None
    
    # Ensure job_id is set - try to find job by job_applied if not present
    if not candidate.get('job_id') and candidate.get('job_applied'):
        # Try to find job by position name
        jobs = get_all_jobs()
        for job in jobs:
            if job.get("position") == candidate.get('job_applied'):
                candidate['job_id'] = job.get("job_id") or job.get("id")
                break
        # If still not found, use job_applied as job_id
        if not candidate.get('job_id'):
            candidate['job_id'] = candidate.get('job_applied')
    
    return templates.TemplateResponse("partials/candidate_detail.html", {
        "request": request,
        "analysis": candidate.pop("analysis", {}),
        "generated_message": candidate.pop("generated_message", ''),
        "resume_text": candidate.pop("resume_text", ''),
        "full_resume": candidate.pop("full_resume", ''),
        "candidate": candidate,
    })

