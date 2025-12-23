"""Candidate management routes for web UI.
`chat_id` is the id from boss zhipin website, in mode = chat, greet, followup
`index` is the index of the candidate in the recommended list, in mode = recommend
`conversation_id` is from openai responses api, used to continue the conversation from openai
`candidate_id` is the primary key in zilliz cloud object, used to store the candidate data
`job_applied` is the job position title that candidate is applying for, used consistently throughout
"""

import asyncio
from datetime import datetime, timedelta
import json
from typing import Any, Dict, Optional
import difflib
from dateutil import parser as date_parser

from fastapi import APIRouter, BackgroundTasks, Form, Query, Request, Response, Body, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from tenacity import retry, stop_after_attempt, wait_exponential
from src.candidate_store import search_candidates_advanced, get_candidate_by_dict, upsert_candidate, _readable_fields, calculate_resume_similarity
from src.jobs_store import get_all_jobs, get_job_by_id as get_job_by_id_from_store
from src.global_logger import logger
from src import chat_actions, assistant_actions, assistant_utils, recommendation_actions
from src.assistant_actions import send_dingtalk_notification
from src.candidate_stages import STAGE_PASS, STAGE_CHAT, STAGE_SEEK, STAGE_CONTACT
import boss_service

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")
from src.config import get_vercel_config
vercel_url = get_vercel_config().get("url", "").rstrip('/')

def load_jobs() -> list[dict]:
    """Load job configurations from Zilliz Cloud."""
    return get_all_jobs()


def get_job_by_id(job_id: str) -> dict:
    """Get job info by id or position name from Zilliz Cloud."""
    job = get_job_by_id_from_store(job_id)
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
    limit: int = Query(50, description="Limit the number of candidates to return (default: 999)"),
):
    """Get candidate fetched from browser, compare with saved candidates in cloud store, and merge the data when matched

    Supports four modes:
    - recommend: Get recommended candidates from 推荐牛人 page
    - greet: Get new greeting candidates (新招呼, 未读)
    - chat: Get ongoing chat candidates (沟通中, 未读)
    - followup: Get follow-up candidates (沟通中, 牛人已读未回)
    """
    if mode == "recommend":
        # Get job to retrieve candidate_filters (database query, no browser lock needed)
        job = get_job_by_id(job_id)
        
        # Get candidate_filters from job
        candidate_filters = job.get("candidate_filters") if job else None
        
        # Use recommendation_actions directly instead of API call
        # Get page from boss_service
        page = await boss_service.service._ensure_browser_session()
        # Call list_recommended_candidates_action directly
        candidates = await recommendation_actions.list_recommended_candidates_action(
            page=page,
            limit=limit,
            job_applied=job_applied,
            new_only=False,
            filters=candidate_filters
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
                job_applied=job_applied,
                unread_only=False if mode in ["recommend", "followup"] else True,  # True 只看未读,
                random_order=True if mode == "followup" else False # followup mode 需要随机顺序，因为上面的都是最近联系的
            )
        except Exception as e:
            logger.error(f"Failed to get chat candidates: {e}")
            return HTMLResponse(
                content=f'<div class="text-center text-red-500 py-12">获取候选人失败: {str(e)}</div>'
            )
    
    # Return empty HTML if no candidates, let frontend handle the empty state
    if not candidates:
        return HTMLResponse(content='''<div class="text-center text-gray-500 py-12" id="empty-message">
            <p class="text-lg mb-2">📭 暂无候选人</p>
            <p class="text-sm">当前筛选条件下没有找到候选人</p>
            </div>''')
    
    # Batch query candidates from cloud store
    candidate_ids = [c.get("candidate_id") for c in candidates if c.get("candidate_id")]
    chat_ids = [c.get("chat_id") for c in candidates if c.get("chat_id")]
    conversation_ids = [c.get("conversation_id") for c in candidates if c.get("conversation_id")]
    names = [c.get("name") for c in candidates if c.get("name")]
    # Run database query in thread pool to avoid blocking event loop
    fields_to_remove = {"resume_vector", "full_resume", "resume_text"}
    fields = [f for f in _readable_fields if f not in fields_to_remove]
    stored_candidates = search_candidates_advanced(
        candidate_ids= candidate_ids,
        chat_ids= chat_ids,
        conversation_ids= conversation_ids,
        names= names, # if not recommend mode, use ids to search
        job_applied=job_applied,
        limit=len(candidates) * 2,
        strict=False,
        fields=fields,
    )

    # Render candidate cards
    html = ""
    restored = 0
    for i, candidate in enumerate(candidates):
        candidate["mode"] = mode
        candidate["job_id"] = job_id
        # candidate["index"] = i
        candidate["saved"] = False
        # match stored candidate by chat_id, or name + job_applied
        stored_candidate = next((c for c in stored_candidates if \
            c["name"] == candidate['name'] and candidate_matched(candidate, c, mode)), None)

        if stored_candidate:
            candidate.update(stored_candidate) # last_message will be updated by saved candidate
            candidate["saved"] = True
            # Extract score from analysis if available)
            candidate["score"] = stored_candidate.get("analysis", {}).get("overall", None)
            # update greeted status if the candidate is in chat, greet, or seek stage
            candidate['greeted'] = candidate.get('greeted', False)
            # ensure notified field is properly set (default to False if not present)
            candidate['notified'] = candidate.get('notified', False)
            restored += 1
        elif mode in ['chat', 'followup']:
            found_candidates = [c for c in stored_candidates if c['name'] == candidate['name']]
            logger.error(f"Candidate {candidate} \n not matched, found: {json.dumps(found_candidates, indent=2, ensure_ascii=False)}")

        # Extract resume_text and full_resume from candidate
        analysis = candidate.pop("analysis", '')
        resume_text = candidate.pop("resume_text", '')
        full_resume = candidate.pop("full_resume", '')
        metadata = candidate.pop("metadata", {})
        if any(h for h in metadata.get("history", []) if h.get("role") == "assistant"):
            candidate['greeted'] = True
        generated_message = candidate.pop("generated_message", '')
        
        template = templates.get_template("partials/candidate_card.html")
        html += template.render({
            "analysis": analysis,
            "resume_text": resume_text,
            "full_resume": full_resume,
            "metadata": metadata,
            "generated_message": generated_message,
            "candidate": candidate,
            "selected": False
        })
    logger.info(f"Restored {restored}/{len(candidates)} candidates from cloud store")
    return HTMLResponse(content=html)


