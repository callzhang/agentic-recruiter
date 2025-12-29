"""Assistant actions for recruitment automation with AI and storage."""
import json
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
from functools import lru_cache
from typing import Any, Dict, List, Optional
from .candidate_store import upsert_candidate
from .config import get_dingtalk_config, get_openai_config
from .global_logger import logger
from .assistant_utils import _openai_client
from .prompts.assistant_actions_prompts import ACTION_PROMPTS, ACTION_SCHEMAS

# Constants - Import from unified stage definition
from .candidate_stages import ALL_STAGES as STAGES, STAGE_DESCRIPTIONS

# AI Generation with Responses API ------------------------------
def init_chat(
    mode: str,
    name: str,
    job_info: Dict[str, Any],
    online_resume_text: str,
    chat_history: List[Dict[str, Any]]=[],
    chat_id: Optional[str] = None,
    kwargs: Optional[Dict[str, Any]] = {},
) -> Dict[str, Any]:
    """
    Initialize conversation and Zilliz record.
    
    Creates OpenAI conversation with job description and resume, then creates/updates Zilliz record
    with conversation_id for future message generation.
    
    Note: This function is called ONLY when we have the resume_text and BEFORE analyzing it.
    
    Args:
        name: str (candidate name)
        job_info: Dict with job position, description, requirements
        online_resume_text: str (candidate online resume text - REQUIRED)
        chat_id: Optional[str] (for chat workflows, None for recommend workflow)
        chat_history: Optional existing chat history to sync
        kwargs: Optional additional keyword arguments to pass to the function
    Returns:
        str: OpenAI conversation ID
    """
    
    # Create OpenAI thread
    conversation_metadata = {
        "chat_id": chat_id,
        "name": name,
        "job_applied": job_info["position"],
        "mode": mode,
    }

    
    # Add job description to thread
    job_info_text = json.dumps(job_info, ensure_ascii=False)
    job_prompt = {
        'type': 'message', 
        'role': 'developer',    
        'content': f'''你是招聘顾问，正在和候选人沟通。你的目标是根据岗位要求分析简历，
            通过对话的方式判断候选人是否符合岗位要求，可以提出问题让候选人回答，也可以介绍岗位要求。
            如果候选人的经验以及回复达到岗位要求，则可以推进到面试阶段，表达会通知HR尽快安排面试。
            以下是岗位描述，用于分析候选人的匹配程度:\n{job_info_text}'''
    }
    
    # Add candidate resume to thread
    full_history = [job_prompt] + chat_history
    
    # Create openai conversation
    full_history = [{'role': m['role'], 'content': m['content'], 'type': m.get('type', 'message')} for m in full_history]
    conversation = _openai_client.conversations.create(
        metadata=conversation_metadata, 
        items=full_history
    )

    # create candidate record
    kwargs.pop('chat_id', None)
    kwargs.pop('stage', None)
    kwargs.pop('conversation_id', None)
    kwargs.pop('metadata', None)
    candidate_id = upsert_candidate(
        chat_id=chat_id,
        stage=None,  # Not analyzed yet
        conversation_id=conversation.id,
        metadata={'history': chat_history},
        **kwargs,
    )
    if not candidate_id:
        raise RuntimeError("Failed to create candidate record")
    
    return {
        "conversation_id": conversation.id,
        "candidate_id": candidate_id,
    }

## ------------Main Message Generation----------------------------------

