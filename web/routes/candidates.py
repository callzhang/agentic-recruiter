"""Candidate management routes for web UI.
`chat_id` is the id from boss zhipin website, in mode = chat, greet, followup
`index` is the index of the candidate in the recommended list, in mode = recommend
`conversation_id` is from openai responses api, used to continue the conversation from openai
`candidate_id` is the primary key in zilliz cloud object, used to store the candidate data
`job_applied` is the job position title that candidate is applying for, used consistently throughout
"""

import asyncio
from datetime import datetime, timedelta
import dateutil.parser as parser
import json
import re
from typing import Any, Dict, Optional
from fastapi import APIRouter, BackgroundTasks, Form, Query, Request, Response, Body, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from tenacity import retry, stop_after_attempt, wait_exponential
from src.candidate_store import search_candidates_advanced, get_candidate_by_dict, upsert_candidate, _readable_fields, calculate_resume_similarity, candidate_matched
from src.jobs_store import get_job_by_id 
from src.global_logger import logger
from src import chat_actions, assistant_actions, assistant_utils, recommendation_actions
from src.assistant_actions import send_dingtalk_notification
from src.candidate_stages import STAGE_PASS, STAGE_CHAT, STAGE_SEEK, STAGE_CONTACT, ALL_STAGES, derive_stage_from_action
import boss_service

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")
from src.config import get_vercel_config
vercel_url = get_vercel_config().get("url", "").rstrip('/')

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
    limit: int = Query(40, description="Limit the number of candidates to return (default: 999)"),
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
        job = get_job_by_id(job_id) or {}
        
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
                unread_only=False if mode in ["followup"] else True,  # True 只看未读,
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
    fields = [f for f in _readable_fields if f not in {"resume_vector", "full_resume", "resume_text"}]
    found_candidates = search_candidates_advanced(
        candidate_ids= [c.get("candidate_id") for c in candidates if c.get("candidate_id")],
        chat_ids= [c.get("chat_id") for c in candidates if c.get("chat_id")],
        conversation_ids= [c.get("conversation_id") for c in candidates if c.get("conversation_id")],
        names= [c.get("name") for c in candidates if c.get("name")], # if not recommend mode, use ids to search
        job_applied=job_applied,
        limit=len(candidates) * 2,
        strict=False, # relax the strictness of the search
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
        matched_candidate = next((c for c in found_candidates if \
            c.get("name") == candidate['name'] and candidate_matched(candidate, c, mode)), None)
        # fallback to find individual candidate 
        if not matched_candidate:
            matched_candidate = get_candidate_by_dict(dict(**candidate, fields=fields))

        if matched_candidate:
            if matched_candidate in found_candidates: 
                found_candidates.remove(matched_candidate) # remove matched candidate from found_candidates to avoid duplicate matching
            # update candidate 
            current_metadata = candidate.get("metadata", {})
            current_metadata.update(matched_candidate.get("metadata", {}))
            candidate.update(matched_candidate) # last_message will be updated by saved candidate
            candidate["metadata"] = current_metadata
            # update candidate fields
            candidate["saved"] = True
            candidate["score"] = matched_candidate.get("analysis", {}).get("overall", None)
            # update greeted status if the candidate is in chat, greet, or seek stage
            candidate['greeted'] = candidate.get('greeted', False)
            # ensure notified field is properly set (default to False if not present)
            candidate['notified'] = candidate.get('notified', False)
            restored += 1
            

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
    # Try to find existing candidate (database query, no browser lock needed)
    stored_candidate = get_candidate_by_dict(candidate, strict=False) # we should not use strict=True here, chat_id may change, or not available from recommend mode
    if stored_candidate:
        candidate.update(stored_candidate)
    # Prepare template context (pop values before rendering to avoid issues)
    analysis = candidate.pop("analysis", {})
    generated_message = candidate.pop("generated_message", '')
    resume_text = candidate.pop("resume_text", '')
    full_resume = candidate.pop("full_resume", '')
    
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
    
    # Get job info
    job_info = get_job_by_id(job_id)
    if not job_info:
        raise HTTPException(status_code=400, detail=f"未找到岗位: {job_id}")
    
    # check if existing candidate has been saved before by using semantic search
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
        history = [
            {"role": "developer", "content": "系统推荐以下候选人，请分析是否匹配。如匹配可以主动和候选人沟通。"},
            {'role': 'developer', 'content': f"候选人: {name}, 系统推荐岗位: {job_applied}, 基本信息: {last_message}"},
            {'role': 'developer', 'content': f"以下是岗位信息（JSON，仅用于内部判断）：\n{job_info}"},
            {"role": "assistant", "content": f"你好，我们正在诚招{job_applied}，想跟你沟通一下。"}, 
            {"role": "user", "content": "你好，有什么事？"},
        ]
    else:
        assert chat_id is not None, "chat_id is required for chat/followup/greet mode"
        history = [
            {"role": "developer", "content": "候选人主动投递简历，请分析是否匹配。如匹配可以主动和候选人沟通。"},
            {'role': 'developer', 'content': f"候选人: {name}, 申请岗位: {job_applied}"},
            {'role': 'developer', 'content': f"以下是岗位信息（JSON，仅用于内部判断）：\n{job_info}"},
        ]
        page = await boss_service.service._ensure_browser_session()
        history += await chat_actions.get_chat_history_action(page, chat_id)
    
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


@router.post("/analyze-and-generate", response_class=HTMLResponse)
async def analyze_and_generate(
    request: Request,
    mode: str = Form(...),
    chat_id: Optional[str] = Form(None),
    candidate_id: str = Form(...),
    conversation_id: str = Form(...),
    job_applied: str = Form(...),
    resume_text: str = Form(None),
    full_resume: str = Form(None),
    analysis: Optional[str] = Form(None),
    name: str = Form(...),
    force: bool = Form(False),
    chat_threshold: float = Form(6.0),
    borderline_threshold: float = Form(7.0),
):
    """Analyze candidate and (optionally) generate message in one request."""
    analysis = json.loads(analysis) if analysis else None
    resume_type = analysis['resume_type'] if analysis else None
    new_user_messages = []
    # check if should generate message
    need_reply, user_messages, assistant_message, chat_history = await _should_generate_message(
        candidate_id, chat_id, mode, force
    )
    # build user messages from resume
    if full_resume and analysis and resume_type != "full":
        need_reply = True
        logger.debug(f"Analyzing full resume for {name}")
        new_user_messages += [{"role": "developer", "content": f'这是候选人{name}的完整简历，结合已有对话记录，分析是否匹配{job_applied}这个岗位？\n{full_resume}'}]
        resume_type = "full"
    elif resume_text and not analysis:
        need_reply = True
        logger.debug(f"Analyzing online resume for {name}")
        new_user_messages += [{"role": "developer", "content": f'这是候选人{name}的在线简历，结合已有对话记录，分析是否匹配{job_applied}这个岗位？\n{resume_text}'}]
        resume_type = "online"
        
    # add new user messages
    new_user_messages += user_messages
    # Build input for followup action if needed
    if (mode == "followup" or force) and not new_user_messages:
        new_user_messages += [{"role": "user", "content": "[沉默]"}]
        need_reply = True

    if not need_reply:
        return HTMLResponse(
            content='',
            status_code=200,
            headers={"HX-Trigger": json.dumps({"showToast": {"message": "不需要回复", "type": "error"}}, ensure_ascii=True)}
        )

    # Always re-run analysis on every request.
    additional_instruction = f'HR设定的沟通阈值（action=CHAT）是{chat_threshold}， 推荐阈值（action=SEEK）是{borderline_threshold}，请在分析打分时参考。'
    analysis_result = await asyncio.to_thread(
        assistant_actions.generate_message,
        input_message=new_user_messages,
        conversation_id=conversation_id,
        purpose="ANALYZE_AND_MESSAGE_ACTION",
        additional_instruction=additional_instruction,
    )
    analysis_result["resume_type"] = resume_type
    # 安全检查（基于规则），用于检测模型是否按照规则行事
    action = analysis_result.get("action")
    overall = analysis_result.get("overall")
    message_text = analysis_result.get("message")
    
    # Validate action based on score thresholds
    if overall < 4 and action != "PASS":
        logger.warning(f"overall is {overall}, but action is {action}, forcing to PASS")
        action = "PASS"
    elif overall < 6 and action not in ["PASS", "CHAT", "WAIT"]:
        logger.warning(f"overall is {overall}, but action is {action}, forcing to CHAT")
        action = "CHAT"
    
    # WAIT 时，不应该有消息
    if action == "WAIT" and message_text:
        logger.warning(f"action is WAIT, but message_text is not empty: {message_text}")
        message_text = ""
    if not need_reply:
        message_text = ""
        action = "PASS" if overall < 4 else "WAIT"
    # 未提供完整简历，不应该设置为强匹配
    if action == "CONTACT" and resume_type != "full":
        logger.warning(f"action is {action}, but resume_type is {resume_type}, downgrading to SEEK")
        action = "SEEK"
    
    # Derive stage from action
    stage = derive_stage_from_action(action)
    # 构建历史记录
    generated_history_item: dict[str, Any] = {
        "role": "assistant",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "content": message_text,
        "action": action,
        "reason": analysis_result.get("reason"),
    }
    # new_chat_history = chat_history + [generated_history_item]
    # new_chat_history = [m for m in new_chat_history if m.get("role") in ["user", "assistant"]] # prevent json over size limit
    # 更新数据
    upsert_candidate(
        analysis=analysis_result,
        score=overall,
        candidate_id=candidate_id,
        chat_id=chat_id,
        mode=mode,
        conversation_id=conversation_id,
        stage=stage,
        generated_message=message_text,
        metadata={
            "history": chat_history + [generated_history_item]
        }
    )
    
    # render analysis and message
    analysis_html = templates.env.get_template("partials/analysis_result.html").render({
        "request": request,
        "analysis": analysis_result,
    })
    message_html = templates.env.get_template("partials/message_result.html").render({
        "request": request,
        "message": message_text,
        "action": action,
        "reason": analysis_result.get("reason"),
        "generated": bool(message_text),
    })
    content = (
        f'<div id="analysis-content" hx-swap-oob="true">{analysis_html}</div>'
        f'<div id="message-content" hx-swap-oob="true">{message_html}</div>'
    )
    return HTMLResponse(content=content)

@router.post("/should-reply")
async def should_reply(
    chat_id: Optional[str] = Body(None),
    candidate_id: Optional[str] = Body(None),
    mode: Optional[str] = Body(None),
) -> bool:
    should_generate, _, _, _ = await _should_generate_message(candidate_id, chat_id, mode)
    return should_generate

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
    kwargs = dict(form_data)
    # Only for chat/greet/followup modes, not recommend
    if mode == "recommend":
        return HTMLResponse(
            content='<div class="text-red-500 p-4">推荐候选人不支持离线简历</div>',
            status_code=400
        )
    
    # skip if already requested
    full_resume_text, requested = None, False
    candidate = get_candidate_by_dict(kwargs, strict=False)
    # if history:=candidate.get("metadata", {}).get("history"):
    page = await boss_service.service._ensure_browser_session()
    chat_history = await chat_actions.get_chat_history_action(page, chat_id)
    if any(h for h in chat_history if h.get("role") == "developer" and h.get("content") == "简历请求已发送"):
        requested = True
        full_resume_text = candidate.get("full_resume")
    
    if not full_resume_text:
        # Try to get full resume only
        page = await boss_service.service._ensure_browser_session()
        result = await chat_actions.view_full_resume_action(page, chat_id, request=not requested)
        full_resume_text = result.get("text")
        requested = result.get("requested") or requested
    
    if full_resume_text and len(full_resume_text) > 100:
        upsert_candidate(
            candidate_id=candidate_id,
            full_resume=full_resume_text,
            chat_id=chat_id,
            metadata={
                "history": chat_history,
                "full_resume_requested": requested,
            }
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


@router.post("/scroll-recommendations")
async def scroll_recommendations():
    """Scroll the recommendation frame to trigger loading of new candidates."""
    page = await boss_service.service._ensure_browser_session()
    result = await recommendation_actions.scroll_to_load_more_candidates(page)
    if result:
        return {"success": True, "message": "已滚动推荐列表"}
    else:
        raise HTTPException(status_code=500, detail="滚动操作失败")


@router.post("/request-contact")
async def request_contact(
    request: Request,
):
    """Request contact information (phone and WeChat) from a candidate and store in metadata."""
    page = await boss_service.service._ensure_browser_session()
    kwargs = await request.json()
    candidate = get_candidate_by_dict(kwargs, strict=False)
    if not candidate:
        raise RuntimeError(f"Candidate not found for chat_id: {kwargs.get('chat_id')}")
    metadata = candidate.get("metadata", {})
    requested = False
    if history:=metadata.get("history"):
        if any(h for h in history if h.get("role") == "developer" and\
            "请求交换联系方式已发送" in h.get("content") or "请求交换微信已发送" in h.get("content")):
            requested = True
    # Call request_contact_action to get contact info
    contact_result = await chat_actions.request_contact_action(page, kwargs.get("chat_id"), request=not requested)
    
    # Extract phone_number and wechat_number
    phone_number = contact_result.get("phone_number")
    wechat_number = contact_result.get("wechat_number")
    
    # Find the candidate by candidate_id or chat_id
    
    # Update candidate metadata with contact info
    # Metadata merging is handled automatically by upsert_candidate()
    if candidate and (phone_number or wechat_number):
        upsert_candidate(
            candidate_id=candidate.get("candidate_id"),
            chat_id=kwargs.get("chat_id"),
            metadata={
                "phone_number": phone_number,
                "wechat_number": wechat_number,
            },
            stage=STAGE_CONTACT,
        )
        
    return JSONResponse({
        "success": bool(phone_number or wechat_number),
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


#----------------------
# Helper Functions
#----------------------
FOLLOWUP_DELTA_DAYS = 2
MAX_FOLLOWUP_DAYS = 20
async def _should_generate_message(candidate_id: str, chat_id: str, mode: str, force = False) -> tuple[bool, list]:
    """Check if should generate message for candidate.
    Args:
        chat_id: Chat ID to get chat history from browser
        mode: Mode (recommend/chat/greet/followup)
        force: Force generate message
    Returns:
        bool, list
    """   
    should_generate = False
    new_user_messages, chat_history = [], []
    if force: should_generate = True
    # get candidate from database
    candidate = get_candidate_by_dict({"candidate_id": candidate_id})
    # if candidate not saved, it's probably a new candidate, so we should generate message
    if not candidate: return True, [], {}, []
    # if the candidate is already passed, don't reply
    if candidate.get("stage") == STAGE_PASS: return False, [], {}, []
    # Get analysis result
    analysis_result = candidate.get("analysis")
    # Get new user messages and assistant message from candidate metadata
    new_user_messages, assistant_message, chat_history = await _get_chat_history(candidate)
    last_action = assistant_message.get("action")
    # Derive stage from action in analysis if available
    analysis_action = analysis_result.get("action") if analysis_result else None
    analysis_derived_stage = derive_stage_from_action(analysis_action) if analysis_action else None
    if analysis_derived_stage == STAGE_PASS:
        should_generate = False
    elif last_action in ['WAIT', 'PASS']:
        should_generate = False
    elif bool(new_user_messages):
        should_generate = True
    elif mode == "followup":
        # check if updated_at has exceeded FOLLOWUP_MAX_DAYS
        updated_at = candidate.get("updated_at")
        updated_at = parser.parse(updated_at).replace(tzinfo=None)
        diff_days = (datetime.now() - updated_at).days
        if diff_days > FOLLOWUP_DELTA_DAYS and diff_days < MAX_FOLLOWUP_DAYS:
            should_generate = True
    return should_generate, new_user_messages, assistant_message, chat_history


async def _get_chat_history(candidate) -> Optional[dict]:
    """Get chat history from candidate metadata, 
    fall back to get chat history from browser(and upsert history if empty).
    """
    if not candidate.get("chat_id"):
        return [], {}, []
    # first check user messages from metadata -> this is not working to detect new user messages from browser
    metadata_history = candidate.get('metadata', {}).get('history')
    page = await boss_service.service._ensure_browser_session()
    chat_history = await chat_actions.get_chat_history_action(page, candidate["chat_id"])
    new_user_messages, assistant_message, _, _ = _extract_user_assistant_messages(chat_history, skip_words=['方便发一份简历过来吗'])
    # merge history from browser to metadata
    merged_history = _merge_history(metadata_history, chat_history)
    if len(metadata_history) < len(merged_history):
        upsert_candidate(
            candidate_id=candidate["candidate_id"],
            metadata={ "history": merged_history }
        )
    return new_user_messages, assistant_message, merged_history

def _extract_user_assistant_messages(history, skip_words:list=[], detect_words:list=[]):
    """Extract user and last assistant messages from history.
    Args:
        history: List of messages
        skip_words: if matched skip word, the message is not a hit
        detect_words: List of words to detect in assistant message
    """
    assert type(skip_words) == list and type(detect_words) == list, "skip_words and detect_words must be list"
    assistant_message = {}
    new_user_messages = []
    skipped = False
    detected = False
    # { "role": "assistant/user", "timestamp": "2025-11-10 10:00:00", "content": "你好，我叫张三", "status": "未读" }
    for msg in history[::-1]:
        role = msg.get("role")
        content = msg.get("content")
        if role == "assistant":
            skipped = any(skip in content for skip in skip_words)
            detected = any(detect in content for detect in detect_words)
            if not skipped:
                assistant_message = msg
                break
            elif detected:
                break
        elif role == "user":
            new_user_messages.insert(0, msg)
    return new_user_messages, assistant_message, skipped, detected

def _merge_history(metadata_history, browser_history):
    ''' merge history from browser to metadata
    metadata_history: list of dict [{"role": "user/assistant", "timestamp": "2025-11-10 10:00:00", "content": "你好，我叫张三", "status": "未读", "action": "CHAT"}]
    browser_history: list of dict [{"role": "user/assistant", "timestamp": "2025-11-10 10:00:00", "content": "你好，我叫张三", "status": "未读"}]
    '''
    if not metadata_history:
        return browser_history
    if not browser_history:
        return metadata_history
    
    merged = metadata_history.copy()
    for msg in merged:
        msg["timestamp"] = re.sub(r'[\u4e00-\u9fff]+', '', msg.get("timestamp", ""))
    metadata_messages_set = {(msg.get("role"), msg.get("content")):msg for msg in metadata_history}
    for browser_msg in browser_history:
        key = (browser_msg.get("role"), browser_msg.get("content"))
        if key not in metadata_messages_set:
            timestamp_str = browser_msg.get("timestamp")
            browser_msg['timestamp'] = re.sub(r'[\u4e00-\u9fff]+', '', timestamp_str)
            merged.append(browser_msg)
        else:
            msg = metadata_messages_set[key]
            msg["timestamp"] = re.sub(r'[\u4e00-\u9fff]+', '', browser_msg["timestamp"])
    
    merged.sort(key=lambda x: parser.parse(x.get("timestamp", "1970-01-01 00:00:00")))
    return merged