# ============================================================================
# Candidate detail endpoints
# ============================================================================

@router.get("/detail", response_class=HTMLResponse)
async def get_candidate_detail(request: Request):
    """Get candidate detail view."""
    candidate = json.loads(request.query_params.get('candidate', '{}'))
    chat_id = candidate.get('chat_id')
    # Try to find existing candidate (database query, no browser lock needed)
    stored_candidate = get_candidate_by_dict(candidate, strict=False)
    matched = candidate_matched(candidate, stored_candidate, candidate.get('mode'))
    if matched:
        candidate.update(stored_candidate)
    
    # Prepare template context (pop values before rendering to avoid issues)
    analysis = candidate.pop("analysis", {}) if stored_candidate else {}
    generated_message = candidate.pop("generated_message", '') if stored_candidate else ''
    resume_text = candidate.pop("resume_text", '') if stored_candidate else ''
    full_resume = candidate.pop("full_resume", '') if stored_candidate else ''
    
    # Render template content in thread pool to avoid blocking event loop
    template = templates.get_template("partials/candidate_detail.html")
    html_content = template.render({
        "request": request,
        "analysis": analysis,
        "generated_message": generated_message,
        "resume_text": resume_text,
        "full_resume": full_resume,
        "candidate": candidate,
        "view_mode": "interactive",
    })
    return HTMLResponse(content=html_content)


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
    request: Request,
    mode: str = Form(...),
    chat_id: Optional[str] = Form(None),
    job_id: str = Form(...),
    job_applied: str = Form(...),
    name: str = Form(...),
    last_message: str = Form(...),
    resume_text: str = Form(...),
):
    """Initialize chat thread with proper data preparation.
    1. If in recommend mode, first check if exisiting candidate has been saved before by using semantic search
    2. If not found, create a new candidate record with history or last_message
    """
    # Get all form data as kwargs
    form_data = await request.form()
    kwargs = dict(form_data)
    if mode != "recommend":
        assert chat_id is not None, "chat_id is required for chat mode"
    # check if existing candidate has been saved before by using semantic search
    if not chat_id and resume_text:
        # use semantic search to find existing candidate
        candidate = get_candidate_by_dict(kwargs, strict=True)
        if candidate:
            logger.info(f"Found existing candidate when initializing chat: {candidate.get('candidate_id')} for name: {candidate.get('name')}")
            current = {'chat_id': chat_id, 'job_applied': job_applied, 'resume_text': resume_text}
            updates = {k:v for k, v in candidate.items() if current.get(k) and v != current.get(k)}
            if updates:
                upsert_candidate(candidate_id=candidate.get('candidate_id'), **updates)
            return candidate
    
    if mode == "recommend":
        history = [{'role': 'user', 'content': last_message}]
    else:
        assert chat_id is not None, "chat_id is required for chat mode"
        page = await boss_service.service._ensure_browser_session()
        history = await chat_actions.get_chat_history_action(page, chat_id)
    
    # Get job info
    job_info = get_job_by_id(job_id)
    # Init chat in thread pool to avoid blocking event loop (OpenAI API call)
    result = assistant_actions.init_chat(
        mode=mode,
        name=name,
        job_info=job_info,
        online_resume_text=resume_text,
        chat_history=history,
        chat_id=chat_id,
        kwargs=kwargs,
    )
    assert result.get("conversation_id"), "conversation_id is required"
    assert result.get("candidate_id"), "candidate_id is required"
    return result


