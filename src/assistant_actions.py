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
from pydantic import BaseModel, Field

# Constants - Import from unified stage definition
from .candidate_stages import ALL_STAGES as STAGES, STAGE_DESCRIPTIONS
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
    "CHAT_ACTION": """
你作为星尘数据的招聘顾问，请用轻松口语化的风格和候选人沟通。请直接生成一条可以发送给候选人的自然语言消息，不要超过150字。不要发模板或者嵌入占位符，不要使用任何格式化、引号、JSON或括号。
如果是初次沟通，请针对候选人简历，根据岗位信息里面的drill_down_questions根据他经验最匹配的对应问题，提出问题。提问前可以根据候选人简历的特点和具体岗位契合点位进行评价，以及告知待验证的岗位要求。然后让候选人回答经验细节，或者澄清模棱两可的地方。重点在于挖掘过往经验，判断候选人是否符合岗位要求，而不是问工作时限等简历上写明的信息。
如果候选人信息中有外部链接（如博客），或者对候选人过往公司、项目经验不确定，可以通过web_search工具来获取更多信息，确保信息准确，不要猜测。
如果初次提问后，候选人表达对于公司或者岗位有疑问，或者对之前你提出的问题有疑问，尤其是高分（7分以上）的候选人，请优先回答候选人的问题、解答岗位疑问、介绍公司情况等，以打消其顾虑、提高他的求职意愿。
注意：最多问一次问题+一次追问！如果候选人认真回答了我们之前提出的问题，消除了岗位判断的疑虑/达到了岗位的要求，请做岗位介绍，尽快推进到面试阶段，表达会通知HR尽快安排面试。如果两次问题都没有得到满意的回答，则结束沟通。
如果候选人没有认真回答，或者如果回答不到位，或者一次问题+一次追问没有达到岗位匹配度，则根据态度决定是否继续聊天还是结束沟通。
如果判断候选人符合岗位要求（7分以上），则表达希望尽快进行面试沟通。但不要约具体的时间，而是告知会通知HR尽快安排面试。
请不要透露我们的岗位筛选标准，不要提及薪资问题，不必提及到岗时间，不要问候选人已经在简历中的信息，例如年龄、学校是否211、经验年限等，回避讨论涉及年龄/性别/婚姻状况等敏感信息。
请不要向候选人索取代码、流程图或者其他属于工作隐私的内容，只能通过问答的方式来判断候选人是否符合岗位要求。
如果候选人表达工作地点不合适、薪资不合适、工作年限不合适等，请结束沟通。
结束沟通请直接回复"收到"。
如果候选人没有兴趣/态度恶劣/不耐烦，或者有其他不适合继续沟通的情况，根据他的overall_score分数有两种情况：
1. 分数低于7分，没有必要再沟通；直接判断为“不合适”，回复“<PASS>: 不合适理由”，系统会自动PASS这个候选人。
2. 分数大于等于7分，可以继续沟通，但是需要转变沟通策略，不要再问问题，而是主动介绍公司情况、岗位要求、薪资待遇等，打消其顾虑、提高他的求职意愿。
""",
    "ANALYZE_ACTION": f"""请根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。
    首先根据岗位要求，判断候选人是否符合岗位要求，如果符合岗位要求，则进行加分；如果不符合岗位要求，则进行减分。硬性要求扣分更多，软性要求扣分更少。
    然后关注keyword里面的正负向关键词，如果简历中匹配关键词，要进行相对应的加分或减分。
    仔细查看候选人的项目经历，检查是否有言过其词的情况。同时判断过往经验是否匹配岗位要求。
    最后，还要查看候选人的过往公司类型、行业类型、工作内容等经历，判断是否符合岗位要求。
    请给出 1-10 的四个评分：技能匹配度、创业契合度、基础背景、综合评分，并提供简要分析。""",
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


class AnalysisSchema(BaseModel):
    """Analysis schema for the candidate."""
    skill: int = Field(description="技能、经验匹配度，满分10分")
    startup_fit: int = Field(description="创业公司契合度，抗压能力、对工作的热情程度，满分10分")
    background: int = Field(description="基础背景、学历优秀程度、逻辑思维能力，满分10分")
    overall: int = Field(description="综合评分，满分10分，6分为及格/待定，7分为基本满足岗位要求/推进面试，8分为优秀，9分为卓越，10分为完全满足岗位要求")
    summary: str = Field(description="分析总结，不要超过200字")
    followup_tips: str = Field(description="后续招聘顾问跟进的沟通策略，不要超过200字")


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
        'content': f'你是招聘顾问，正在和候选人沟通。你的目标是根据岗位要求分析简历，\
            通过对话的方式判断候选人是否符合岗位要求，可以提出问题让候选人回答，也可以介\
            绍岗位要求。如果候选人的经验以及回复达到岗位要求，则可以推进到面试阶段，\
            表达会通知HR尽快安排面试。\
            以下是岗位描述，用于分析候选人的匹配程度:\n{job_info_text}'
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
) -> Dict[str, Any]:
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
        Dict with:
            - message: str (generated message)
            - analysis: dict (if purpose="ANALYZE_ACTION")
            - plan: dict (if purpose="PLAN_PROMPTS")
    """
    
    # conversation_id is now passed directly, no lookup needed
    assert conversation_id and conversation_id != 'null', "conversation_id is required"
    logger.debug(f"Generating message for purpose: {purpose}")
    instruction = ACTION_PROMPTS[purpose]
    if purpose in ["ANALYZE_ACTION", "PLAN_PROMPTS"]:
        json_schema = AnalysisSchema
    else:
        json_schema = None

    # check input_message if list: { "type": "message", "role": "user", "content": "This is my new input." },
    if isinstance(input_message, list):
        for item in input_message:
            assert 'role' in item and 'content' in item, "input_message must be a list of dict with role, content"
    
    # Create a new run
    openai_config = get_openai_config()
    if json_schema:
        if purpose == "ANALYZE_ACTION":
            response = _openai_client.responses.parse(
                conversation=conversation_id,
                instructions=instruction,
                input= input_message,
                text_format=json_schema,
                model=openai_config["model"],
                tools=[{"type": "web_search"}],  # Enable web search tool
            )
            result = response.output_parsed.model_dump() 
            upsert_candidate(conversation_id=conversation_id, analysis=result)
        else:
            raise NotImplementedError(f"Unsupported purpose: {purpose}")
        return result
    else:
        # Enable web search tool to parse URLs from chat if necessary
        response = _openai_client.responses.create(
            conversation=conversation_id,
            instructions=instruction,
            input=input_message,
            model=openai_config["model"],
            tools=[{"type": "web_search"}],  # Enable web search tool
        )
        return response.output_text
    


# ============================================================================
# DingTalk Notification
# ============================================================================

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
