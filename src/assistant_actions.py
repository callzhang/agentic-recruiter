"""Assistant actions for recruitment automation with AI and storage."""
from __future__ import annotations

import logging
import json
from functools import lru_cache
from typing import Any, Dict, List, Optional
from openai import OpenAI
from .candidate_store import candidate_store
from .config import settings
from .global_logger import logger
from .assistant_utils import (
        _wait_for_run_completion, 
        _extract_latest_assistant_message, 
        _append_message_to_thread, 
        _normalise_history, 
        _sync_thread_with_history, 
        get_thread_messages, 
        get_embedding
)

# Constants
STAGES = [
    "GREET", # 打招呼
    "PASS", # < borderline,不匹配，已拒绝
    "CHAT", # >= borderline,沟通中
    "SEEK", # >= threshold_seek,寻求联系方式
    "CONTACT", # 已获得联系方式
]
ACTIONS = {
    # generate message actions
    "CHAT_ACTION": "请根据上述沟通历史，生成下一条跟进消息。重点在于挖掘简历细节，判断候选人是否符合岗位要求，请直接提出问题，让候选人回答经验细节，或者澄清模棱两可的地方", # 打招呼 询问简历细节,
    "ANALYZE_ACTION": "请根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。", # 分析候选人
    "ANSWER_QUESTIONS_ACTION": "请回答候选人提出的问题。", # 回答问题
    "FOLLOWUP_ACTION": "请生成下一条跟进消息，用于吸引候选人回复。", # 跟进消息
    "REQUEST_CONTACT_MESSAGE_ACTION": "请生成下一条跟进消息，用于吸引候选人回复。", # 联系方式
    # browser actions
    "SEND_MESSAGE_BROWSER_ACTION": "请发送消息给候选人。", # 发送消息
    "REQUEST_FULL_RESUME_BROWSER_ACTION": "请请求完整简历。", # 请求完整简历
    "REQUEST_WECHAT_PHONE_BROWSER_ACTION": "请请求候选人微信和电话。", # 请求微信和电话
    # notification actions
    "NOTIFY_HR_ACTION": "请通知HR。", # 通知HR
    # chat actions
    "FINISH_ACTION": "已经完成所有动作，等待候选人回复。",
    "PLAN_PROMPTS": "自动化工作流计划动作"
}
ACTION_PROMPTS = {
    "CHAT_ACTION": """请根据上述沟通历史，生成下一条跟进消息。
    重点在于挖掘简历细节，判断候选人是否符合岗位要求，请直接提出问题，让候选人回答经验细节，或者澄清模棱两可的地方。
    请直接生成一条可以发送给候选人的自然语言消息，不要超过100字。不要发模板或者嵌入占位符，不要使用任何格式化、引号、JSON或括号。
    """,
    "ANALYZE_ACTION": """请根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。
尤其是keyword里面的正负向关键词要进行加分和减分。
另外也要仔细查看候选人的项目经历，检查是否有言过其词的情况。
最后，还要查看候选人的过往工作经历，判断是否符合岗位要求。

请给出 1-10 的四个评分：技能匹配度、创业契合度、基础背景、综合评分，并提供简要分析。

输出严格使用 JSON 格式：
{{
"skill": <int>, // 技能、经验匹配度
"startup_fit": <int>, // 创业公司契合度，抗压能力、对工作的热情程度
"background": <int>, // 基础背景、学历优秀程度、逻辑思维能力
"overall": <int>, // 综合评分
"summary": <str>, // 分析总结
"followup_tips": <str>  // 后续招聘顾问跟进的沟通策略
}}""",
    "CONTACT_ACTION": "请发出一条请求候选人电话或者微信的消息。不要超过50字。且能够直接发送给候选人的文字，不要发模板或者嵌入占位符。请用纯文本回复，不要使用markdown、json格式。",
    "FINISH_ACTION": "已经完成所有动作，等待候选人回复。",
    "PLAN_PROMPTS": f"""请根据上述沟通历史，决定下一步操作。输出格式：
        {{
            "candidate_stage": <str>, // SEEK, GREET, PASS, CONTACT
            "action": <str>, // {", ".join(ACTIONS.keys())}
            "reason": <str>, // 为什么选择这个action, 不要超过100字
        }}
        每个action的说明：{json.dumps(ACTIONS, ensure_ascii=False)}"""
}


# Assistants ----------------------------------------------------
_openai_client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

@lru_cache(maxsize=1)
def get_assistants() -> List[Dict[str, Any]]:
    """Get all assistants."""
    return _openai_client.beta.assistants.list()