@router.post("/analyze")
async def analyze_candidate(
    request: Request,
    mode: str = Form(...),
    chat_id: Optional[str] = Form(None),
    candidate_id: Optional[str] = Form(None),
    conversation_id: str = Form(...),
    job_applied: str = Form(...),
    resume_text: str = Form(None),
    full_resume: str = Form(None),
    name: Optional[str] = Form(None),
):
    """Analyze candidate and return analysis result."""
    if full_resume:
        assert len(full_resume) > 100, f"full_resume is required, but full_resume is:\n {full_resume} "
        logger.debug("Analyzing full resume")
        input_message=f'招聘顾问您好，你帮我分析一下我是否匹配{job_applied}这个岗位？以下是我的完整简历：\n{full_resume}'
    else:
        assert len(resume_text) > 100, f"online resume is required, but online resume is:\n {resume_text} "
        logger.debug("Analyzing online resume")
        input_message=f'招聘顾问您好，你帮我分析一下我是否匹配{job_applied}这个岗位？以下是我的在线简历：\n{resume_text}'
    
    # start analyze - run in thread pool to avoid blocking event loop (OpenAI API call)
    analysis_result = await asyncio.to_thread(
        assistant_actions.generate_message,
        input_message=input_message,
        conversation_id=conversation_id,
        purpose="ANALYZE_ACTION"
    )
    resume_type = "online" if not full_resume else "full"
    analysis_result["resume_type"] = resume_type
    
    # Save analysis (database operation, no browser lock needed)
    upsert_candidate(
        analysis=analysis_result,
        candidate_id=candidate_id,
        chat_id=chat_id,
        mode=mode,
        conversation_id=conversation_id,
        job_applied=job_applied,
        name=name,
    )
    return await _render_analysis_result(request, analysis_result)

@router.post("/render-analysis-result")
async def render_analysis_result(request: Request) -> HTMLResponse:
    """Render analysis result HTML."""
    form = await request.form()
    analysis = json.loads(form.get("analysis", '{}'))
    return await _render_analysis_result(request, analysis)

async def _render_analysis_result(request: Request, analysis: dict) -> HTMLResponse:
    """Internal helper to render analysis result HTML."""
    return templates.TemplateResponse("partials/analysis_result.html", {
        "request": request,
        "analysis": analysis,
    })

@router.post("/save")
async def save_candidate_to_cloud(request: Request):
    """Save candidate record to Zilliz cloud using all form data."""
    # Parse form data
    kwargs = await request.json()
    assert kwargs, "kwargs is empty"
    # update candidate passes all relevant kwargs (database operation, no browser lock needed)
    candidate_id = upsert_candidate(**kwargs)
    return candidate_id


