"""Assistant actions for recruitment automation with AI and storage."""
from __future__ import annotations

import logging
import json
import time
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional

from annotated_types import Not
from openai import OpenAI
from pydantic_core.core_schema import str_schema
from tenacity import retry, stop_after_attempt, wait_exponential
from deprecated import deprecated
from .candidate_store import CandidateStore, candidate_store
from .config import settings
from .global_logger import logger

# Constants
MAX_CONTEXT_CHARS = 4000  # Maximum characters for context truncation
ACTIONS = {
    # generate message actions
    "GREET_ACTION": "请生成首次打招呼消息", # 打招呼
    "ANALYZE_ACTION": "请根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。", # 分析候选人
    "ASK_FOR_RESUME_DETAILS_ACTION": "请根据上述沟通历史，生成下一条跟进消息。重点在于挖掘简历细节，判断候选人是否符合岗位要求，请直接提出问题，让候选人回答经验细节，或者澄清模棱两可的地方。不要超过100字，且能够直接发送给候选人的文字，不要发模板或者嵌入占位符。", # 询问简历细节
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
    "WAIT_ACTION": "已经完成所有动作，等待候选人回复。"
}
PLAN_PROMPTS = f"""请根据上述沟通历史，决定下一步操作。输出格式：
    {{
        "candidate_stage": <str>, // SEEK, GREET, PASS, CONTACT
        "action": <str>, // {", ".join(ACTIONS.keys())}
        "reason": <str>, // 为什么选择这个action, 不要超过100字
    }}
    每个action的说明：{json.dumps(ACTIONS, ensure_ascii=False)}"""
MESSAGE_ACTION_PROMPTS = {
    "GREET_ACTION": "请生成首次打招呼消息，突出公司与岗位亮点并认可候选人背景，请保持简短，不要超过50字。且能够直接发送给候选人的文字，不要发模板或者嵌入占位符。请用纯文本回复，不要使用markdown、json格式。",
    "ASK_FOR_RESUME_DETAILS_ACTION": """请根据上述沟通历史，生成下一条跟进消息。
    重点在于挖掘简历细节，判断候选人是否符合岗位要求，请直接提出问题，让候选人回答经验细节，或者澄清模棱两可的地方。
    不要超过100字，且能够直接发送给候选人的文字，不要发模板或者嵌入占位符。
    """,
    "ANALYZE_ACTION": """请根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。
尤其是keyword里面的正负向关键词要进行加分和减分。
另外也要仔细查看候选人的项目经历，检查是否有言过其词的情况。
最后，还要查看候选人的过往工作经历，判断是否符合岗位要求。

请给出 1-10 的四个评分：技能匹配度、创业契合度、加入意愿、综合评分，并提供简要分析。

输出严格使用 JSON 格式：
{{
"skill": <int>,
"startup_fit": <int>,
"willingness": <int>,
"overall": <int>,
"summary": <str>
}}""",
    "contact": "请发出一条请求候选人电话或者微信的消息。不要超过50字。且能够直接发送给候选人的文字，不要发模板或者嵌入占位符。请用纯文本回复，不要使用markdown、json格式。",
}

# Mapping from old lowercase purpose keys to new ACTION keys
PURPOSE_TO_ACTION = {
    "greet": "GREET_ACTION",
    "chat": "ASK_FOR_RESUME_DETAILS_ACTION",
    "followup": "ASK_FOR_RESUME_DETAILS_ACTION",
    "analyze": "ANALYZE_ACTION",
    "plan": "ANALYZE_ACTION",  # Assuming plan also uses analysis
    "contact": "contact",
}

def load_openai_key() -> str | None:
    """Load OpenAI API key from settings."""
    return settings.OPENAI_API_KEY


# Global OpenAI client singleton
_openai_client: Optional[OpenAI] = None


def get_openai_client() -> OpenAI:
    """Get or create OpenAI client singleton."""
    global _openai_client
    if _openai_client is None:
        api_key = load_openai_key()
        if not api_key:
            raise ValueError("OpenAI API key not found in settings")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


