"""Candidate management routes for web UI."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.config import settings
from src.jobs_store import jobs_store
from src.candidate_store import candidate_store
from src.assistant_utils import get_embedding
from src.recommendation_actions import logger

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
        return False, exc


def load_jobs() -> list[dict]:
    """Load job configurations from Zilliz Cloud."""
    return jobs_store.get_all_jobs()


def get_job_by_id(job_id: str) -> dict:
    """Get job info by id or position name from Zilliz Cloud."""
    job = jobs_store.get_job_by_id(job_id)
    if job:
        return job
    # If not found by ID, try to find by position name
    jobs = load_jobs()
    for job in jobs:
        if job.get("position") == job_id:
            return job
    # Fallback: return minimal dict
    return {"job_id": job_id, "id": job_id, "position": job_id}



async def search_candidate_by_similarity(resume_text: str) -> Optional[Dict[str, Any]]:
    """Search for candidate by resume similarity with 0.9 threshold."""
    if not resume_text:
        return None
    
    # Generate embedding
    embedding = get_embedding(resume_text)
    if not embedding:
        return None
    
    # Search using candidate_store
    if candidate_store.enabled:
        result = candidate_store.search_candidates(resume_vector=embedding, limit=1, similarity_threshold=0.9)
        return result
    
    return None


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
    mode: str = Query("chat", description="Mode: recommend, greet, chat, or followup"),
    job_title: str = Query(..., description="Job title filter (required)"),
    limit: int = Query(30, ge=5, le=100),
):
    """Get candidate list as HTML fragments.
    
    Supports four modes:
    - recommend: Get recommended candidates from 推荐牛人 page
    - greet: Get new greeting candidates (新招呼, 未读)
    - chat: Get ongoing chat candidates (沟通中, 未读)
    - followup: Get follow-up candidates (沟通中, 牛人已读未回)
    """
    if mode == "recommend":
        # Get job to retrieve candidate_filters
        job = get_job_by_id(job_title)
        
        # Build params for recommendation API
        params = {
            "job_title": job_title,
            "limit": limit,
            "new_only": False,
        }
        
        # Convert candidate_filters dict to JSON string for query parameter
        candidate_filters = job.get("candidate_filters") if job else None
        if candidate_filters:
            params["filters"] = json.dumps(candidate_filters, ensure_ascii=False)
        else:
            params["filters"] = None
        
        # Fetch recommended candidates (no limit - returns all from browser page)
        # Longer timeout as this requires browser navigation and resume extraction
        ok, data = await call_api("GET", "/recommend/candidates", timeout=60.0, params=params)
        
        if not ok or not isinstance(data, list):
            return HTMLResponse(
                content=f'<div class="text-center text-red-500 py-12">获取推荐牛人失败: {data}</div>'
            )
        
        candidates = data
    else:
        # Map modes to tab and status filters based on boss_service.py API
        if mode == "greet":
            tab_filter = "新招呼"
            status_filter = "未读"
        elif mode == "chat":
            tab_filter = "沟通中"
            status_filter = "未读"
        elif mode == "followup":
            tab_filter = "沟通中"
            status_filter = "牛人已读未回"
        else:
            return HTMLResponse(
                content=f'<div class="text-center text-red-500 py-12">无效的模式: {mode}</div>',
                status_code=400
            )
        
        # Fetch chat candidates
        ok, data = await call_api("GET", "/chat/dialogs", params={
            "limit": limit,
            "tab": tab_filter,
            "status": status_filter,
            "job_title": job_title,
            "new_only": False,
        })
        
        if not ok or not isinstance(data, list):
            return HTMLResponse(
                content=f'<div class="text-center text-red-500 py-12">获取候选人失败: {data}</div>'
            )
        
        candidates = data
    
    # Return empty list if no candidates, let frontend handle the empty state
    if not candidates:
        candidates = []
    
    # Render candidate cards
    html = ""
    for i, candidate in enumerate(candidates):
        # Add mode to candidate data for detail view routing
        candidate["mode"] = mode
        
        # Ensure index exists
        if "index" not in candidate:
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
    # For recommend candidates, use data passed from the card (no Zilliz lookup)
    if mode == "recommend":
        if index is None:
            return HTMLResponse(
                content='<div class="text-red-500 p-4">推荐候选人必须提供索引(index)参数</div>',
                status_code=400
            )
        if type(index) != int:
            raise ValueError("index must be an integer")
        candidate_data = {
            "chat_id": None,  # Recommend candidates don't have chat_id yet
            "index": index,
            "name": name or "推荐候选人",
            "job_title": job_title,
            "job_applied": job_title,
            "text": text,
            "mode": mode,
            "viewed": viewed,
            "greeted": greeted,
            "stage": stage
        }
    elif mode == "greet":
        # Greet mode candidates have chat_id from chat dialogs
        candidate_data = {
            "chat_id": chat_id,  # Greet candidates have chat_id
            "name": name or "新招呼候选人",
            "job_title": job_title,
            "job_applied": job_title,
            "text": text,
            "mode": mode,
            "stage": stage
        }
    else:
        # For chat/followup mode: search by chat_id first, then similarity search fallback
        candidate_data = None
        
        # First try: Search by chat_id
        if chat_id:
            ok, candidate_data = await call_api("GET", f"/store/candidate/{chat_id}")
            if ok and candidate_data:
                logger.info("Found candidate from zilliz cloud by chat_id: %s", candidate_data['name'])
                candidate_data["mode"] = mode
                candidate_data["description"] = candidate_data.get("last_message") or text
        
        # If not found, try similarity search
        # if not candidate_data and chat_id:
        #     # Fetch online resume to do similarity search
        #     ok, resume_data = await call_api("GET", f"/chat/resume/online/{chat_id}")
        #     if ok and resume_data:
        #         resume_text = resume_data.get("text", "")
        #         if resume_text:
        #             # Search by similarity
        #             similar_candidate = await search_candidate_by_similarity(resume_text)
        #             if similar_candidate:
        #                 # Found similar candidate, use it but keep the new chat_id
        #                 candidate_data = dict(similar_candidate)
        #                 candidate_data["chat_id"] = chat_id  # Update with current chat_id
        #                 candidate_data["mode"] = mode
        #                 candidate_data["description"] = candidate_data.get("last_message") or text
        
        # If still not found, use data passed from the card
        if not candidate_data:
            candidate_data = {
                "name": name,
                "job_title": job_title,
                "job_applied": job_title,
                "text": text,
                "stage": stage,
                "chat_id": chat_id, 
                "mode": mode,
                "description": text,
                "viewed": viewed,
                "greeted": greeted,
            }
    
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
    # job_info = await prepare_init_chat_data(mode, chat_id, name, job_id, resume_text)
    job_info = get_job_by_id(job_id)
    init_data = {
        "mode": mode,
        "chat_id": chat_id,
        "job_info": job_info,
        "name": name,
        "resume_text": resume_text
    }
    # Call the backend init-chat endpoint
    ok, result = await call_api("POST", "/assistant/init-chat", json=init_data)
    
    if ok:
        # Return conversation_id in response so frontend can use it for subsequent calls
        # init_chat now returns conversation_id as string, so convert to dict format
        conversation_id = result if isinstance(result, str) else result.get("conversation_id") or result.get("thread_id")
        return JSONResponse(content={
            "conversation_id": conversation_id,
            "success": True
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
    conversation_id: str = Form(...),
    assistant_id: str = Form(...),
    job_id: str = Form(...),
    resume_text: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
):
    """Analyze candidate and return updated analysis section with threshold-based action flags."""
    form_data = await request.form()
    data = dict(form_data)
    chat_history = data.get("chat_history", [])
    
    # Get resume_text from form if not provided, or try to get from request body
    if not resume_text:
        resume_text = data.get("resume_text", "")
    
    # Fetch job_info from jobs_store
    job_info = get_job_by_id(job_id)
    
    # Call analysis API with conversation_id, assistant_id, and job_info
    ok, analysis_result = await call_api("POST", "/assistant/generate-message", timeout=100.0, json={
        "conversation_id": conversation_id,
        "input_message": resume_text,  # Use resume_text as input message for analysis
        "purpose": "ANALYZE_ACTION"
    })
    
    if not ok:
        return HTMLResponse(
            content=f'<div class="text-red-500 p-4">分析失败: {analysis_result}</div>'
        )
    
    # Parse analysis result to extract overall score
    try:
        if isinstance(analysis_result, str):
            analysis_data = json.loads(analysis_result)
        else:
            analysis_data = analysis_result
        
        overall_score = analysis_data.get("overall", 0)
        threshold_borderline = 7.0  # Default threshold for greet
        threshold_seek = 9.0  # Default threshold for request full resume
        
        # Determine action flags based on thresholds
        should_generate_greet = overall_score >= threshold_borderline
        should_request_resume = overall_score >= threshold_seek
        
        # Add action flags to analysis data
        analysis_data["action_flags"] = {
            "should_generate_greet": should_generate_greet,
            "should_request_resume": should_request_resume,
            "threshold_borderline": threshold_borderline,
            "threshold_seek": threshold_seek
        }
        
    except (json.JSONDecodeError, KeyError, TypeError):
        # If parsing fails, set safe defaults
        analysis_data = analysis_result if isinstance(analysis_result, dict) else {"summary": str(analysis_result)}
        analysis_data["action_flags"] = {
            "should_generate_greet": False,
            "should_request_resume": False,
            "threshold_borderline": 7.0,
            "threshold_seek": 9.0
        }
    
    # Try to get existing candidate_id if candidate already exists
    candidate_id = None
    if candidate_store.enabled:
        existing_candidate = candidate_store.get_candidate_by_id(thread_id=conversation_id)
        if existing_candidate:
            candidate_id = existing_candidate.get("candidate_id")
    
    # Render analysis result with action flags
    candidate_data = {
        "analysis": analysis_data,
        "chat_id": chat_id,
        "mode": mode,
        "thread_id": conversation_id,  # Store conversation_id in thread_id field for template compatibility
        "conversation_id": conversation_id,
        "candidate_id": candidate_id,  # Include candidate_id if available
        "assistant_id": assistant_id,
        "job_id": job_id,
        "resume_text": resume_text,
        "name": name
    }
    return templates.TemplateResponse("partials/analysis_result.html", {
        "request": request,
        "candidate": candidate_data,
        "assistant_id": assistant_id
    })


@router.post("/save-to-cloud", response_class=JSONResponse)
async def save_candidate_to_cloud(
    mode: str = Form(...),
    conversation_id: str = Form(...),
    chat_id: Optional[str] = Form(None),
    name: str = Form(...),
    job_id: str = Form(...),
    assistant_id: str = Form(...),
    resume_text: str = Form(...),
    analysis: str = Form(...),
):
    """Save candidate record to Zilliz cloud after analysis."""
    # Parse analysis JSON
    try:
        if isinstance(analysis, str):
            analysis_data = json.loads(analysis)
        else:
            analysis_data = analysis
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Invalid analysis JSON"}
        )
    
    # Get job_info to extract job_applied field
    job_info = get_job_by_id(job_id)
    job_applied = job_info.get("position", job_id)
    
    # Prepare candidate data
    # For recommend candidates, chat_id may be None
    # insert_candidate will handle embedding generation and resume truncation
    candidate_data = {
        "chat_id": chat_id,  # Can be None for recommend candidates
        "name": name,
        "job_applied": job_applied,
        "last_message": "",  # No message yet for recommend candidates
        "resume_text": resume_text,
        # resume_vector will be auto-generated by insert_candidate if not provided
        "thread_id": conversation_id,  # Store conversation_id in thread_id field for backward compatibility
        "analysis": analysis_data,
        "stage": analysis_data.get("stage", None),  # Stage determined by analysis
    }
    
    # Save to Zilliz using candidate_store
    # Use upsert_candidate to handle insert/update automatically
    if candidate_store.enabled:
        success = candidate_store.upsert_candidate(**candidate_data)
        if success:
            return JSONResponse(content={"success": True})
        else:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "Failed to save candidate to cloud"}
            )
    else:
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": "Candidate store not enabled"}
        )


@router.post("/generate-message", response_class=HTMLResponse)
async def generate_message(
    mode: str = Form(...),
    chat_id: str = Form(None),
    conversation_id: str = Form(None),
    assistant_id: str = Form(...),
    job_id: str = Form(...),
):
    """Generate message for candidate."""
    
    if not conversation_id:
        return HTMLResponse(
            content='''<div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                <p class="font-bold text-yellow-800 mb-2">⚠️ 无法生成消息</p>
                <p class="text-yellow-700 mb-2">请先获取候选人简历，系统将自动初始化对话线程。</p>
                <p class="text-sm text-yellow-600">步骤：<span class="font-mono">简历标签 → 获取简历按钮 → 等待加载完成 → 返回操作区域</span></p>
            </div>'''
        )
    
    # Get chat history (empty for recommend candidates)
    if mode in ["recommend", "greet"]:
        history = []
    else:
        ok, history = await call_api("GET", f"/chat/{chat_id}/messages")
        if not ok:
            history = []
    
    # Fetch job_info from jobs_store
    job_info = get_job_by_id(job_id)
    
    # Generate message using conversation_id
    # Get the last message from history as input, or use empty string
    input_message = history[-1].get("message", "") if history else ""
    ok, message = await call_api("POST", "/assistant/generate-message", json={
        "conversation_id": conversation_id,
        "input_message": input_message,
        "purpose": "CHAT_ACTION"
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
            <button hx-post="/candidates/send"
                    hx-include="#candidate-context,#message-text"
                    hx-target="body"
                    hx-swap="none"
                    class="flex-1 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700">
                📤 发送消息
            </button>
            <button hx-post="/candidates/pass"
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
        ok, result = await call_api("POST", f"/chat/{chat_id}/send_message", json={"message": message})
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


@router.post("/request-full_resume", response_class=HTMLResponse)
async def request_resume(chat_id: str = Form(...)):
    """Request full resume from candidate."""
    ok, result = await call_api("POST", "/chat/resume/request_full", json={"chat_id": chat_id})
    
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
    mode: str = Form(...),
):
    """Fetch online resume for mode = chat/greet/followup candidate and return textarea."""
    assert mode in ["chat", "greet", "followup"], "mode must be chat, greet, or followup"
    # Call online resume API
    ok, resume_data = await call_api("GET", f"/chat/resume/online/{chat_id}")

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
    mode: str = Form(...),
    index: str = Form(...),
):
    """Fetch resume for recommend candidate and return textarea."""
    assert mode == "recommend", "mode must be recommend"
    index = int(index)
    # Only valid for recommend mode
    if mode != "recommend":
        return HTMLResponse(
            content=f'<div class="text-red-500 p-4">此操作仅适用于推荐候选人。当前模式: {mode or "(空)"}</div>',
            status_code=400
        )
    
    # Parse index - handle empty string or None
    if not index:
        return HTMLResponse(
            content='<div class="text-red-500 p-4">缺少候选人索引(index)</div>',
            status_code=400
        )
    
    # get resume
    ok, resume_data = await call_api("GET", f"/recommend/candidate/{index}/resume")
    
    if not ok:
        return HTMLResponse(
            content='<div class="text-red-500 p-4">无法获取推荐候选人简历</div>',
            status_code=500
        )

    # Always return textarea for automatic workflow
    resume_text = resume_data.get("text", "")
    
    # Automatically call init-chat after loading resume
    # name = form_data.get("name", "推荐候选人")
    # job_id = form_data.get("job_id", "")
    
    # if resume_text and job_id:
    #     # Initialize chat thread
    #     init_data = await prepare_init_chat_data("recommend", None, name, job_id, resume_text)
    #     conversation_id = await call_api("POST", "/assistant/init-chat", json=init_data)
        
    #     if conversation_id:
    #         # Return textarea with conversation_id embedded in data attribute (as thread_id for backward compatibility)
    #         return HTMLResponse(
    #             content=f'<textarea readonly class="w-full h-64 p-4 bg-gray-50 border rounded-lg font-mono text-sm" data-thread-id="{conversation_id}" data-conversation-id="{conversation_id}">{resume_text}</textarea>'
    #         )
    
    # Fallback: return textarea without thread_id if init failed
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
    ok, resume_data = await call_api("GET", f"/chat/resume/full/{chat_id}")

    if not ok:
        return HTMLResponse(
            content='<div class="text-red-500 p-4">无法获取离线简历，可能尚未上传附件简历</div>',
            status_code=500
        )

    # Fetch latest candidate metadata for display
    ok_candidate, candidate_data = await call_api("GET", f"/store/candidate/{chat_id}")
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
    ok, result = await call_api("POST", "/chat/candidate/discard", json={
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
    """Get conversation history HTML.
    
    Note: URL parameter is named 'thread_id' for backward compatibility,
    but it accepts a conversation_id (stored as thread_id field).
    """
    ok, messages = await call_api("GET", f"/assistant/{thread_id}/messages")
    
    if not ok:
        return HTMLResponse(content='<div class="text-red-500">获取历史失败</div>')
    
    # Render conversation history template
    return templates.TemplateResponse("partials/thread_history.html", {
        "request": request,
        "messages": messages,
        "thread_id": thread_id  # Pass as thread_id for template compatibility
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


