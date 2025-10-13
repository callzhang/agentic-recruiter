"""Job profile management routes for web UI."""

from __future__ import annotations

from pathlib import Path
import yaml

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
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


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def jobs_page(request: Request):
    """Main jobs management page."""
    return templates.TemplateResponse("jobs.html", {"request": request})


@router.get("/list", response_class=HTMLResponse)
async def list_jobs():
    """Get jobs list as HTML."""
    jobs = load_jobs()
    
    if not jobs:
        return HTMLResponse(
            content='<div class="p-6 text-center text-gray-500">暂无岗位</div>'
        )
    
    html = ""
    for job in jobs:
        html += f'''
        <div class="p-4 hover:bg-blue-50 cursor-pointer border-b"
             hx-get="/web/jobs/detail/{job.get("id", "")}"
             hx-target="#job-detail">
            <h3 class="font-bold text-gray-900">{job.get("position", "未知岗位")}</h3>
            <p class="text-sm text-gray-600 mt-1">{(job.get("description", "") or "")[:100]}</p>
        </div>
        '''
    
    return HTMLResponse(content=html)


@router.get("/list-simple", response_class=HTMLResponse)
async def list_jobs_simple(job_title: str = Query(None, description="Currently selected job title")):
    """Get jobs as HTML options for select."""
    jobs = load_jobs()
    
    if not jobs:
        return HTMLResponse(content='<option>无岗位</option>')
    
    html = ""
    for idx, job in enumerate(jobs):
        position = job.get("position", "未知")
        # Auto-select first job if no job_title provided
        selected = ' selected' if (job_title and position == job_title) or (not job_title and idx == 0) else ''
        html += f'<option value="{position}"{selected}>{position}</option>'
    
    return HTMLResponse(content=html)


@router.get("/detail/{job_id}", response_class=HTMLResponse)
async def get_job_detail(job_id: str):
    """Get job detail."""
    jobs = load_jobs()
    job = next((j for j in jobs if j.get("id") == job_id), None)
    
    if not job:
        return HTMLResponse(
            content='<div class="text-center text-gray-500 py-12">岗位未找到</div>'
        )
    
    html = f'''
    <div class="space-y-6">
        <div class="flex justify-between items-start">
            <h2 class="text-2xl font-bold text-gray-900">{job.get("position", "未知")}</h2>
            <a href="/web/jobs/{job_id}/edit" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                ✏️ 编辑
            </a>
        </div>
        
        <div class="space-y-4">
            <div>
                <h3 class="font-bold text-gray-800 mb-2">岗位背景</h3>
                <p class="text-gray-700 whitespace-pre-wrap">{job.get("background", "")}</p>
            </div>
            
            <div>
                <h3 class="font-bold text-gray-800 mb-2">岗位职责</h3>
                <p class="text-gray-700 whitespace-pre-wrap">{job.get("responsibilities", "")}</p>
            </div>
            
            <div>
                <h3 class="font-bold text-gray-800 mb-2">任职要求</h3>
                <p class="text-gray-700 whitespace-pre-wrap">{job.get("requirements", "")}</p>
            </div>
            
            <div>
                <h3 class="font-bold text-gray-800 mb-2">理想人选画像</h3>
                <p class="text-gray-700 whitespace-pre-wrap">{job.get("target_profile", "")}</p>
            </div>
        </div>
    </div>
    '''
    
    return HTMLResponse(content=html)