@router.post("/generate-message", response_class=HTMLResponse)
async def generate_message(
    request: Request,
    name: str = Form(...),
    mode: str = Form(...),
    candidate_id: str = Form(...),
    chat_id: Optional[str] = Form(None),
    conversation_id: str = Form(...),
    purpose: str = Form(...),
    force: bool = Form(False),
    index: Optional[int] = Form(None),
):
    """Generate message for candidate. Requires conversation_id to be initialized first."""
    # { "type": "candidate/recruiter", "timestamp": "2025-11-10 10:00:00", "message": "你好，我叫张三", "status": "未读" }
    page = await boss_service.service._ensure_browser_session()
    stored_candidate = get_candidate_by_dict({"candidate_id": candidate_id, "chat_id": chat_id}, strict=False) or {}
    last_message = None
    # Get chat history from browser to decide whether we have new user messages to respond to.
    if mode == "recommend":
        new_user_messages = [{"content": "请问你有什么问题可以让我进一步解答吗？", "role": "user"}]
        chat_history = new_user_messages
    else:
        if not chat_id:
            raise RuntimeError("No chat_id provided for chat mode")
        new_user_messages = []
        chat_history = await chat_actions.get_chat_history_action(page, chat_id)
        for msg in chat_history[::-1]:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role == "assistant":
                if not content.startswith("方便发一份简历过来吗"):
                    last_message = msg
                    break
            elif role == "user":
                new_user_messages.insert(0, {"content": content, "role": role})
    # if new_user_messages is None, return it
    should_generate = bool(new_user_messages) or purpose == "FOLLOWUP_ACTION" or force
    if not should_generate:
        return templates.TemplateResponse(
            "partials/message_result.html",
            {"request": request, **last_message},
        )

    generated = await asyncio.to_thread(
        assistant_actions.generate_message,
        input_message=new_user_messages or "[沉默]",
        conversation_id=conversation_id,
        purpose=purpose,
    )
    logger.debug("Generated message: %s", generated)
    action = generated.get("action", "")
    reason = generated.get("reason", "")
    message_text = generated.get("message", "")

    generated_history_item: dict[str, Any] = {
        "role": "assistant",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "content": message_text,
        "payload": generated,
        "action": action,
        "reason": reason,
    }
    # update candidate data
    updates: dict[str, Any] = {
        "candidate_id": candidate_id,
        "chat_id": chat_id,
        "mode": mode,
        "conversation_id": conversation_id,
        "metadata": {"history": chat_history + [generated_history_item]},
        "generated_message": message_text,
    }
    upsert_candidate(**updates)
    # return message result
    return templates.TemplateResponse(
        "partials/message_result.html",
        {"request": request, "message": message_text, "action": action, "reason": reason, "payload": generated},
    )

@router.post("/should-reply")
async def should_reply(
    chat_id: Optional[str] = Body(None),
    mode: Optional[str] = Body(None),
) -> JSONResponse:
    """Check if should generate message based on chat history.
    If last message is an assistant message, return False, otherwise return True.
    
    Args:
        chat_id: Chat ID to get chat history from browser
        mode: Mode (recommend/chat/greet/followup), if recommend mode, return True
    
    Returns:
        JSONResponse with {"should_reply": bool}
    """
    # For recommend mode, always return True (no chat history available)
    if mode == "recommend":
        return JSONResponse({"should_reply": True})
    
    # if chat_id is not provided, return True (default to reply)
    if not chat_id:
        return JSONResponse({"should_reply": True})
    
    # Get chat history from browser
    page = await boss_service.service._ensure_browser_session()
    chat_history = await chat_actions.get_chat_history_action(page, chat_id)
    
    # Check last message role
    message = ''
    for msg in chat_history[::-1]:
        role = msg.get("role")
        if role == "assistant":
            return JSONResponse({"should_reply": False})
        elif role == "user":
            message += msg.get("content", '')
            if len(message) > 5:# ignore short messages from user
                return JSONResponse({"should_reply": True})
    
    # no message found, or only developer message, return False
    return JSONResponse({"should_reply": False})

