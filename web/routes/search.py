"""Data search routes for web UI.
Allows searching candidates by name and job_applied for viewing by other colleagues.
"""

import asyncio
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
from web.utils.performance import profile_operation

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")
STAGE_OPTIONS = ["PASS", "CHAT", "SEEK", "CONTACT"]


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def search_page(request: Request):
    """Main search page with form to search candidates by name and job."""
    # Load all jobs for the dropdown (run in thread pool to avoid blocking event loop)
    jobs = await asyncio.to_thread(get_all_jobs)
    # Extract unique job positions for dropdown
    job_positions = sorted(set([job.get("position", "") for job in jobs if job.get("position")]))
    
    # Render template content in thread pool to avoid blocking event loop
    def _render_template():
        template = templates.get_template("search.html")
        return template.render({
            "request": request,
            "jobs": jobs,
            "job_positions": job_positions,
            "stage_options": STAGE_OPTIONS,
        })
    
    html_content = await asyncio.to_thread(_render_template)
    return HTMLResponse(content=html_content)


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

    # Run database query in thread pool to avoid blocking event loop
    candidates = await asyncio.to_thread(
        search_candidates_advanced,
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

    # Render template content in thread pool to avoid blocking event loop
    def _render_template():
        template = templates.get_template("partials/search_results_table.html")
        return template.render({
            "request": request,
            "candidates": candidates,
            "result_count": len(candidates),
            "sort_by": sort_by,
            "sort_dir": sort_dir,
        })
    
    html_content = await asyncio.to_thread(_render_template)
    return HTMLResponse(content=html_content)


@router.get("/detail/{candidate_id}", response_class=HTMLResponse)
async def search_candidate_detail(request: Request, candidate_id: str):
    """Return candidate detail view in read-only mode for the search page."""
    import time
    handler_start = time.perf_counter()
    
    # Check if request arrival time was recorded by middleware
    if hasattr(request.state, 'request_arrival_time'):
        queue_wait_ms = (handler_start - request.state.request_arrival_time) * 1000
        if queue_wait_ms > 10.0:  # Log if request waited more than 10ms
            logger.warning(f"[PERF] Request queued for {queue_wait_ms:.2f}ms before handler: /search/detail/{candidate_id}")
    
    with profile_operation(f"search_candidate_detail({candidate_id})", log_threshold_ms=0.0) as profiler:
        profiler.step("start")
        
        # Run database query in thread pool to avoid blocking event loop
        profiler.step("before_db_query")
        thread_pool_wait_start = time.perf_counter()
        stored = await asyncio.to_thread(
            search_candidates_advanced,
            candidate_ids=[candidate_id],
            limit=1
        )
        thread_pool_wait_ms = (time.perf_counter() - thread_pool_wait_start) * 1000
        if thread_pool_wait_ms > 10.0:  # Log if waited more than 10ms for thread pool
            logger.warning(f"[PERF] Thread pool wait: {thread_pool_wait_ms:.2f}ms (may indicate thread pool saturation)")
        profiler.step("after_db_query")
        
        if not stored:
            return HTMLResponse(
                content=f'<div class="text-center text-gray-500 py-6">未找到候选人: {candidate_id}</div>',
                status_code=404,
            )

        candidate = stored[0]
        profiler.step("after_extract_candidate")

        candidate['score'] = candidate.get("analysis", {}).get("overall")
        profiler.step("after_set_score")

        # Prepare template context (pop values before rendering to avoid issues)
        analysis = candidate.pop("analysis", {})
        generated_message = candidate.pop("generated_message", '')
        resume_text = candidate.pop("resume_text", '')
        full_resume = candidate.pop("full_resume", '')
        profiler.step("after_prepare_context")
        
        # Render template content in thread pool to avoid blocking event loop
        def _render_template():
            template = templates.get_template("partials/candidate_detail.html")
            return template.render({
                "request": request,
                "analysis": analysis,
                "generated_message": generated_message,
                "resume_text": resume_text,
                "full_resume": full_resume,
                "candidate": candidate,
                "view_mode": "readonly",
            })
        
        profiler.step("before_template_render")
        html_content = await asyncio.to_thread(_render_template)
        profiler.step("after_template_render")
        
        return HTMLResponse(content=html_content)