# Assistants ----------------------------------------------------
@lru_cache(maxsize=1)
def get_assistants() -> List[Dict[str, Any]]:
    """Get all assistants."""
    client = get_openai_client()
    return client.beta.assistants.list()


# Embeddings ----------------------------------------------------
@lru_cache(maxsize=1000)
def get_embedding(text: str) -> Optional[List[float]]:
    """Generate embedding for text."""
    if not candidate_store.enabled:
        return None
    client = get_openai_client()
    response = client.embeddings.create(
        model=settings.ZILLIZ_EMBEDDING_MODEL, 
        input=text[:4096],
        dimensions=settings.ZILLIZ_EMBEDDING_DIM,
    )
    return response.data[0].embedding


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
    client = get_openai_client()
    
    # Create OpenAI thread
    thread_metadata = {"chat_id": chat_id} if chat_id else {}
    thread = client.beta.threads.create(metadata=thread_metadata)
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
    Generate message using thread_id directly.
    
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
        
    Returns:
        Dict with:
            - message: str (generated message)
            - analysis: dict (if purpose="analyze")
            - success: bool
            - thread_id: str
    """
    
    client = get_openai_client()
    
    # thread_id is now passed directly, no lookup needed
    if not thread_id:
        raise ValueError("thread_id is required for generate_message")
    
    # Get current thread messages for comparison
    thread_messages = get_thread_messages(thread_id)
    
    # Sync thread with complete chat history
    history_messages = _normalise_history(chat_history)
    thread_messages = _sync_thread_with_history(thread_id, thread_messages, history_messages)
    logger.info("Synced chat history to thread %s", thread_id)
    
    # Get instruction for purpose - map old keys to new ACTION keys
    action_key = PURPOSE_TO_ACTION.get(purpose, purpose)  # Try mapping first, fallback to original
    instruction = MESSAGE_ACTION_PROMPTS.get(action_key)
    assert instruction, f"prompt for {purpose} (mapped to {action_key}) is not found"
    if purpose in ["analyze", "plan"]:
        format_json = True
    # Create a new run
    run = client.beta.threads.runs.create(
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
    if purpose == "analyze":
        analysis = json.loads(generated_message)
        # Get candidate entity by thread_id to update with analysis
        entity = candidate_store.get_candidate_by_id(thread_id=thread_id)
        if entity:
            entity["analysis"] = analysis
            _upsert_candidate(**entity)
        return analysis
    elif purpose == "plan":
        plan = json.loads(generated_message)
        # Get candidate entity by thread_id to update with plan
        entity = candidate_store.get_candidate_by_id(thread_id=thread_id)
        if entity:
            stage = plan["candidate_stage"]
            entity['stage'] = stage
            _upsert_candidate(**entity)
        return plan
                
    
    return generated_message


def get_candidate_by_resume(chat_id: str, candidate_resume: str) -> Optional[Dict[str, Any]]:
    """
    Get candidate record by candidate_resume.
    """
    # Try semantic search by resume
    if candidate_resume:
        embedding = get_embedding(candidate_resume)
        if embedding:
            match = candidate_store.search_candidates(embedding, limit=1)
            if match and match.get("entity"):
                entity = match["entity"]
                entity["chat_id"] = chat_id
                _upsert_candidate(**entity)
                return entity
    return None


def get_thread_messages(thread_id: str) -> List[Dict[str, str]]:
    """List all messages in a thread, paginated.
    1.	Fetch the first page (since after is None initially).
    2.	Collect all messages from that batch.
    3.	If the API says has_more=True, set after to the last message ID of the batch and loop again.
    4.	Stop when has_more=False.
    """
    client = get_openai_client()
    messages: List[Dict[str, str]] = []
    after: Optional[str] = None

    while True:
        response = client.beta.threads.messages.list(
            thread_id=thread_id,
            order="asc",
            limit=100,
            after=after,
        )
        for item in response.data:
            text_blocks = [
                block.text.value
                for block in getattr(item, "content", [])
                if getattr(block, "type", None) == "text"
            ]
            content = "\n".join(text_blocks).strip()
            messages.append({"id": item.id, "role": item.role, "content": content})
        if not getattr(response, "has_more", False):
            '''has_more = True means there are more messages available beyond what was just returned 
            (you haven't yet reached the end of the thread's history).
            {
                "data": [...],
                "has_more": true or false
            }
            '''
            break
        if response.data:
            after = response.data[-1].id
        else:
            break

    return messages


def _normalise_history(chat_history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Convert chat history to thread message format."""
    role_map = {"candidate": "user", "recruiter": "assistant", "system": "assistant"}
    normalised: List[Dict[str, str]] = []
    for entry in chat_history or []:
        role = role_map.get(entry.get("type"))
        message = (entry.get("message") or "").strip()
        if role and message:
            normalised.append({"role": role, "content": message})
        else:
            logger.warning(f"缺少角色或消息内容: [{role}]: {entry}")
    return normalised