@router.post("/send", response_class=HTMLResponse)
async def send_message(
    mode: str = Form(...),
    chat_id: Optional[str] = Form(None),
    index: Optional[int] = Form(None),
    message: str = Form(...),
):
    """Send message to candidate."""
    if not message:
        return HTMLResponse(
            content='',
            status_code=200,
            headers={"HX-Trigger": json.dumps({"showToast": {"message": "消息不能为空", "type": "error"}}, ensure_ascii=True)}
        )
    page = await boss_service.service._ensure_browser_session()
    
    if mode == "recommend" and index is not None:
        result = await recommendation_actions.greet_recommend_candidate_action(page, index, message)
    elif chat_id:
        result = await chat_actions.send_message_action(page, chat_id, message)
    else:
        return HTMLResponse(
            content='',
            status_code=400,
            headers={"HX-Trigger": json.dumps({"showToast": {"message": "缺少候选人ID", "type": "error"}}, ensure_ascii=True)}
        )
    
    if result:
        return HTMLResponse(
            content='',
            status_code=200,
            headers={"HX-Trigger": json.dumps({"showToast": {"message": f"消息发送成功:\n {message}", "type": "success"}}, ensure_ascii=True)}
        )
    else:
        return HTMLResponse(
            content='',
            status_code=500,
            headers={"HX-Trigger": json.dumps({"showToast": {"message": "发送失败", "type": "error"}}, ensure_ascii=True)}
        )

#--------------------------------------------------
# DingTalk Notification
#--------------------------------------------------

@router.post("/notify")
async def notify_hr(
    analysis: dict = Body(...),
    job_id: Optional[str] = Body(None),
    chat_id: Optional[str] = Body(None),
    conversation_id: Optional[str] = Body(None),
    candidate_id: Optional[str] = Body(None),
    name: Optional[str] = Body(None),
    job_applied: Optional[str] = Body(None),
):
    """Send DingTalk notification to HR."""
    # Double check if candidate has already been notified
    candidate = get_candidate_by_dict({
        "chat_id": chat_id,
        "conversation_id": conversation_id,
        "candidate_id": candidate_id,
        "job_id": job_id,
    })
    
    # Skip if already notified
    if candidate.get("notified"):
        return {"success": False, "error": "该候选人已发送过通知，避免重复发送"}
    
    # Generate message from analysis if not provided
    name = candidate.get("name") or name or "未知候选人"
    job_applied = candidate.get("job_applied") or job_applied or "未指定岗位"
    resume_type = '完整简历' if analysis.get('resume_type') == 'full' else '在线简历'
    
    # Get Vercel URL and generate candidate detail link
    candidate_id = candidate.get('candidate_id')
    candidate_link = f"{vercel_url}/candidate/{candidate_id}" if vercel_url and candidate_id else ""
    
    message = f"""**候选人**: {name}
**岗位**: {job_applied}

**评分结果（{resume_type}）**:
- 技能匹配度: {analysis.get('skill', 'N/A')}/10
- 创业契合度: {analysis.get('startup_fit', 'N/A')}/10
- 基础背景: {analysis.get('background', 'N/A')}/10
- **综合评分: {analysis.get('overall', 'N/A')}/10**

**分析总结**:
{analysis.get('summary', '暂无')}

**跟进建议**:
{analysis.get('followup_tips', '暂无')}"""
    
    # Add candidate detail link if available
    if candidate_link:
        message += f"\n\n[查看候选人详情]({candidate_link})"
    
    title = f"候选人 {name} 通过筛选（{resume_type}）"
    
    # Send notification with job_id support
    success = send_dingtalk_notification(title=title, message=message, job_id=job_id)
    
    if success:
        # Update candidate's notified field after successful notification
        upsert_candidate(candidate_id=candidate.get('candidate_id'), notified=True)
        return {"success": True, "message": "通知发送成功"}
    else:
        return {"success": False, "error": "通知发送失败"}