# Candidate Management --------------------------------------

def _upsert_candidate(**kwargs) -> bool:
    """Insert or update candidate information to the store.
    Used by: boss_service.py (upsert endpoint), src/scheduler.py (automation), generate_message (internal)
    """
    # Generate embedding for new candidates
    candidate_id = kwargs.get("candidate_id")
    chat_id = kwargs.get("chat_id")
    if chat_id or candidate_id:
        existing_candidate = candidate_store.get_candidate_by_id(chat_id=chat_id, candidate_id=candidate_id)
    else:
        existing_candidate = None

    # Truncate resume text to avoid over limits
    resume_text = kwargs.get("resume_text")
    if resume_text:
        kwargs["resume_text"] = resume_text[:8000]

    if not existing_candidate:  # create a new candidate
        resume_text = kwargs.get("resume_text")
        if resume_text:
            embedding = get_embedding(resume_text)
            kwargs["resume_vector"] = embedding
        return candidate_store.insert_candidate(**kwargs)
    else:
        existing_candidate.update(kwargs)
        return candidate_store.update_candidate(**existing_candidate)
        

def update_candidate_resume(chat_id: str, thread_id: str, resume_text: str, full_resume: str) -> bool:
    """Update candidate resume in store and thread."""
    kwargs = {'chat_id': chat_id}
    assert thread_id, f"thread_id is missing from record:{chat_id}"
    if resume_text:
        kwargs["resume_text"] = resume_text
        candidate_resume_text = f'请查看我的简历:\n{resume_text}'
        _append_message_to_thread(thread_id, role="user", content=candidate_resume_text)
    if full_resume:
        kwargs["full_resume"] = full_resume
        candidate_resume_text = f'请查看我的完整简历:\n{full_resume}'
        _append_message_to_thread(thread_id, role="user", content=candidate_resume_text)

    return _upsert_candidate(chat_id=chat_id, **kwargs)

# todo: has not been used
def get_candidate_by_resume(chat_id: str, candidate_resume: str) -> Optional[Dict[str, Any]]:
    """
    Get candidate record by candidate_resume.
    """
    # Try semantic search by resume
    embedding = get_embedding(candidate_resume)
    return candidate_store.search_candidates(embedding, limit=1)

# AI Generation with Threads API ------------------------------

