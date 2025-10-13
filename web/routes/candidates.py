"""Candidate management routes for web UI."""

from __future__ import annotations

from typing import Any, Dict

import httpx
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
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
):
    """Get candidate list as HTML fragments."""
    if mode == "chat":
        # Fetch chat candidates
        ok, data = await call_api("GET", "/chat/dialogs", params={
            "limit": limit,
            "tab": chat_type,
            "status": chat_type,
            "job_title": job_title
        })
        
        if not ok or not isinstance(data, list):
            return HTMLResponse(
                content=f'<div class="text-center text-red-500 py-12">获取候选人失败: {data}</div>'
            )
        
        candidates = data
    else:
        # Fetch recommended candidates (longer timeout - needs browser navigation)
        ok, data = await call_api("GET", "/recommend/candidates", timeout=20.0, params={
            "limit": limit,
            "job_title": job_title
        })
        
        if not ok or not isinstance(data, list):
            return HTMLResponse(
                content=f'<div class="text-center text-red-500 py-12">获取推荐牛人失败: {data}</div>'
            )
        
        candidates = data
    
    if not candidates:
        return HTMLResponse(
            content='<div class="text-center text-gray-500 py-12">暂无候选人数据</div>'
        )
    
    # Render candidate cards
    html = ""
    for candidate in candidates:
        # Add mode to candidate data for detail view routing
        candidate["mode"] = mode
        html += templates.get_template("partials/candidate_card.html").render({
            "candidate": candidate,
            "selected": False
        })
    
    return HTMLResponse(content=html)


# ============================================================================
# Candidate detail endpoints
# ============================================================================