@router.post("/fetch-online-resume", response_class=HTMLResponse)
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def fetch_online_resume(
    name: str = Form(...),
    job_applied: str = Form(...),
    mode: str = Form(...),
    chat_id: Optional[str] = Form(None),
    index: Optional[int] = Form(None),
    conversation_id: Optional[str] = Form(None),
    candidate_id: Optional[str] = Form(None),
):
    """Fetch online resume for both chat/greet/followup and recommend candidates.
    
    For chat/greet/followup modes: requires chat_id, uses chat_actions
    For recommend mode: requires index, uses recommendation_actions
    """
    page = await boss_service.service._ensure_browser_session()
    
    if mode == "recommend":
        if index is None:
            return HTMLResponse(
                content='<div class="text-red-500 p-4">推荐模式需要提供 index 参数</div>',
                status_code=400
            )
        resume_text = await recommendation_actions.view_recommend_candidate_resume_action(page, index)
        resume_text = resume_text.get("text")
        
    else:
        if chat_id is None:
            return HTMLResponse(
                content='<div class="text-red-500 p-4">沟通模式需要提供 chat_id 参数</div>',
                status_code=400
            )
        resume_text = await chat_actions.view_online_resume_action(page, chat_id)
        resume_text = resume_text.get("text")

    # save resume text to background
    if resume_text and len(resume_text) > 100:
        if candidate_id: # only update resume_text if candidate_id is provided (initiated), otherwise wait for init-chat to create candidate_id
            upsert_candidate(
                resume_text=resume_text,
                chat_id=chat_id,
                conversation_id=conversation_id,
                candidate_id=candidate_id,
                mode=mode,
                name=name,
                job_applied=job_applied,
            )
        return HTMLResponse(
            content=f'<textarea id="resume-textarea-online" readonly class="w-full h-64 p-2 bg-gray-50 border rounded-lg font-mono text-sm">{resume_text}</textarea>'
        )
    else:
        return HTMLResponse(
            # content='<div class="text-red-500 p-4">暂无在线简历，请先请求在线简历</div>',
            content=f'<textarea id="resume-textarea-online" readonly class="w-full h-64 p-2 bg-gray-50 border rounded-lg font-mono text-sm text-red-500">暂无在线简历，请先请求在线简历</textarea>'
        )


@router.post("/fetch-full-resume", response_class=HTMLResponse)
async def fetch_full_resume(
    request: Request,
):
    """Explicitly fetch full/offline resume (not online resume)."""
    form_data = await request.form()
    candidate_id = form_data.get("candidate_id")
    chat_id = form_data.get("chat_id")
    mode = form_data.get("mode")
    job_id = form_data.get("job_id")
    # Only for chat/greet/followup modes, not recommend
    if mode == "recommend":
        return HTMLResponse(
            content='<div class="text-red-500 p-4">推荐候选人不支持离线简历</div>',
            status_code=400
        )
    
    # check if requested
    request = True
    candidate = get_candidate_by_dict({"candidate_id": candidate_id, "chat_id": chat_id}, strict=False)
    if history:=candidate.get("metadata", {}).get("history"):
        if any(h for h in history if h.get("role") == "developer" and h.get("content") == "简历请求已发送"):
            requested = False
    
    # Try to get full resume only
    page = await boss_service.service._ensure_browser_session()
    result = await chat_actions.view_full_resume_action(page, chat_id, request)
    full_resume_text = result.get("text")
    requested = result.get("requested")
    
    if full_resume_text and len(full_resume_text) > 100:
        upsert_candidate(
            candidate_id=candidate_id,
            full_resume=full_resume_text,
            chat_id=chat_id,
            mode=mode
        )
        return HTMLResponse(
            content=f'<textarea id="resume-textarea-full" readonly class="w-full h-64 p-2 bg-gray-50 border rounded-lg font-mono text-sm">{full_resume_text}</textarea>'
        )
    elif requested:
        return HTMLResponse(
            content='<div class="text-green-500 p-4">已向候选人请求完整简历，请稍后检查完整简历是否存在</div>',
        )
    else:
        return HTMLResponse(
            content='<div class="text-red-500 p-4">暂无完整简历，请先请求完整简历</div>',
        )


@router.post("/pass")
async def pass_candidate(
    mode: str = Body(...),
    index: int = Body(None),
    chat_id: str = Body(None),
    candidate_id: str = Body(...),
):
    """Mark candidate as PASS and move to next."""
    page = await boss_service.service._ensure_browser_session()
    if mode == "recommend":
        result = await recommendation_actions.pass_recommend_candidate_action(page, index)
    else:
        result = await chat_actions.discard_candidate_action(page, chat_id)
    
    if result:
        return {"success": True, "message": "已标记为 PASS"}
    else:
        raise HTTPException(status_code=500, detail="PASS 操作失败")