def init_chat(
    name: str,
    job_info: Dict[str, Any],
    resume_text: str,
    chat_history: List[Dict[str, Any]]=[],
    chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Initialize conversation thread and Zilliz record.
    
    Creates OpenAI thread with job description and resume, then creates/updates Zilliz record
    with thread_id for future message generation.
    
    Note: This function is called ONLY when we have the resume_text and BEFORE analyzing it.
    
    Args:
        name: str (candidate name)
        job_info: Dict with job position, description, requirements
        resume_text: str (candidate resume text - REQUIRED)
        chat_id: Optional[str] (for chat workflows, None for recommend workflow)
        chat_history: Optional existing chat history to sync
        
    Returns:
        Dict with:
            - thread_id: str (OpenAI thread ID)
            - candidate_id: str (Zilliz record ID)
            - success: bool
    """
    
    # Create OpenAI thread
    thread_metadata = {"chat_id": chat_id} if chat_id else {}
    thread = _openai_client.beta.threads.create(metadata=thread_metadata)
    thread_id = thread.id
    thread_messages: List[Dict[str, str]] = []
    
    # Add job description to thread
    job_info_text = json.dumps(job_info, ensure_ascii=False)
    job_description = f'你好，我是招聘顾问。以下是岗位描述，用于你的匹配程度，我们在后面的对话中都需要参考:\n{job_info_text}'
    _append_message_to_thread(thread_id, thread_messages=thread_messages, role="assistant", content=job_description)
    logger.info("Added job description to thread %s", thread_id)
    
    # Sync thread with chat history if provided
    history_messages = _normalise_history(chat_history)
    thread_messages = _sync_thread_with_history(thread_id, thread_messages, history_messages)
    logger.info("Synced chat history to thread %s", thread_id)
    if len(chat_history) > 0:
        last_message = chat_history[-1].get("message")
    else:
        last_message = ""
    
    # Add candidate resume to thread
    candidate_resume_text = f'请查看我的简历:\n{resume_text[:2000]}'
    _append_message_to_thread(thread_id, thread_messages=thread_messages, role="user", content=candidate_resume_text)
    logger.info("Added candidate resume to thread %s", thread_id)
    
    # Create/update Zilliz record
    # Generate embedding for semantic search
    embedding = get_embedding(resume_text)
    
    # create candidate record
    success = _upsert_candidate(
        chat_id=chat_id,
        name=name,
        last_message=last_message,
        job_applied=job_info["position"],
        resume_text=resume_text,
        resume_vector=embedding,
        stage=None,  # Not analyzed yet
        thread_id=thread_id,
    )
    
    return {
        "thread_id": thread_id,
        "success": success
    }

## ------------Main Message Generation----------------------------------

def generate_message(
    thread_id: str,
    assistant_id: str,
    purpose: str,
    chat_history: List[Dict[str, Any]],
    format_json: Optional[bool] = False,
) -> Dict[str, Any]:
    """
    Generate message using openai's assistant api.
    
    This method generates the next message in an existing conversation thread.
    It adds any new context (user message, full resume, etc.) to the thread
    and generates an appropriate response based on the purpose.
    
    Supports three scenarios:
    1) Recommend candidates: thread_id from init_chat (no chat_id)
    2) Chat "新招呼": thread_id from init_chat after passing chat_id
    3) Chat "沟通中/牛人已读未回": thread_id retrieved from Zilliz by chat_id
    
    Args:
        thread_id: OpenAI thread ID (required) - universal identifier
        assistant_id: OpenAI assistant ID (required)
        purpose: Message purpose - "analyze", "greet", "chat", "followup"
        chat_history: Complete chat history to sync with thread (required)
        format_json: Whether to request JSON response format
        threshold: Threshold for stage decision, required for analyze and plan
    Returns:
        Dict with:
            - message: str (generated message)
            - analysis: dict (if purpose="analyze")
            - success: bool
            - thread_id: str
    """
    
    # thread_id is now passed directly, no lookup needed
    if not thread_id:
        raise ValueError("thread_id is required for generate_message")
    assert purpose in ACTION_PROMPTS.keys(), f"purpose {purpose} is not found in MESSAGE_ACTION_PROMPTS"
    logger.debug(f"Generating message for purpose: {purpose}")
    # Get current thread messages for comparison
    thread_messages = get_thread_messages(thread_id)['messages']
    # Sync thread with complete chat history
    history_messages = _normalise_history(chat_history)
    thread_messages = _sync_thread_with_history(thread_id, thread_messages, history_messages)
    logger.info("Synced chat history to thread %s", thread_id)
    # Get instruction for purpose - map old keys to new ACTION keys
    instruction = ACTION_PROMPTS.get(purpose)
    if purpose in ["ANALYZE_ACTION", "PLAN_PROMPTS"]:
        format_json = True
    # Create a new run
    run = _openai_client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id,
        additional_instructions=instruction,
        response_format={"type": "json_object"} if format_json else {"type": "text"},
    )
    
    # Wait for completion
    if not _wait_for_run_completion(thread_id, run.id):
        logger.error("Run failed or timed out for thread %s", thread_id)
        raise RuntimeError("消息生成失败，请稍后重试")
    
    # Extract generated message
    generated_message = _extract_latest_assistant_message(thread_id).strip()
    
    # Parse analysis if purpose is "analyze"
    if purpose == "ANALYZE_ACTION":
        analysis = json.loads(generated_message)
        # Try to update candidate entity with analysis (non-critical, analysis is in thread)
        try:
            # First, query to get the candidate_id, including the vector field
            entity = candidate_store.get_candidate_by_id(thread_id=thread_id, fields=["*"]) #TODO: remove vector field
            if entity and entity.get('candidate_id'):
                # Update with analysis
                entity['analysis'] = analysis
                entity['stage'] = "CHAT"
                candidate_store.update_candidate(**entity)
        except Exception as e:
            logger.warning("Failed to update candidate analysis in Zilliz (non-critical): %s", e)
        return analysis
    elif purpose == "PLAN_PROMPTS":
        plan = json.loads(generated_message)
        # Try to update candidate entity with plan (non-critical, plan is in thread)
        try:
            # First, query to get the candidate_id, including the vector field
            entity = candidate_store.get_candidate_by_id(thread_id=thread_id, fields=["*"]) #TODO: remove vector field
            if entity and entity.get('candidate_id'):
                # Update with plan
                entity['stage'] = plan["candidate_stage"]
                candidate_store.update_candidate(**entity)
        except Exception as e:
            logger.warning("Failed to update candidate plan in Zilliz (non-critical): %s", e)
        return plan
                
    
    return generated_message




__all__ = [
    "get_assistants",
    "get_embedding",
    "init_chat",
    "generate_message",
    "get_thread_messages",
    "update_candidate_resume",
    "get_candidate_by_resume",
]
