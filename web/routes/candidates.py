"""Candidate management routes for web UI."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

# Base URL for internal API calls
API_BASE_URL = settings.BOSS_SERVICE_BASE_URL


# ============================================================================
# Helper functions
# ============================================================================

async def call_api(method: str, path: str, timeout: float = 30.0, **kwargs) -> tuple[bool, Any]:
    """Make HTTP request to internal API without blocking the event loop."""
    base_url = API_BASE_URL or "http://127.0.0.1:5001"
    url = f"{base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method.upper(), url, **kwargs)
        response.raise_for_status()
        if "application/json" in response.headers.get("content-type", ""):
            return True, response.json()
        return True, response.text
    except httpx.HTTPError as exc:
        return False, str(exc)


def load_jobs() -> list[dict]:
    """Load job configurations from jobs.yaml."""
    import yaml
    with open(settings.BOSS_CRITERIA_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config["roles"]


def get_job_by_id(job_id: str) -> dict:
    """Get job info by id or position name from jobs.yaml."""
    jobs = load_jobs()
    for job in jobs:
        if job.get("id") == job_id or job.get("position") == job_id:
            return job
    # Fallback: return minimal dict
    return {"id": job_id, "position": job_id}


async def prepare_init_chat_data(mode: str, chat_id: Optional[str], name: str, job_id: str, resume_text: str) -> dict:
    """Prepare data for init-chat API call by fetching chat_history and job_info."""
    # Get job info from jobs.yaml
    job_info = get_job_by_id(job_id)
    
    # For recommend candidates, they have no chat history yet
    if mode == "recommend":
        chat_history = []
    else:
        # Fetch chat history from API for chat candidates
        ok, chat_history = await call_api("GET", f"/chat/{chat_id}/messages")
        if not ok or not isinstance(chat_history, list):
            chat_history = []
    
    return {
        "chat_id": chat_id,  # None for recommend, real ID for chat
        "name": name,
        "job_info": job_info,
        "resume_text": resume_text,
        "chat_history": chat_history
    }


# ============================================================================
# Main page
# ============================================================================

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def candidates_page(request: Request):
    """Main candidates management page."""
    return templates.TemplateResponse("candidates.html", {"request": request})


# ============================================================================
# Candidate list endpoints
# ============================================================================

@router.get("/list", response_class=HTMLResponse)
async def get_candidate_list(
    request: Request,
    mode: str = Query("chat", description="Mode: chat or recommend"),
    chat_type: str = Query("新招呼", description="Chat type for chat mode"),
    job_title: str = Query(..., description="Job title filter (required)"),
    limit: int = Query(30, ge=5, le=100),
    job_id: str = Query(..., description="Job id filter (required)"),
):
    """Get candidate list as HTML fragments."""
    if mode == "chat":
        # Fetch chat candidates
        ok, data = await call_api("GET", "/chat/dialogs", params={
            "limit": limit,
            "tab": chat_type,
            "status": chat_type,
            "job_title": job_title,
            "job_id": job_id
        })
        
        if not ok or not isinstance(data, list):
            return HTMLResponse(
                content=f'<div class="text-center text-red-500 py-12">获取候选人失败: {data}</div>'
            )
        
        candidates = data
    else:
        # Fetch recommended candidates (no limit - returns all from browser page)
        # Longer timeout as this requires browser navigation and resume extraction
        ok, data = await call_api("GET", "/recommend/candidates", timeout=60.0, params={
            "job_title": job_title,
            "job_id": job_id
        })
        
        if not ok or not isinstance(data, list):
            return HTMLResponse(
                content=f'<div class="text-center text-red-500 py-12">获取推荐牛人失败: {data}</div>'
            )
        
        candidates = data
    
    # Return empty list if no candidates, let frontend handle the empty state
    if not candidates:
        candidates = []
    
    # Render candidate cards
    html = ""
    for i,candidate in enumerate(candidates):
        # Add mode to candidate data for detail view routing
        candidate["mode"] = mode
        candidate["index"] = i
        html += templates.get_template("partials/candidate_card.html").render({
            "candidate": candidate,
            "selected": False
        })
    
    return HTMLResponse(content=html)


# ============================================================================
# Candidate detail endpoints
# ============================================================================

@router.get("/detail", response_class=HTMLResponse)
async def get_candidate_detail(
    request: Request,
    mode: str = Query("chat", description="Candidate source mode: chat or recommend"),
    chat_id: Optional[str] = Query(None, description="Chat ID for chat candidates"),
    index: Optional[int] = Query(None, description="Index for recommend candidates"),
    name: str = Query(None, description="Candidate name from list"),
    job_title: str = Query(..., description="Job title from list"),
    text: str = Query(None, description="Last message/text from list"),
    stage: str = Query(None, description="Candidate stage"),
    viewed: bool = Query(None, description="Viewed status (recommend only)"),
    greeted: bool = Query(None, description="Greeted status (recommend only)"),
    assistant_id: str = Query(..., description="Selected assistant ID"),
    job_id: str = Query(..., description="Selected job ID"),
):
    """Get candidate detail view."""
    # For recommend candidates, use data passed from the card
    if mode == "recommend":
        candidate_data = {
            "chat_id": None,  # Recommend candidates don't have chat_id yet
            "index": index,
            "name": name or "推荐候选人",
            "job_title": job_title,
            "job_applied": job_title,
            "text": text,
            "mode": "recommend",
            "viewed": viewed,
            "greeted": greeted,
            "stage": stage
        }
    else:
        # Try to fetch candidate from store
        ok, candidate_data = await call_api("GET", f"/candidate/{chat_id}")
        
        if not ok or not candidate_data:
            # If not in store, use data passed from the card (if available)
            if name or job_title or text:
                candidate_data = {
                    "chat_id": chat_id,
                    "name": name,
                    "job_title": job_title,
                    "job_applied": job_title,
                    "last_message": text,
                    "stage": stage,
                    "mode": "chat"
                }
            else:
                # No data passed, fallback to minimal data
                candidate_data = {"chat_id": chat_id, "mode": "chat"}
    
    return templates.TemplateResponse("partials/candidate_detail.html", {
        "request": request,
        "candidate": candidate_data,
        "assistant_id": assistant_id,
        "job_id": job_id,
        "job_title": job_title,  # Use job_title from selector, not from candidate data
        "generated_message": None
    })


@router.get("/history/{candidate_id}", response_class=HTMLResponse)
async def get_candidate_history(candidate_id: str):
    """Get chat history for a candidate."""
    ok, history = await call_api("GET", f"/chat/{candidate_id}/messages")
    
    if not ok or not isinstance(history, list):
        return HTMLResponse(
            content='<div class="text-center text-gray-500 py-6">无法获取聊天记录</div>'
        )
    
    if not history:
        return HTMLResponse(
            content='<div class="text-center text-gray-500 py-6">暂无聊天记录</div>'
        )
    
    # Render history messages
    html = '<div class="space-y-3">'
    for msg in history:
        msg_type = msg.get("type", "")
        is_candidate = msg_type == "candidate"
        bg_color = "bg-blue-50" if is_candidate else "bg-gray-50"
        icon = "👤" if is_candidate else "🏢"
        
        html += f'''
        <div class="{bg_color} rounded-lg p-4">
            <div class="flex items-start space-x-3">
                <span class="text-2xl">{icon}</span>
                <div class="flex-1">
                    <div class="flex justify-between items-start mb-1">
                        <span class="font-medium text-gray-900">
                            {"候选人" if is_candidate else "HR"}
                        </span>
                        <span class="text-xs text-gray-500">{msg.get("timestamp", "")}</span>
                    </div>
                    <p class="text-gray-700 whitespace-pre-wrap">{msg.get("message", "")}</p>
                </div>
            </div>
        </div>
        '''
    html += '</div>'
    
    return HTMLResponse(content=html)


# ============================================================================
# Candidate action endpoints
# ============================================================================

@router.post("/init-chat")
async def init_chat(
    mode: str = Form(...),
    chat_id: Optional[str] = Form(None),
    job_id: str = Form(...),
    name: str = Form(...),
    resume_text: str = Form(...),
):
    """Initialize chat thread with proper data preparation."""
    # Prepare data with job_info from jobs.yaml and chat_history from API
    # For recommend candidates: mode="recommend" and chat_id=None
    init_data = await prepare_init_chat_data(mode, chat_id, name, job_id, resume_text)
    
    # Call the backend init-chat endpoint
    ok, result = await call_api("POST", "/thread/init-chat", json=init_data)
    
    if ok:
        # Return thread_id in response so frontend can use it for subsequent calls
        # Return as JSON instead of 204 to include thread_id
        return JSONResponse(content={
            "thread_id": result.get("thread_id"),
            "success": result.get("success", True)
        })
    else:
        # Return error with 500 status
        return JSONResponse(
            content={"error": str(result)},
            status_code=500
        )


@router.post("/analyze", response_class=HTMLResponse)
async def analyze_candidate(
    request: Request,
    mode: str = Form(...),
    chat_id: Optional[str] = Form(None),
    thread_id: Optional[str] = Form(None),
    assistant_id: str = Form(...),
    resume_text: Optional[str] = Form(None),
):
    """Analyze candidate and return updated analysis section."""
    
    # Use thread_id if available (for both chat and recommend),
    # otherwise fall back to chat_id (for backward compatibility)
    if thread_id:
        # Preferred: use thread_id directly
        api_chat_id = thread_id
    elif chat_id:
        api_chat_id = chat_id
    else:
        return HTMLResponse(
            content='<div class="text-red-500 p-4">Missing chat_id or thread_id</div>',
            status_code=400
        )
    
    # Get chat history (empty for recommend candidates without chat_id)
    if mode == "recommend" or not chat_id:
        history = []
    else:
        ok, history = await call_api("GET", f"/chat/{chat_id}/messages")
        if not ok:
            history = []
    
    # Call analysis API with thread_id
    ok, analysis_result = await call_api("POST", "/assistant/generate-message", json={
        "thread_id": api_chat_id,  # Now using thread_id directly
        "assistant_id": assistant_id,
        "chat_history": history,
        "purpose": "analyze"
    })
    
    if not ok:
        return HTMLResponse(
            content=f'<div class="text-red-500 p-4">分析失败: {analysis_result}</div>'
        )
    
    # Render analysis result
    candidate_data = {"analysis": analysis_result, "chat_id": chat_id or thread_id}
    return templates.TemplateResponse("partials/analysis_result.html", {
        "request": request,
        "candidate": candidate_data,
        "assistant_id": assistant_id
    })


@router.post("/generate-message", response_class=HTMLResponse)
async def generate_message(
    mode: str = Form(...),
    chat_id: Optional[str] = Form(None),
    thread_id: Optional[str] = Form(None),
    assistant_id: str = Form(...),
):
    """Generate message for candidate."""
    # Use thread_id if available, otherwise look it up by chat_id
    if not thread_id and chat_id:
        # Lookup thread_id from Zilliz using chat_id
        ok, candidate = await call_api("GET", f"/candidate/{chat_id}")
        if not ok or not candidate:
            return HTMLResponse(
                content='<div class="text-red-500 p-4">候选人不存在，请先初始化对话</div>',
                status_code=404
            )
        thread_id = candidate.get("thread_id")
    
    if not thread_id:
        return HTMLResponse(
            content='''<div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                <p class="font-bold text-yellow-800 mb-2">⚠️ 无法生成消息</p>
                <p class="text-yellow-700 mb-2">请先获取候选人简历，系统将自动初始化对话线程。</p>
                <p class="text-sm text-yellow-600">步骤：<span class="font-mono">简历标签 → 获取简历按钮 → 等待加载完成 → 返回操作区域</span></p>
            </div>'''
        )
    
    # Get chat history (empty for recommend candidates)
    if mode == "recommend" or not chat_id:
        history = []
    else:
        ok, history = await call_api("GET", f"/chat/{chat_id}/messages")
        if not ok:
            history = []
    
    # Generate message using thread_id
    ok, message = await call_api("POST", "/assistant/generate-message", json={
        "thread_id": thread_id,
        "assistant_id": assistant_id,
        "chat_history": history,
        "purpose": "chat"
    })
    
    if not ok:
        return HTMLResponse(
            content=f'<div class="text-red-500 p-4">生成消息失败: {message}</div>'
        )
    
    # Return textarea with generated message and send button
    html = f'''
    <div class="space-y-4">
        <div>
            <label class="block text-sm font-medium text-gray-700 mb-2">生成的消息</label>
            <textarea id="message-text" name="message" class="w-full h-32 p-4 border rounded-lg">{message}</textarea>
        </div>
        <div class="flex space-x-2">
            <button hx-post="/web/candidates/send"
                    hx-include="#candidate-context,#message-text"
                    hx-target="body"
                    hx-swap="none"
                    class="flex-1 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700">
                📤 发送消息
            </button>
            <button hx-post="/web/candidates/pass"
                    hx-include="#candidate-context"
                    hx-target="body"
                    hx-swap="none"
                    class="flex-1 px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300">
                ❌ PASS
            </button>
        </div>
    </div>
    '''
    
    return HTMLResponse(content=html)


@router.post("/send", response_class=HTMLResponse)
async def send_message(
    mode: str = Form(...),
    chat_id: Optional[str] = Form(None),
    index: Optional[int] = Form(None),
    message: str = Form(...),
):
    """Send message to candidate."""
    if not message.strip():
        return HTMLResponse(
            content='',
            status_code=200,
            headers={"HX-Trigger": '{"showToast": {"message": "消息内容不能为空", "type": "warning"}}'}
        )
    
    # Handle different modes
    if mode == "recommend" and index is not None:
        # For recommend candidates, use greet endpoint
        ok, result = await call_api("POST", f"/recommend/candidate/{index}/greet", json={"message": message})
    elif chat_id:
        # For chat candidates, use send endpoint
        ok, result = await call_api("POST", f"/chat/{chat_id}/send", json={"message": message})
    else:
        return HTMLResponse(
            content='',
            status_code=400,
            headers={"HX-Trigger": '{"showToast": {"message": "缺少候选人ID", "type": "error"}}'}
        )
    
    if ok and result is True:
        return HTMLResponse(
            content='',
            status_code=200,
            headers={
                "HX-Trigger": json.dumps({"showToast": {"message": "消息发送成功！", "type": "success"}}),
            }
        )
    else:
        return HTMLResponse(
            content='',
            status_code=500,
            headers={"HX-Trigger": json.dumps({"showToast": {"message": f"发送失败: {result}", "type": "error"}})}
        )


@router.post("/request-resume", response_class=HTMLResponse)
async def request_resume(chat_id: str = Form(...)):
    """Request full resume from candidate."""
    ok, result = await call_api("POST", "/resume/request", json={"chat_id": chat_id})
    
    if ok and result is True:
        return HTMLResponse(
            content='<div class="text-green-600 p-4">✅ 简历请求已发送</div>'
        )
    else:
        return HTMLResponse(
            content=f'<div class="text-red-500 p-4">❌ 请求失败: {result}</div>',
            status_code=500
        )


@router.post("/fetch-online-resume", response_class=HTMLResponse)
async def fetch_online_resume(
    chat_id: str = Form(...),
):
    """Fetch online resume for chat candidate and return textarea."""
    # Call online resume API
    ok, resume_data = await call_api("POST", "/resume/online", json={"chat_id": chat_id})

    if not ok:
        return HTMLResponse(
            content='<div class="text-red-500 p-4">无法获取在线简历</div>',
            status_code=500
        )

    # Always return textarea for automatic workflow
    resume_text = resume_data.get("text", "")
    return HTMLResponse(
        content=f'<textarea readonly class="w-full h-64 p-4 bg-gray-50 border rounded-lg font-mono text-sm">{resume_text}</textarea>'
    )


@router.post("/fetch-recommend-resume", response_class=HTMLResponse)
async def fetch_recommend_resume(
    index: int = Form(...),
):
    """Fetch resume for recommend candidate and return textarea."""
    ok, resume_data = await call_api("GET", f"/recommend/candidate/{index}/resume")
    
    if not ok:
        return HTMLResponse(
            content='<div class="text-red-500 p-4">无法获取推荐候选人简历</div>',
            status_code=500
        )

    # Always return textarea for automatic workflow
    resume_text = resume_data.get("text", "")
    return HTMLResponse(
        content=f'<textarea readonly class="w-full h-64 p-4 bg-gray-50 border rounded-lg font-mono text-sm">{resume_text}</textarea>'
    )


@router.post("/fetch-full-resume", response_class=HTMLResponse)
async def fetch_full_resume(
    request: Request,
    chat_id: str = Form(...),
    mode: str = Form("chat"),
    assistant_id: str = Form(""),
    job_id: str = Form(""),
):
    """Explicitly fetch full/offline resume (not online resume)."""
    # Only for chat mode, not recommend
    if mode != "chat":
        return HTMLResponse(
            content='<div class="text-red-500 p-4">推荐候选人不支持离线简历</div>',
            status_code=400
        )
    
    # Try to get full resume only
    ok, resume_data = await call_api("POST", "/resume/view_full", json={"chat_id": chat_id})

    if not ok:
        return HTMLResponse(
            content='<div class="text-red-500 p-4">无法获取离线简历，可能尚未上传附件简历</div>',
            status_code=500
        )

    # Fetch latest candidate metadata for display
    ok_candidate, candidate_data = await call_api("GET", f"/candidate/{chat_id}")
    if not ok_candidate or not isinstance(candidate_data, dict):
        candidate_data = {"chat_id": chat_id}

    # Re-render detail with full resume
    candidate_data.update({
        "chat_id": chat_id,
        "resume_text": resume_data.get("text", ""),
        "full_resume": resume_data.get("text", ""),
        "mode": mode
    })

    return templates.TemplateResponse("partials/candidate_detail.html", {
        "request": request,
        "candidate": candidate_data,
        "assistant_id": assistant_id,
        "job_id": job_id,
        "generated_message": None
    })


@router.post("/pass", response_class=HTMLResponse)
async def pass_candidate(chat_id: str = Form(...)):
    """Mark candidate as PASS and move to next."""
    ok, result = await call_api("POST", "/candidate/discard", json={
        "chat_id": chat_id,
        "stage": "PASS"
    })
    
    if ok and result is True:
        # Trigger refresh of candidate list
        return HTMLResponse(
            content='<div class="text-green-600">✅ 已标记为 PASS</div>',
            headers={"HX-Trigger": "candidateUpdated"}
        )
    else:
        return HTMLResponse(
            content=f'<div class="text-red-500">❌ 操作失败: {result}</div>',
            status_code=500
        )


@router.post("/next", response_class=HTMLResponse)
async def next_candidate(
    request: Request,
    current_id: str = Form(...),
):
    """Move to next candidate in the list."""
    # This is a placeholder - in real implementation, you'd need to track
    # the current list and find the next candidate
    return HTMLResponse(
        content='<div class="text-center text-gray-500 py-24">请从列表中选择下一个候选人</div>'
    )


# ============================================================================
# Record Reuse Endpoints
# ============================================================================



@router.get("/thread-history/{thread_id}", response_class=HTMLResponse)
async def get_thread_history(
    request: Request,
    thread_id: str
):
    """Get thread history HTML."""
    ok, messages = await call_api("GET", f"/thread/{thread_id}/messages")
    
    if not ok:
        return HTMLResponse(content='<div class="text-red-500">获取历史失败</div>')
    
    # Render thread history template
    return templates.TemplateResponse("partials/thread_history.html", {
        "request": request,
        "messages": messages,
        "thread_id": thread_id
    })


@router.post("/render-analysis", response_class=HTMLResponse)
async def render_analysis(
    request: Request,
    analysis: dict = Form(...)
):
    """Render analysis template."""
    # Parse JSON if it's a string
    if isinstance(analysis, str):
        import json
        analysis = json.loads(analysis)
    
    candidate_data = {"analysis": analysis}
    return templates.TemplateResponse("partials/analysis_result.html", {
        "request": request,
        "candidate": candidate_data
    })