def generate_message(
    input_message: str|list[dict[str, str]],
    conversation_id: str,
    purpose: str
) -> Any:
    """
    Generate message using openai's assistant api.
    
    This method generates the next message in an existing conversation thread.
    It adds any new context (user message, full resume, etc.) to the thread
    and generates an appropriate response based on the purpose.
    
    Supports three scenarios:
    1) Recommend candidates: conversation_id from init_chat (no chat_id)
    2) Chat "新招呼": conversation_id from init_chat after passing chat_id
    3) Chat "沟通中/牛人已读未回": conversation_id retrieved from Zilliz by chat_id
    
    Args:
        conversation_id: OpenAI conversation ID (required) for the conversation
        input_message: User message to add to the conversation
        purpose: Message purpose - current supported purposes: "ANALYZE_ACTION", "CHAT_ACTION", "PLAN_PROMPTS"
    Returns:
        - purpose="ANALYZE_ACTION": dict (AnalysisSchema)
        - purpose="CHAT_ACTION"/"FOLLOWUP_ACTION": dict (ChatActionSchema)
        - otherwise: str (raw model text)
    """
    
    # conversation_id is now passed directly, no lookup needed
    assert conversation_id and conversation_id != 'null', "conversation_id is required"
    logger.debug(f"Generating message for purpose: {purpose}")
    instruction = ACTION_PROMPTS[purpose]
    json_schema = ACTION_SCHEMAS.get(purpose)

    # check input_message if list: { "type": "message", "role": "user", "content": "This is my new input." },
    if isinstance(input_message, list):
        for item in input_message:
            assert 'role' in item and 'content' in item, "input_message must be a list of dict with role, content"
    
    # Create a new run
    openai_config = get_openai_config()
    
    # Prefer parse() for reliable structured output (parse() does NOT support stream=True)
    # Use parse() directly for all purposes since they all have schemas
    response = _openai_client.responses.parse(
        conversation=conversation_id,
        instructions=instruction,
        input=input_message,
        text_format=json_schema,
        model=openai_config["model"],
        tools=[{"type": "web_search"}],  # Enable web search tool
    )
    result = response.output_parsed.model_dump()
    
    if purpose == "ANALYZE_ACTION":
        upsert_candidate(conversation_id=conversation_id, analysis=result)
    return result

# -----------------------------DingTalk Notification----------------------------------
def send_dingtalk_notification(
    title: str,
    message: str,
    job_id: str = None
) -> bool:
    """
    Send notification to DingTalk group chat using webhook.
    
    According to DingTalk documentation: https://open.dingtalk.com/document/dingstart/custom-bot-to-send-group-chat-messages
    
    Args:
        title: Title of the notification
        message: Message content to send
        job_id: Optional job ID to lookup job-specific notification config
        
    Returns:
        bool: True if message sent successfully, False otherwise
        
    Raises:
        ValueError: If webhook URL is not configured or message sending fails
    """
    # Priority: job.notification > default config
    # Initialize webhook_url and secret
    webhook_url = None
    secret = None
    
    # Try job-specific config first if job_id provided
    from src.jobs_store import get_job_by_id
    job = get_job_by_id(job_id)
    if job and job.get("notification"):
        notification = job.get("notification")
        if isinstance(notification, dict):
            webhook_url = notification.get("url")
            secret = notification.get("secret")
    
    # Fallback to default config if still not set
    if not webhook_url:
        dingtalk_config = get_dingtalk_config()
        webhook_url = dingtalk_config.get("url")
        secret = dingtalk_config.get("secret")
    
    if not webhook_url:
        logger.warning("DingTalk webhook URL is not configured, skipping notification")
        return False
    
    # Generate signature if secret is provided
    url = webhook_url
    if secret:
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode('utf-8'))
        
        # Append timestamp and signature to webhook URL
        separator = '&' if '?' in url else '?'
        url = f"{url}{separator}timestamp={timestamp}&sign={sign}"
    
    # Format message for DingTalk (markdown format)
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"## {title}\n\n{message}"
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10.0)
        response.raise_for_status()
        
        result = response.json()
        if result.get("errcode") != 0:
            logger.error(f"Failed to send DingTalk message: {result.get('errmsg', 'Unknown error')}")
            return False
        
        logger.info(f"DingTalk notification sent successfully: {title}")
        return True
    except Exception as exc:
        logger.exception(f"Failed to send DingTalk notification: {exc}")
        return False


__all__ = [
    "init_chat",
    "generate_message",
    "send_dingtalk_notification",
]