@router.get("/detail/{candidate_id}", response_class=HTMLResponse)
async def get_candidate_detail(
    request: Request,
    candidate_id: str,
    mode: str = Query("chat", description="Candidate source mode: chat or recommend"),
    name: str = Query(None, description="Candidate name from list"),
    job_title: str = Query(None, description="Job title from list"),
    text: str = Query(None, description="Last message/text from list"),
    stage: str = Query(None, description="Candidate stage"),
    viewed: bool = Query(None, description="Viewed status (recommend only)"),
    greeted: bool = Query(None, description="Greeted status (recommend only)"),
    assistant_id: str = Query(None, description="Selected assistant ID"),
    job_id: str = Query(None, description="Selected job ID"),
):
    """Get candidate detail view."""
    # For recommend candidates, use data passed from the card
    if mode == "recommend" and candidate_id.startswith("recommend_"):
        index = int(candidate_id.split("_")[1])
        candidate_data = {
            "chat_id": candidate_id,
            "id": candidate_id,
            "name": name or "推荐候选人",
            "job_title": job_title,
            "job_applied": job_title,
            "text": text,
            "mode": "recommend",
            "index": index,
            "viewed": viewed,
            "greeted": greeted,
            "stage": stage
        }
    else:
        # Try to fetch candidate from store
        ok, candidate_data = await call_api("GET", f"/candidate/{candidate_id}")
        
        if not ok or not candidate_data:
            # If not in store, use data passed from the card (if available)
            if name or job_title or text:
                candidate_data = {
                    "chat_id": candidate_id,
                    "id": candidate_id,
                    "name": name,
                    "job_title": job_title,
                    "job_applied": job_title,
                    "last_message": text,
                    "stage": stage,
                    "mode": "chat"
                }
            else:
                # No data passed, fallback to minimal data
                candidate_data = {"chat_id": candidate_id, "id": candidate_id, "mode": "chat"}
    
    # Get default assistant and job if not provided
    if not assistant_id:
        ok, assistants = await call_api("GET", "/assistant/list")
        assistant_id = assistants[0]["id"] if ok and assistants else None
    
    if not job_id:
        # Get first job from config directly
        import yaml
        try:
            with open(settings.BOSS_CRITERIA_PATH, "r", encoding="utf-8") as f:
                jobs_config = yaml.safe_load(f)
            job_id = list(jobs_config.keys())[0] if jobs_config else None
        except:
            job_id = None
    
    return templates.TemplateResponse("partials/candidate_detail.html", {
        "request": request,
        "candidate": candidate_data,
        "assistant_id": assistant_id,
        "job_id": job_id,
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

@router.post("/analyze", response_class=HTMLResponse)
async def analyze_candidate(
    request: Request,
    chat_id: str = Form(...),
    assistant_id: str = Form(...),
    job_id: str = Form(None),
):
    """Analyze candidate and return updated analysis section."""
    # Check if candidate exists in store with thread_id
    ok, candidate = await call_api("GET", f"/candidate/{chat_id}")
    if not ok or not candidate or not candidate.get("thread_id"):
        # Candidate needs resume to be fetched first
        return HTMLResponse(
            content='''<div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                <p class="font-bold text-yellow-800 mb-2">⚠️ 无法分析候选人</p>
                <p class="text-yellow-700 mb-2">请先获取候选人简历，系统将自动初始化对话线程。</p>
                <p class="text-sm text-yellow-600">步骤：<span class="font-mono">简历标签 → 获取简历按钮 → 等待加载完成 → 返回分析标签</span></p>
            </div>'''
        )
    
    # Get chat history
    ok, history = await call_api("GET", f"/chat/{chat_id}/messages")
    if not ok:
        history = []
    
    # Call analysis API
    ok, analysis_result = await call_api("POST", "/assistant/generate-message", json={
        "chat_id": chat_id,
        "assistant_id": assistant_id,
        "chat_history": history,
        "purpose": "analyze"
    })
    
    if not ok:
        return HTMLResponse(
            content=f'<div class="text-red-500 p-4">分析失败: {analysis_result}</div>'
        )
    
    # Render analysis result
    candidate_data = {"analysis": analysis_result, "chat_id": chat_id}
    return templates.TemplateResponse("partials/analysis_result.html", {
        "request": request,
        "candidate": candidate_data,
        "assistant_id": assistant_id
    })


@router.post("/generate-message", response_class=HTMLResponse)
async def generate_message(
    chat_id: str = Form(...),
    assistant_id: str = Form(...),
):
    """Generate message for candidate."""
    # Check if candidate exists in store with thread_id
    ok, candidate = await call_api("GET", f"/candidate/{chat_id}")
    if not ok or not candidate or not candidate.get("thread_id"):
        # Candidate needs resume to be fetched first
        return HTMLResponse(
            content='''<div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                <p class="font-bold text-yellow-800 mb-2">⚠️ 无法生成消息</p>
                <p class="text-yellow-700 mb-2">请先获取候选人简历，系统将自动初始化对话线程。</p>
                <p class="text-sm text-yellow-600">步骤：<span class="font-mono">简历标签 → 获取简历按钮 → 等待加载完成 → 返回操作区域</span></p>
            </div>'''
        )
    
    # Get chat history
    ok, history = await call_api("GET", f"/chat/{chat_id}/messages")
    if not ok:
        history = []
    
    # Generate message
    ok, message = await call_api("POST", "/assistant/generate-message", json={
        "chat_id": chat_id,
        "assistant_id": assistant_id,
        "chat_history": history,
        "purpose": "chat"
    })
    
    if not ok:
        return HTMLResponse(
            content=f'<div class="text-red-500 p-4">生成消息失败: {message}</div>'
        )
    
    # Return textarea with generated message
    html = f'''
    <div class="mb-4">
        <label class="block text-sm font-medium text-gray-700 mb-2">生成的消息</label>
        <textarea id="message-text" name="message" class="w-full h-32 p-4 border rounded-lg">{message}</textarea>
    </div>
    '''
    
    return HTMLResponse(content=html)


@router.post("/send", response_class=HTMLResponse)
async def send_message(
    chat_id: str = Form(...),
    message: str = Form(...),
):
    """Send message to candidate."""
    if not message.strip():
        return HTMLResponse(
            content='<div class="text-yellow-600 p-4">消息内容不能为空</div>',
            status_code=400
        )
    
    ok, result = await call_api("POST", f"/chat/{chat_id}/send", json={"message": message})
    
    if ok and result is True:
        return HTMLResponse(
            content='<div class="text-green-600 p-4">✅ 消息发送成功</div>',
            headers={
                "HX-Trigger": "messagesSent",
                "HX-Trigger-After-Settle": '{"showToast": {"message": "消息发送成功", "type": "success"}}'
            }
        )
    else:
        return HTMLResponse(
            content=f'<div class="text-red-500 p-4">❌ 发送失败: {result}</div>',
            status_code=500,
            headers={"HX-Trigger": '{"showToast": {"message": "消息发送失败", "type": "error"}}'}
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
    request: Request,
    chat_id: str = Form(...),
    mode: str = Form("chat"),
    assistant_id: str = Form(""),
    job_id: str = Form(""),
):
    """Fetch online resume for chat candidate (view_online_resume_action)."""
    if mode != "chat":
        return HTMLResponse(
            content='<div class="text-red-500 p-4">推荐候选人不支持在线简历</div>',
            status_code=400
        )
    
    # Call online resume API
    ok, resume_data = await call_api("POST", "/resume/online", json={"chat_id": chat_id})

    if not ok:
        return HTMLResponse(
            content=f'<div class="text-red-500 p-4">无法获取在线简历: {resume_data}</div>',
            status_code=500
        )

    # Fetch latest candidate metadata for display
    ok_candidate, candidate_data = await call_api("GET", f"/candidate/{chat_id}")
    if not ok_candidate or not isinstance(candidate_data, dict):
        candidate_data = {"chat_id": chat_id}

    # Re-render detail with online resume
    candidate_data.update({
        "chat_id": chat_id,
        "resume_text": resume_data.get("text", ""),
        "mode": mode
    })

    return templates.TemplateResponse("partials/candidate_detail.html", {
        "request": request,
        "candidate": candidate_data,
        "assistant_id": assistant_id,
        "job_id": job_id,
        "generated_message": None
    })


@router.post("/fetch-recommend-resume", response_class=HTMLResponse)
async def fetch_recommend_resume(
    request: Request,
    chat_id: str = Form(...),
    mode: str = Form("recommend"),
    assistant_id: str = Form(""),
    job_id: str = Form(""),
):
    """Fetch resume for recommend candidate (view_recommend_candidate_resume_action)."""
    if mode != "recommend" or not chat_id.startswith("recommend_"):
        return HTMLResponse(
            content='<div class="text-red-500 p-4">仅支持推荐候选人</div>',
            status_code=400
        )
    
    index = int(chat_id.split("_")[1])
    ok, resume_data = await call_api("GET", f"/recommend/candidate/{index}/resume")
    
    if not ok:
        return HTMLResponse(
            content=f'<div class="text-red-500 p-4">无法获取推荐候选人简历: {resume_data}</div>',
            status_code=500
        )

    # For recommend candidates, we don't have persistent storage
    candidate_data = {
        "chat_id": chat_id,
        "id": chat_id,
        "resume_text": resume_data.get("text", ""),
        "mode": mode,
        "index": index
    }

    return templates.TemplateResponse("partials/candidate_detail.html", {
        "request": request,
        "candidate": candidate_data,
        "assistant_id": assistant_id,
        "job_id": job_id,
        "generated_message": None
    })


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