def _sync_thread_with_history(
    thread_id: str,
    thread_messages: List[Dict[str, str]],
    history_messages: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Sync thread messages with chat history, adding missing messages."""
    client = get_openai_client()
    comparable_thread = [
        (msg["role"], msg["content"])
        for msg in thread_messages
    ]

    last_common = -1
    idx_thread = len(comparable_thread) - 1
    for idx_history in range(len(history_messages) - 1, -1, -1):
        history_msg = history_messages[idx_history]
        while idx_thread >= 0:
            thread_role, thread_content = comparable_thread[idx_thread]
            if (
                thread_role == history_msg["role"]
                and thread_content == history_msg["content"]
            ):
                last_common = idx_history
                idx_thread -= 1
                break
            idx_thread -= 1
        if last_common != -1:
            break

    pending = history_messages[last_common + 1 :]
    for message in pending:
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role=message["role"],
            content=message["content"],
        )
        thread_messages.append({"role": message["role"], "content": message["content"]})

    return thread_messages


def _append_message_to_thread(
    thread_id: str,
    role: str,
    content: str,
    thread_messages: Optional[List[Dict[str, str]]] = None,
) -> bool:
    """
    Append a message to the thread only if it does not already exist.

    Args:
        thread_id (str): The ID of the thread.
        role (str): The role of the message sender ("user", "assistant", etc).
        content (str): The message content.
        thread_messages (Optional[List[Dict[str, str]]]): Current list of thread messages, if available.

    Returns:
        bool: True if the message was added, False if it already existed.
    """
    client = get_openai_client()
    if thread_messages:
        for message in thread_messages:
            if message.get("role") == role and message.get("content") == content:
                return False
        thread_messages.append({"role": role, "content": content})
    message = client.beta.threads.messages.create(thread_id=thread_id, role=role, content=content)
    return bool(message)
    

def _wait_for_run_completion(thread_id: str, run_id: str, timeout: int = 60) -> bool:
    """Wait for AI assistant run to complete with timeout."""
    client = get_openai_client()
    start = time.time()
    while time.time() - start < timeout:
        run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        status = getattr(run_status, "status", "")
        if status == "completed":
            return True
        if status in {"failed", "cancelled", "expired"}:
            logger.error("Run %s stopped with status %s", run_id, status)
            return False
        time.sleep(1)
    logger.error("Run %s timed out", run_id)
    return False


def _extract_latest_assistant_message(thread_id: str) -> str:
    """Extract the latest assistant message from thread."""
    client = get_openai_client()
    response = client.beta.threads.messages.list(
        thread_id=thread_id,
        order="desc",
        limit=10,
    )
    for message in response.data:
        if message.role != "assistant":
            continue
        text_blocks = [
            block.text.value
            for block in message.content
            if getattr(block, "type", None) == "text"
        ]
        content = "\n".join(text_blocks).strip()
        return content # only return the latest assistant message



__all__ = [
    "get_openai_client",
    "get_assistants",
    "get_embedding",
    "init_chat",
    "generate_message",
    "get_thread_messages",
    "update_candidate_resume",
]
