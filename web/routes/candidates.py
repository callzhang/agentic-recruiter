"""Candidate management routes for web UI.
`chat_id` is the id from boss zhipin website, in mode = chat, greet, followup
`index` is the index of the candidate in the recommended list, in mode = recommend
`conversation_id` is from openai responses api, used to continue the conversation from openai
`candidate_id` is the primary key in zilliz cloud object, used to store the candidate data
`job_applied` is the job position title that candidate is applying for, used consistently throughout
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from src.candidate_store import get_candidates, get_candidate_id_by_dict, upsert_candidate
from src.config import settings
from src.jobs_store import jobs_store
from src.global_logger import logger    
from src import chat_actions, assistant_actions, assistant_utils, recommendation_actions
import boss_service

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


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
async def list_candidates(
    request: Request,
    mode: str = Query("chat", description="Mode: recommend, greet, chat, or followup"),
    job_applied: str = Query(..., description="Job position filter (required)"),
    job_id: str = Query(..., description="Job ID filter (required)"),
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
        job = get_job_by_id(job_id)
        
        # Get candidate_filters from job
        candidate_filters = job.get("candidate_filters") if job else None
        
        # Use recommendation_actions directly instead of API call
        try:
            # Get page from boss_service
            page = await boss_service.service._ensure_browser_session()
            # Call list_recommended_candidates_action directly
            candidates = await recommendation_actions.list_recommended_candidates_action(
                page=page,
                limit=limit,
                job_title=job_applied,
                new_only=False,
                filters=candidate_filters
            )
        except Exception as e:
            logger.error(f"Failed to get recommended candidates: {e}")
            return HTMLResponse(
                content=f'<div class="text-center text-red-500 py-12">获取推荐牛人失败: {str(e)}</div>'
            )
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
        
        # Use chat_actions directly instead of API call
        try:
            # Get page from boss_service
            page = await boss_service.service._ensure_browser_session()
            # Call list_conversations_action directly
            candidates = await chat_actions.list_conversations_action(
                page=page,
                limit=limit,
                tab=tab_filter,
                status=status_filter,
                job_title=job_applied,
                unread_only=False  # new_only=False maps to unread_only=False
            )
        except Exception as e:
            logger.error(f"Failed to get chat candidates: {e}")
            return HTMLResponse(
                content=f'<div class="text-center text-red-500 py-12">获取候选人失败: {str(e)}</div>'
            )
    
    # Return empty list if no candidates, let frontend handle the empty state
    if not candidates:
        return []
    
    # Batch query candidates from cloud store
    identifiers = [c["chat_id"] for c in candidates if c.get("chat_id")]
    identifiers += [c["candidate_id"] for c in candidates if c.get("candidate_id")]
    identifiers += [c["conversation_id"] for c in candidates if c.get("conversation_id")]
    names: list[str] = [c["name"] for c in candidates if c.get("name")]
    job_applied = candidates[0].get("job_applied")
    # Check if candidate is saved to cloud using batch query results
    stored_candidates = get_candidates(identifiers=identifiers, names=names, job_applied=job_applied)
    
    # Render candidate cards
    html = ""
    for i, candidate in enumerate(candidates):
        # Add mode to candidate data for detail view routing
        candidate["mode"] = mode
        candidate["job_id"] = job_id
        candidate["index"] = i
        candidate["saved"] = False
        # match stored candidate by chat_id, or name + job_applied
        stored_candidate = next((c for c in stored_candidates if \
            (candidate.get("chat_id") and c.get("chat_id") == candidate.get("chat_id")) or\
            (c.get("name") == candidate.get("name")) and c.get("job_applied") == candidate.get("job_applied")), None)
        
        
        if stored_candidate:
            candidate.update(stored_candidate)
            candidate["conversation_id"] = stored_candidate.get("conversation_id")
            candidate["saved"] = True
            # Extract score from analysis if available
            analysis = stored_candidate.get("analysis")
            if analysis and isinstance(analysis, dict):
                candidate["score"] = analysis.get("overall", None)
        
        html += templates.get_template("partials/candidate_card.html").render({
            "candidate": candidate,
            "selected": False
        })
    
    return HTMLResponse(content=html)


# ============================================================================
# Candidate detail endpoints
# ============================================================================

@router.get("/detail", response_class=HTMLResponse)
async def get_candidate_detail(request: Request):
    """Get candidate detail view."""
    # Parse index if provided
    data = dict(request.query_params)
    if not data:
        form_data = await request.form()
        data = dict(form_data)
    data = {k:v for k, v in data.items() if v}
    # Try to find existing candidate
    results = get_candidates(
        identifiers=[data.get('candidate_id'), data.get('chat_id'), data.get('conversation_id')], 
        names=[data.get('name')], 
        job_applied=data.get('job_applied'), 
        limit=1
    )
    candidate_data = results[0] if results else {}
    candidate_data = {k:v for k, v in candidate_data.items() if v}
    data.update(candidate_data)
    data['score'] = candidate_data.get("analysis", {}).get("overall")
    
    return templates.TemplateResponse("partials/candidate_detail.html", {
        "request": request,
        "candidate": data,
        "generated_message": data.get("last_message"),
    })


@router.get("/history/{candidate_id}", response_class=HTMLResponse)
async def get_candidate_history(candidate_id: str):
    """Get chat history for a candidate."""
    page = await boss_service.service._ensure_browser_session()
    history = await chat_actions.get_chat_history_action(page, candidate_id)
    
    if not isinstance(history, list):
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
    job_info = get_job_by_id(job_id)
    conversation_id = assistant_actions.init_chat(
        mode=mode,
        chat_id=chat_id,
        job_info=job_info,
        name=name,
        resume_text=resume_text
    )
    
    return JSONResponse(content={
        "conversation_id": conversation_id,
        "success": True
    })


@router.post("/analyze", response_class=HTMLResponse)
async def analyze_candidate(
    request: Request,
    mode: str = Form(...),
    chat_id: Optional[str] = Form(None),
    conversation_id: str = Form(...),
    job_applied: str = Form(...),
    # resume_text: str = Form(...),
    name: Optional[str] = Form(None),
):
    """Analyze candidate and return analysis result."""
    analysis_result = assistant_actions.generate_message(
        input_message='你看我是否匹配{job_applied}这个岗位？',
        conversation_id=conversation_id,
        purpose="ANALYZE_ACTION"
    )
    
    analysis_data = json.loads(analysis_result) if isinstance(analysis_result, str) else analysis_result
    analysis_data["action_flags"] = {}
    
    # Get candidate_id if exists
    candidate_id = get_candidate_id_by_dict({"conversation_id": conversation_id, "job_applied": job_applied, "name": name})
    
    candidate_data = {
        "analysis": analysis_data,
        "chat_id": chat_id,
        "mode": mode,
        "conversation_id": conversation_id,
        "candidate_id": candidate_id,
        "job_applied": job_applied,
        "name": name
    }
    
    return templates.TemplateResponse("partials/analysis_result.html", {
        "request": request,
        "candidate": candidate_data,
    })


@router.post("/save-to-cloud", response_class=JSONResponse)
async def save_candidate_to_cloud(request: Request):
    """Save candidate record to Zilliz cloud using all form data."""
    # Parse form data
    form_data = await request.form()
    kwargs = dict(form_data)
    
    # Parse analysis back to dict if sent as JSON string
    analysis = kwargs.get("analysis")
    if analysis and isinstance(analysis, str):
        kwargs["analysis"] = json.loads(analysis)
    # Only require job_applied and at least one ID
    assert 'job_applied' in kwargs, "job_applied is required"

    # update candidate passes all relevant kwargs
    candidate_id = upsert_candidate(**kwargs)
    return JSONResponse(content={
        "candidate_id": candidate_id,
        "success": True
    })


@router.post("/generate-message", response_class=HTMLResponse)
async def generate_message(
    mode: str = Form(...),
    chat_id: Optional[str] = Form(None),
    index: Optional[int] = Form(None),
    conversation_id: str = Form(...),
    purpose: str = Form(...)
):
    """Generate message for candidate."""
    # Get chat history
    default_user_message = {"content": f"请问你有什么问题可以让我进一步解答吗？", "role": "user"}
    history = []
    last_assistant_message = None
    page = await boss_service.service._ensure_browser_session()
    # { "type": "candidate/recruiter", "timestamp": "2025-11-10 10:00:00", "message": "你好，我叫张三", "status": "未读" }
    if mode == "recommend":
        # assert index is not None, "index is required for recommend mode"
        # result = await recommendation_actions.get_recommend_history_action(page, index) # no history
        history = [default_user_message]
    else:
        assert chat_id is not None, "chat_id is required for chat mode"
        result = await chat_actions.get_chat_history_action(page, chat_id)
        for msg in result[::-1]:
            content = f'{msg.get("timestamp")}: {msg.get("message")}'
            type = {"candidate": "user", "recruiter": "assistant", "system": "developer"}.get(msg.get("type"))
            if type == "assistant":
                last_assistant_message = msg.get("message")
                break
            else:
                history.insert(0, {"content": content, "role": type})
    
    # generate message if history is not empty
    if history:
        # Generate message
        message = assistant_actions.generate_message(
            input_message=history,
            conversation_id=conversation_id,
            purpose=purpose
        )
        logger.debug("Generated message: %s", message)
    else:
        logger.warning("No new message found for conversation_id: %s", conversation_id)
        message = last_assistant_message
    # Return textarea with generated message and send button
    html = f'''
    <div class="space-y-4">
        <textarea id="message-text" name="message" class="w-full h-32 p-4 border rounded-lg">{message}</textarea>
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
    page = await boss_service.service._ensure_browser_session()
    
    if mode == "recommend" and index is not None:
        result = await recommendation_actions.greet_recommend_candidate_action(page, index, message)
    elif chat_id:
        result = await chat_actions.send_message_action(page, chat_id, message)
    else:
        return HTMLResponse(
            content='',
            status_code=400,
            headers={"HX-Trigger": '{"showToast": {"message": "缺少候选人ID", "type": "error"}}'}
        )
    
    if result:
        return HTMLResponse(
            content='',
            status_code=200,
            headers={"HX-Trigger": json.dumps({"showToast": {"message": "消息发送成功！", "type": "success"}})}
        )
    else:
        return HTMLResponse(
            content='',
            status_code=500,
            headers={"HX-Trigger": json.dumps({"showToast": {"message": "发送失败", "type": "error"}})}
        )


@router.post("/request-full_resume", response_class=HTMLResponse)
async def request_resume(chat_id: str = Form(...)):
    """Request full resume from candidate."""
    page = await boss_service.service._ensure_browser_session()
    result = await chat_actions.request_full_resume_action(page, chat_id)
    resume_text = resume_text.get("text")
    if result:
        return HTMLResponse(content='<div class="text-green-600 p-4">✅ 简历请求已发送</div>')
    else:
        return HTMLResponse(content='<div class="text-red-500 p-4">❌ 请求失败</div>', status_code=500)


@router.post("/fetch-online-resume", response_class=HTMLResponse)
async def fetch_online_resume(
    chat_id: str = Form(...),
    mode: str = Form(...),
):
    """Fetch online resume for mode = chat/greet/followup candidate and return textarea."""
    page = await boss_service.service._ensure_browser_session()
    resume_text = await chat_actions.view_online_resume_action(page, chat_id)
    resume_text = resume_text.get("text")
    return HTMLResponse(
        content=f'<textarea readonly class="w-full h-64 p-4 bg-gray-50 border rounded-lg font-mono text-sm">{resume_text}</textarea>'
    )


@router.post("/fetch-recommend-resume", response_class=HTMLResponse)
async def fetch_recommend_resume(
    index: int = Form(...),
):
    """Fetch resume for recommend candidate and return textarea."""
    page = await boss_service.service._ensure_browser_session()
    resume_text = await recommendation_actions.view_recommend_candidate_resume_action(page, index)
    resume_text = resume_text.get("text")
    return HTMLResponse(
        content=f'<textarea readonly class="w-full h-64 p-4 bg-gray-50 border rounded-lg font-mono text-sm">{resume_text}</textarea>'
    )


@router.post("/fetch-full-resume", response_class=HTMLResponse)
async def fetch_full_resume(
    request: Request,
    chat_id: str = Form(...),
    mode: str = Form("chat"),
    job_id: str = Form(""),
):
    """Explicitly fetch full/offline resume (not online resume)."""
    # Only for chat/greet/followup modes, not recommend
    if mode not in ["chat", "greet", "followup"]:
        return HTMLResponse(
            content='<div class="text-red-500 p-4">推荐候选人不支持离线简历</div>',
            status_code=400
        )
    
    # Try to get full resume only
    page = await boss_service.service._ensure_browser_session()
    resume_text = await chat_actions.get_full_resume_action(page, chat_id)

    # Fetch latest candidate metadata for display
    results = get_candidates(identifiers=[chat_id], limit=1)
    candidate_data = results[0] if results else {"chat_id": chat_id}

    # Re-render detail with full resume
    candidate_data.update({
        "chat_id": chat_id,
        "resume_text": resume_text,
        "full_resume": resume_text,
        "mode": mode
    })

    # Default threshold values (no longer fetched from assistant metadata)
    threshold_chat = 5.0
    threshold_borderline = 7.0
    threshold_seek = 9.0

    return templates.TemplateResponse("partials/candidate_detail.html", {
        "request": request,
        "candidate": candidate_data,
        "job_id": job_id,
        "generated_message": None,
        "threshold_chat": threshold_chat,
        "threshold_borderline": threshold_borderline,
        "threshold_seek": threshold_seek
    })


@router.post("/pass", response_class=HTMLResponse)
async def pass_candidate(chat_id: str = Form(...)):
    """Mark candidate as PASS and move to next."""
    page = await boss_service.service._ensure_browser_session()
    result = await chat_actions.discard_candidate_action(page, chat_id, stage="PASS")
    
    if result:
        return HTMLResponse(
            content='<div class="text-green-600">✅ 已标记为 PASS</div>',
            headers={"HX-Trigger": "candidateUpdated"}
        )
    else:
        return HTMLResponse(
            content='<div class="text-red-500">❌ 操作失败</div>',
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



@router.get("/thread-history/{conversation_id}", response_class=HTMLResponse)
async def get_thread_history(
    request: Request,
    conversation_id: str
):
    """Get conversation history HTML.
    
    Args:
        conversation_id: OpenAI conversation ID
    """
    messages_data = assistant_utils.get_conversation_messages(conversation_id)
    
    return templates.TemplateResponse("partials/thread_history.html", {
        "request": request,
        "messages": messages_data.get("messages", []),
        "conversation_id": conversation_id
    })
