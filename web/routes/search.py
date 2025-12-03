"""Data search routes for web UI.
Allows searching candidates by name and job_applied for viewing by other colleagues.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from src.candidate_store import (
    search_candidates_advanced,
)
from src.jobs_store import get_all_jobs
from src.global_logger import logger

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")
STAGE_OPTIONS = ["PASS", "CHAT", "SEEK", "CONTACT"]


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
        "stage_options": STAGE_OPTIONS,
    })


@router.get("/query", response_class=HTMLResponse)
async def search_candidates(
    request: Request,
    name: Optional[str] = Query(None, description="Candidate name"),
    job_applied: Optional[str] = Query(None, description="Job position filter"),
    stage: Optional[str] = Query(None, description="Candidate stage"),
    notified: Optional[str] = Query(None, description="Notified flag (true/false)"),
    score_min: Optional[float] = Query(None, ge=0, le=10, description="Minimum analysis score (0-10)"),
    date_from: Optional[str] = Query(None, description="Updated at (from, YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Updated at (to, YYYY-MM-DD)"),
    resume_contains: Optional[str] = Query(None, description="Resume text contains"),
    semantic_query: Optional[str] = Query(None, description="Semantic search query"),
    sort_by: str = Query("updated_at"),
    sort_dir: str = Query("desc"),
    limit: int = Query(100, gt=0, le=500, description="Result limit (1-500)"),
):
    """Search for candidates with advanced filters and return a table view."""

    def _parse_date(date_value: Optional[str], end_of_day: bool = False) -> Optional[str]:
        if not date_value:
            return None
        try:
            parsed = datetime.strptime(date_value, "%Y-%m-%d")
            if end_of_day:
                parsed = parsed + timedelta(days=1) - timedelta(seconds=1)
            return parsed.isoformat()
        except ValueError:
            return None

    updated_from = _parse_date(date_from)
    updated_to = _parse_date(date_to, end_of_day=True)
    
    # Convert notified string to bool
    notified_bool = None
    if notified:
        notified_lower = notified.strip().lower()
        if notified_lower in ('true', '1', 'yes'):
            notified_bool = True
        elif notified_lower in ('false', '0', 'no'):
            notified_bool = False

    candidates = search_candidates_advanced(
        names=[name.strip()] if name and name.strip() else None,
        job_applied=job_applied.strip() if job_applied else None,
        stage=stage.strip() if stage else None,
        notified=notified_bool,
        updated_from=updated_from,
        updated_to=updated_to,
        resume_contains=resume_contains.strip() if resume_contains else None,
        semantic_query=semantic_query.strip() if semantic_query else None,
        min_score=score_min,
        limit=limit,
        sort_by=sort_by,
        sort_direction=sort_dir,
    )

    return templates.TemplateResponse("partials/search_results_table.html", {
        "request": request,
        "candidates": candidates,
        "result_count": len(candidates),
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    })


@router.get("/detail/{candidate_id}", response_class=HTMLResponse)
async def search_candidate_detail(request: Request, candidate_id: str):
    """Return candidate detail view in read-only mode for the search page."""
    stored = search_candidates_advanced(candidate_ids=[candidate_id], limit=1)
    if not stored:
        return HTMLResponse(
            content=f'<div class="text-center text-gray-500 py-6">未找到候选人: {candidate_id}</div>',
            status_code=404,
        )

    candidate = stored[0]

    candidate['score'] = candidate.get("analysis", {}).get("overall")

    return templates.TemplateResponse("partials/candidate_detail.html", {
        "request": request,
        "analysis": candidate.pop("analysis", {}),
        "generated_message": candidate.pop("generated_message", ''),
        "resume_text": candidate.pop("resume_text", ''),
        "full_resume": candidate.pop("full_resume", ''),
        "candidate": candidate,
        "view_mode": "readonly",
    })

