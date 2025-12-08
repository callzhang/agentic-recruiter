"""Candidate management routes for web UI.
`chat_id` is the id from boss zhipin website, in mode = chat, greet, followup
`index` is the index of the candidate in the recommended list, in mode = recommend
`conversation_id` is from openai responses api, used to continue the conversation from openai
`candidate_id` is the primary key in zilliz cloud object, used to store the candidate data
`job_applied` is the job position title that candidate is applying for, used consistently throughout
"""

from datetime import datetime
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Form, Query, Request, Response, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from tenacity import retry, stop_after_attempt, wait_exponential
from src.candidate_store import search_candidates_advanced, get_candidate_by_dict, upsert_candidate
from src.jobs_store import get_all_jobs, get_job_by_id as get_job_by_id_from_store
from src.global_logger import logger
from src import chat_actions, assistant_actions, assistant_utils, recommendation_actions
from src.assistant_actions import send_dingtalk_notification
import boss_service

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


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
                job_applied=job_applied,
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
            status_filter = "全部" #"未读"
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
                unread_only=False  # new_only=False maps to unread_only=False
            )
        except Exception as e:
            logger.error(f"Failed to get chat candidates: {e}")
            return HTMLResponse(
                content=f'<div class="text-center text-red-500 py-12">获取候选人失败: {str(e)}</div>'
            )
    
    # Return empty HTML if no candidates, let frontend handle the empty state
    if not candidates:
        return HTMLResponse(content='<div class="text-center text-gray-500 py-12">暂无候选人</div>')
    
    # Batch query candidates from cloud store
    candidate_ids: list[str] = []
    chat_ids: list[str] = []
    conversation_ids: list[str] = []
    names: list[str] = []
    for c in candidates:
        if c.get("candidate_id"):
            candidate_ids.append(c["candidate_id"])
        if c.get("chat_id"):
            chat_ids.append(c["chat_id"])
        if c.get("conversation_id"):
            conversation_ids.append(c["conversation_id"])
        if c.get("name"):
            names.append(c["name"])
    stored_candidates = search_candidates_advanced(
        candidate_ids=list({cid for cid in candidate_ids}),
        chat_ids=list({cid for cid in chat_ids}),
        conversation_ids=list({cid for cid in conversation_ids}),
        names=list({n for n in names}),
        job_applied=job_applied,
        limit=len(candidates) * 2,
        strict=False,
    )

    # Render candidate cards
    html = ""
    restored = 0
    for i, candidate in enumerate(candidates):
        candidate["mode"] = mode
        candidate["job_id"] = job_id
        candidate["index"] = i
        candidate["saved"] = False
        # match stored candidate by chat_id, or name + job_applied
        stored_candidate = next((c for c in stored_candidates if \
            (candidate.get("chat_id") and c.get("chat_id") == candidate.get("chat_id") and c.get('name') == candidate.get('name')) or\
            (c.get("name") == candidate.get("name")) and c.get("job_applied") == candidate.get("job_applied")), None)
        
        if stored_candidate:
            chat_id, chat_id2 = candidate.get("chat_id"), stored_candidate.get("chat_id")
            if chat_id and chat_id2 and chat_id != chat_id2:
                logger.warning(f"chat_id mismatch ({candidate['name']}): {chat_id} != {chat_id2}")
                stored_candidate = {}
            candidate.update(stored_candidate) # last_message will be updated by saved candidate
            candidate["saved"] = True
            # Extract score from analysis if available)
            candidate["score"] = stored_candidate.get("analysis", {}).get("overall", None)
            # update greeted status if the candidate is in chat, greet, or seek stage
            candidate['greeted'] = candidate.get('greeted', False)
            restored += 1

        # Extract resume_text and full_resume from candidate
        html += templates.get_template("partials/candidate_card.html").render({
            "analysis": candidate.pop("analysis", ''),
            "resume_text": candidate.pop("resume_text", ''),
            "full_resume": candidate.pop("full_resume", ''),
            "metadata": candidate.pop("metadata", {}),
            "generated_message": candidate.pop("generated_message", ''),
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
    # Parse index if provided
    # str2bool = lambda v: {'true': True, 'false': False}.get(v, v)
    # candidate = dict(request.query_params)
    # candidate = {k:str2bool(v) for k, v in candidate.items() if v}
    candidate = json.loads(request.query_params.get('candidate', '{}'))
    # Try to find existing candidate
    stored_candidate = get_candidate_by_dict(candidate, strict=False)
    if stored_candidate and candidate['name'] != stored_candidate.get('name'):
        logger.warning(f"name mismatch: {candidate.get('name')} != {stored_candidate.get('name')}")
    if candidate.get('chat_id') and stored_candidate.get('chat_id') and candidate.get('chat_id') != stored_candidate.get('chat_id'):
        logger.warning(f"chat_id mismatch: {candidate.get('chat_id')} != {stored_candidate.get('chat_id')}")
    else:
        candidate.update(stored_candidate)
    candidate['score'] = stored_candidate.get("analysis", {}).get("overall")
    return templates.TemplateResponse("partials/candidate_detail.html", {
        "request": request,
        "analysis": candidate.pop("analysis", {}),
        "generated_message": candidate.pop("generated_message", ''),
        "resume_text": candidate.pop("resume_text", ''),
        "full_resume": candidate.pop("full_resume", ''),
        "candidate": candidate,
        "view_mode": "interactive",
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
    job_applied: str = Form(...),
    name: str = Form(...),
    last_message: str = Form(...),
    resume_text: str = Form(...),
):
    """Initialize chat thread with proper data preparation.
    1. If in recommend mode, first check if exisiting candidate has been saved before by using semantic search
    2. If not found, create a new candidate record with history or last_message
    """

    job_info = get_job_by_id(job_id)
    # check if existing candidate has been saved before by using semantic search
    if not chat_id and resume_text:
        candidate = get_candidate_by_dict({"name": name, "job_applied": job_applied, "resume_text": resume_text})
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
        
    result = assistant_actions.init_chat(
        mode=mode,
        chat_id=chat_id,
        job_info=job_info,
        name=name,
        online_resume_text=resume_text,
        chat_history=history
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
    
    # start analyze
    analysis_result = assistant_actions.generate_message(
        input_message=input_message,
        conversation_id=conversation_id,
        purpose="ANALYZE_ACTION"
    )
    resume_type = "online" if not full_resume else "full"
    analysis_result["resume_type"] = resume_type
    
    # Save analysis in background
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
    # update candidate passes all relevant kwargs
    candidate_id = upsert_candidate(**kwargs)
    return candidate_id


@router.post("/generate-message", response_class=HTMLResponse)
async def generate_message(
    mode: str = Form(...),
    candidate_id: str = Form(...),
    chat_id: Optional[str] = Form(None),
    conversation_id: str = Form(...),
    purpose: str = Form(...),
):
    """Generate message for candidate. Requires conversation_id to be initialized first."""

    # ROLE_MAPPING = {'candidate': 'user', 'recruiter': 'assistant', 'system': 'developer'}

    # Get chat history
    default_user_message = {"content": f"请问你有什么问题可以让我进一步解答吗？", "role": "user"}
    new_messages = []
    last_assistant_message = ''
    page = await boss_service.service._ensure_browser_session()
    # { "type": "candidate/recruiter", "timestamp": "2025-11-10 10:00:00", "message": "你好，我叫张三", "status": "未读" }
    if mode == "recommend":
        # assert index is not None, "index is required for recommend mode"
        chat_history = [default_user_message]
        new_messages = [default_user_message]
    else:
        # get chat history from browser
        if chat_id:
            chat_history = await chat_actions.get_chat_history_action(page, chat_id)
            for msg in chat_history[::-1]:
                role = msg.get("role")
                content = f'{msg.get("timestamp")}: {msg.get("content")}'
                if role == "assistant":
                    last_assistant_message = content
                    break
                else:
                    new_messages.insert(0, {"content": content, "role": role})
        else:
            # No chat_id, use default message
            chat_history = [default_user_message]
            new_messages = [default_user_message]
    
    # generate message if there is new message from user(candidate)
    if [m for m in new_messages if m.get('role') == 'user']:
        # Generate message
        message = assistant_actions.generate_message(
            input_message=new_messages,
            conversation_id=conversation_id,
            purpose=purpose
        )
        logger.debug("Generated message: %s", message)
        
        # append the new message to the chat_history from DOM
        new_message = {"role": "assistant", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "content": message}
        upsert_candidate(
            candidate_id=candidate_id,
            last_message=message,
            chat_id=chat_id,
            mode=mode,
            conversation_id=conversation_id,
            generated_message=message,
            metadata={'history': chat_history + [new_message]},
        )
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

#--------------------------------------------------
# 简历请求
#--------------------------------------------------
# @router.post("/request-full_resume", response_class=HTMLResponse)
# async def request_resume(chat_id: str = Form(...)):
#     """Request full resume from candidate."""
#     page = await boss_service.service._ensure_browser_session()
#     result = await chat_actions.request_full_resume_action(page, chat_id)
#     if result:
#         return HTMLResponse(content='<div class="text-green-600 p-4">✅ 简历请求已发送</div>')
#     else:
#         return HTMLResponse(content='<div class="text-red-500 p-4">❌ 请求失败</div>', status_code=500)

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
    name = candidate.get("name", "未知候选人")
    job_applied = candidate.get("job_applied", "未指定岗位")
    message = f"""**候选人**: {name}
**岗位**: {job_applied}

**评分结果**:
- 技能匹配度: {analysis.get('skill', 'N/A')}/10
- 创业契合度: {analysis.get('startup_fit', 'N/A')}/10
- 基础背景: {analysis.get('background', 'N/A')}/10
- **综合评分: {analysis.get('overall', 'N/A')}/10**

**分析总结**:
{analysis.get('summary', '暂无')}

**跟进建议**:
{analysis.get('followup_tips', '暂无')}"""
    
    title = f"候选人 {name} 通过初步筛选"
    
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
            content=f'<textarea id="resume-textarea-online" readonly class="w-full h-64 p-4 bg-gray-50 border rounded-lg font-mono text-sm">{resume_text}</textarea>'
        )
    else:
        return HTMLResponse(
            # content='<div class="text-red-500 p-4">暂无在线简历，请先请求在线简历</div>',
            content=f'<textarea id="resume-textarea-online" readonly class="w-full p-4 bg-gray-50 border rounded-lg text-red-500 text-sm">暂无在线简历，请先请求在线简历</textarea>'
        )


@router.post("/fetch-full-resume", response_class=HTMLResponse)
async def fetch_full_resume(
    candidate_id: str = Form(...),
    chat_id: str = Form(...),
    mode: str = Form("chat"),
    job_id: str = Form(""),
):
    """Explicitly fetch full/offline resume (not online resume)."""
    # Only for chat/greet/followup modes, not recommend
    if mode == "recommend":
        return HTMLResponse(
            content='<div class="text-red-500 p-4">推荐候选人不支持离线简历</div>',
            status_code=400
        )
    
    # Try to get full resume only
    page = await boss_service.service._ensure_browser_session()
    # await chat_actions.request_full_resume_action(page, chat_id)
    result = await chat_actions.view_full_resume_action(page, chat_id)
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
            content=f'<textarea id="resume-textarea-full" readonly class="w-full h-64 p-4 bg-gray-50 border rounded-lg font-mono text-sm">{full_resume_text}</textarea>'
        )
    elif requested:
        return HTMLResponse(
            content='<div class="text-green-500 p-4">已向候选人请求完整简历，请稍后检查完整简历是否存在</div>',
        )
    else:
        return HTMLResponse(
            content='<div class="text-red-500 p-4">暂无完整简历，请先请求完整简历</div>',
        )


@router.post("/pass", response_class=HTMLResponse)
async def pass_candidate(
    chat_id: str = Form(...),
    candidate_id: str = Form(...),
):
    """Mark candidate as PASS and move to next."""
    page = await boss_service.service._ensure_browser_session()
    result = await chat_actions.discard_candidate_action(page, chat_id, stage="PASS")
    
    if result:
        upsert_candidate(
            candidate_id=candidate_id,
            chat_id=chat_id,
            stage="PASS",
        )
        return HTMLResponse(
            content='<div class="text-green-600">✅ 已标记为 PASS</div>',
            headers={"HX-Trigger": "candidateUpdated"}
        )
    else:
        return HTMLResponse(
            content='<div class="text-red-500">❌ 操作失败</div>',
            status_code=500
        )


@router.post("/request-contact")
async def request_contact(
    chat_id: str = Body(...),
    candidate_id: Optional[str] = Body(None),
):
    """Request contact information (phone and WeChat) from a candidate and store in metadata."""
    page = await boss_service.service._ensure_browser_session()
    
    # Call request_contact_action to get contact info
    contact_result = await chat_actions.request_contact_action(page, chat_id)
    
    # Extract phone_number and wechat_number
    phone_number = contact_result.get("phone_number")
    wechat_number = contact_result.get("wechat_number")
    
    # Find the candidate by candidate_id or chat_id
    candidate = None
    if candidate_id:
        candidate = get_candidate_by_dict({"candidate_id": candidate_id}, strict=False)
    
    if not candidate and chat_id:
        candidate = get_candidate_by_dict({"chat_id": chat_id}, strict=False)
    
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


# ============================================================================
# Record Reuse Endpoints
# ============================================================================



# @router.get("/thread-history/{conversation_id}", response_class=HTMLResponse)
# async def get_thread_history(
#     request: Request,
#     conversation_id: str
# ):
#     """Get conversation history HTML.
    
#     Args:
#         conversation_id: OpenAI conversation ID
#     """
#     messages_data = assistant_utils.get_conversation_messages(conversation_id)
    
#     return templates.TemplateResponse("partials/thread_history.html", {
#         "request": request,
#         "messages": messages_data.get("messages", []),
#         "conversation_id": conversation_id
#     })