@router.post("/request-contact")
async def request_contact(
    chat_id: str = Body(...),
    candidate_id: Optional[str] = Body(None),
):
    """Request contact information (phone and WeChat) from a candidate and store in metadata."""
    page = await boss_service.service._ensure_browser_session()
    candidate = get_candidate_by_dict({"candidate_id": candidate_id, "chat_id": chat_id}, strict=False)
    if history:=candidate.get("metadata", {}).get("history"):
        if any(h for h in history if h.get("role") == "developer" and h.get("content") == "请求交换联系方式已发送"):
            phone_number = history.get("phone_number")
            wechat_number = history.get("wechat_number")
            return JSONResponse({
                "success": True,
                "phone_number": phone_number,
                "wechat_number": wechat_number,
                "clicked_phone": False,
                "clicked_wechat": False,
            })
    # Call request_contact_action to get contact info
    contact_result = await chat_actions.request_contact_action(page, chat_id)
    
    # Extract phone_number and wechat_number
    phone_number = contact_result.get("phone_number")
    wechat_number = contact_result.get("wechat_number")
    
    # Find the candidate by candidate_id or chat_id
    
    # Update candidate metadata with contact info
    # metadata merging is now handled in upsert_candidate()
    if candidate:
        upsert_candidate(
            candidate_id=candidate.get("candidate_id"),
            chat_id=chat_id,
            metadata={
                "phone_number": phone_number,
                "wechat_number": wechat_number,
            },
            stage=STAGE_CONTACT,
        )
        
        return JSONResponse({
            "success": True,
            "phone_number": phone_number,
            "wechat_number": wechat_number,
            "clicked_phone": contact_result.get("clicked_phone", False),
            "clicked_wechat": contact_result.get("clicked_wechat", False),
        })
    else:
        # Candidate not found, but still return the contact info
        logger.warning(f"Candidate not found for chat_id: {chat_id}, candidate_id: {candidate_id}")
        return JSONResponse({
            "success": False,
            "error": "Candidate not found",
            "phone_number": phone_number,
            "wechat_number": wechat_number,
            "clicked_phone": contact_result.get("clicked_phone", False),
            "clicked_wechat": contact_result.get("clicked_wechat", False),
        })


# Record Reuse Endpoints
@router.get("/thread-history/{conversation_id}", response_class=HTMLResponse)
async def get_thread_history(
    request: Request,
    conversation_id: str
):
    """Get conversation history HTML.
    
    Args:
        conversation_id: OpenAI conversation ID
    """
    # Get conversation messages in thread pool to avoid blocking event loop (OpenAI API call)
    messages_data = await asyncio.to_thread(
        assistant_utils.get_conversation_messages,
        conversation_id
    )
    
    return templates.TemplateResponse("partials/thread_history.html", {
        "request": request,
        "messages": messages_data.get("messages", []),
        "conversation_id": conversation_id
    })


# Utils Functions
def candidate_matched(candidate: Dict[str, Any], stored_candidate: Dict[str, Any], mode: str) -> bool:
    """Check if candidate is matched with stored candidate."""
    if not stored_candidate:
        return False
    if candidate['name'] != stored_candidate['name']:
        return False
    # check chat_id if provided
    chat_id, chat_id2 = candidate.get("chat_id"), stored_candidate.get("chat_id")
    if chat_id and chat_id2:
        if chat_id == chat_id2:
            return True
        else:
            return False
    # check by last_message if provided
    last_message, last_message2 = candidate.get("last_message", ''), stored_candidate.get("last_message", '')
    updated_at = date_parser.parse(stored_candidate.get("updated_at"))
    if updated_at.tzinfo is not None:
        updated_at = updated_at.replace(tzinfo=None)
    if chat_id is None and chat_id2 and updated_at < (datetime.now() - timedelta(days=3)):
        logger.info(f"there should be no chat_id in recommend mode, current candidate:\n{candidate.get('name')}<->{stored_candidate.get('name')}: chat_id: {chat_id2}")
        return False
    elif mode == "recommend" and last_message and last_message2:
        from difflib import SequenceMatcher
        similarity = SequenceMatcher(lambda x: x in ['\n', '\r', '\t', ' '], last_message, last_message2).ratio()
        if similarity < 0.8:
            logger.debug(f"last_message similarity ({candidate['name']}): {similarity*100:.2f}% < 90%\n{last_message}\n != \n{last_message2}")
            return False
    return True
