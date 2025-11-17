"""LangGraph tools that call FastAPI service endpoints."""
from datetime import datetime
from langgraph.graph import END
import requests, time, json, base64
import hmac, hashlib
import urllib.parse
from typing import Any, Dict, List, Optional, Callable, Annotated, Literal
from langgraph.prebuilt import InjectedState, InjectedStore
from langchain.tools import tool, ToolRuntime, InjectedToolCallId
from langgraph.runtime import get_runtime
from langgraph.types import Command, interrupt
from langchain_core.messages import ToolMessage, HumanMessage, AIMessage
from src.global_logger import logger
from agent.states import ContextSchema, Candidate, ManagerState, RecruiterState
from langchain_core.runnables import RunnableConfig


current_timestr = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _call_api(method: str, url: str, data: dict | None = None, timeout: float = 30.0) -> Dict:
    """Make HTTP request to FastAPI service."""

    if method.upper() == "GET":
        response = requests.get(url, params=data, timeout=timeout)
    elif method.upper() == "POST":
        response = requests.post(url, json=data, timeout=timeout)
    elif method.upper() == "PUT":
        response = requests.put(url, json=data, timeout=timeout)
    elif method.upper() == "DELETE":
        # response = requests.delete(url, timeout=timeout)
        raise NotImplementedError("DELETE method is not supported")
    else:
        raise NotImplementedError(f"Unsupported method: {method}")
        
    response.raise_for_status()
    
    if response.headers.get("content-type") == "application/json":
        return response.json()
    else:
        return response.text


def _send_dingtalk_message(webhook_url: str, message: str, title: str, secret: str=None) -> bool:
    """
    Send message to DingTalk group chat using webhook.
    
    According to DingTalk documentation: https://open.dingtalk.com/document/dingstart/custom-bot-to-send-group-chat-messages
    
    Args:
        webhook_url: DingTalk webhook URL
        secret: DingTalk secret for signature (optional, empty string if not used)
        message: Message content to send
        title: Optional title for the message
        
    Returns:
        bool: True if message sent successfully, False otherwise
    """
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
    
    
    # If title is provided, use markdown format for better formatting
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"## Boss直聘候选人跟进通知\n\n{message}"
        }
    }
    
    response = requests.post(url, json=payload, timeout=10.0)
    response.raise_for_status()
    
    result = response.json()
    if result.get("errcode") != 0:
        logger.error(f"Failed to send DingTalk message: {result.get('errmsg', 'Unknown error')}")
        raise ValueError(f"Failed to send DingTalk message: {result.get('errmsg', 'Unknown error')}")

    return True

# ============================================================================
# Manager Tools
# ============================================================================

@tool
def get_candidates_tool(mode: str, job_title: str, limit: int, tool_call_id: Annotated[str, InjectedToolCallId]) -> List[Dict]:
    """
    Navigate to candidates page and get candidate list.
    
    This tool retrieves a list of candidates from Boss直聘 based on candidate type.
    Use this to discover available candidates for recruitment.
    
    Args:
        mode (str): Candidate type filter - "greet", "chat", "followup", "recommend" (default: "recommend")
        job_title (str): Job title filter - specific job title to filter by (default: "")
        limit (int): Limit the number of candidates to return (default: 30)
        
    Returns:
        List[Dict]: List of candidates with their details (chat_id, name, last_message, time, unread status)
        
    Usage:
        - Call after start_browser_tool to get candidate list
        - Use candidate_type to filter by recruitment stage:
          * "greet" - New greetings/candidates
          * "chat" - Candidates in communication
          * "followup" - Candidates who read but haven't replied
          * "recommend" - Navigate to recommendation page and get recommended candidates
        - Returns candidate data including chat_id for further operations
    """
    runtime = get_runtime(ManagerState)
    web_portal = runtime.context.web_portal
    timeout = runtime.context.timeout
    writer = runtime.stream_writer
    # Handle recommend mode separately
    if mode == "recommend":
        params = {
            "job_title": job_title,
            "limit": limit
        }
        writer(f"Getting recommended candidates for job title: {job_title}...")
        result = _call_api("GET", f"{web_portal}/recommend/candidates", params, timeout=timeout)
    else:
        # Map candidate_type to tab and status filters based on Streamlit logic
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
            # Default to all candidates
            raise ValueError(f"Invalid mode: {mode}")
        
        # params = f"?tab={tab_filter}&status={status_filter}&job_title={job_title}"
        params = {
            "tab": tab_filter,
            "status": status_filter,
            "job_title": job_title,
            "limit": limit
        }
        writer(f"Getting {mode} candidates for job title: {job_title}...")
        result = _call_api("GET", f"{web_portal}/chat/dialogs", params, timeout=timeout)
        for candidate in result: candidate['mode'] = mode

    candidates = [Candidate(**candidate) for candidate in result]
    return Command(
        update={
            'candidates': candidates,
            'messages': [ToolMessage(json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id)]
        }
    )
    # return result

@tool
def dispatch_candidate_tool(
        candidate: dict, assistant_name: str, 
        tool_call_id: Annotated[str, InjectedToolCallId]
    ) -> Command[Literal['dispatch_recruiter']]:
    """
    Dispatch a candidate to the recruiter agent.
    Args:
        candidate: dict - The candidate information to process(required), must contain the following fields:
            name: The name of the candidate
            mode: The mode of the candidate
            chat_id: The chat ID of the candidate in mode='chat'|'followup'|'greet'", default=None
            index: The index of the candidate in the recommended mode", default=None
            job_applied: The job title applied by the candidate
            description: The description of the candidate, must be a string
    """
    candidate = Candidate(**candidate)
    manager_messages = ToolMessage(content=f"现在我们来处理候选人{candidate.name}，我们使用的助手风格是：\n{assistant_name}，我们的岗位是：\n{candidate.job_applied}", tool_call_id=tool_call_id)
    return Command(
        update={
            'assistant_name': assistant_name,
            'current_candidate': candidate,
            'messages': [manager_messages]
        },
        goto='dispatch_recruiter'
    )


@tool
def manager_finish_tool(report: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command[Literal[END]]:
    """
    This tool finishes/pauses the manager process.
    
    Args:
        report: str - The summary of the manager process (in less than 400 words). 
        
    Usage:
        Call this tool when you:
        - finished all candidates process
        - there is any error in the manager process and need to notify the user
    """
    return Command(
        update={
            'messages': [ToolMessage(content=f'已结束招聘流程，总结如下:\n{report}', tool_call_id=tool_call_id)]
        },
        goto=END
    )    


# ============================================================================
# Recruiter Action Tools, should be combined with human-in-the-loop actions
# ============================================================================

@tool
def finish_tool(report: str, 
                state: Annotated[RecruiterState, InjectedState],
                config: RunnableConfig,
                tool_call_id: Annotated[str, InjectedToolCallId]
            ) -> dict:
    """
    This tool finishes/pauses the recruitment process.
    
    Args:
        report: str - The summary of the recruitment process (in less than 200 words). 
        It should include the candidate name, the stage of the candidate, and the analysis and reasoning for the decision.
        Also include instructions for the HR to follow up conversation with the candidate.
        
    Usage:
        Call this tool when you:
        - finished current candidate process and are waiting for candidate reply
        - the candidate is not suitable for the position
        - there is any error in the recruitment process
    """
    messages = [f'{m.type}: {m.content[:100]}' for m in state.messages if m.type in ['human', 'ai'] and m.content]
    report_dict = {
        'report': report,
        'stage': state.stage,
        'analysis': state.analysis,
        'messages': messages,
        'time': current_timestr()
    }

    # Doesn't work in CLI/Studio
    # resume_instruction = interrupt({
    #     'time': current_timestr(),
    #     'candidate': state.candidate.model_dump(),
    #     'report': report,
    #     'messages': messages,
    #     'thread_id': config['configurable'].get('thread_id')
    # })
    return report_dict


@tool
def analyze_resume_tool(
    skill: int, 
    startup_fit: int, 
    background: int, 
    overall: int, 
    summary: str, 
    followup_tips: str,
    tool_call_id: Annotated[str, InjectedToolCallId]
    ) -> Command:
    '''
    根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。
    尤其是岗位要求中的keyword里面的正负向关键词要进行加分和减分。
    另外也要仔细查看候选人的项目经历，检查是否有言过其词、模棱两可的情况。
    最后，还要查看候选人的过往工作经历，判断是否匹配岗位要求。
    请给出 1-10 的四个评分：
        - 其中6分为及格：满足岗位要求的底线
        - 8分为良好：基本满足岗位要求，并且有亮点
        - 9分为优秀：满足岗位要求，是一位稀有的候选人
        - 10分为非常优秀：完全满足岗位要求，并且有很强的竞争力
    args:
        skill: int - 技能、经验匹配度
        startup_fit: int - 创业公司契合度，抗压能力、对工作的热情程度
        background: int - 基础背景、学历优秀程度、逻辑思维能力
        overall: int - 综合评分
        summary: str - 分析总结，不要超过200字
        followup_tips: str - 后续招聘顾问跟进的沟通策略，不要超过100字
    '''
    analysis = {
        'skill': skill,
        'startup_fit': startup_fit,
        'background': background,
        'overall': overall,
        'summary': summary,
        'followup_tips': followup_tips
    }
    if overall < 7:
        stage = 'PASS'
    elif overall < 9:
        stage = 'GREET'
    else:
        stage = 'SEEK'
    return Command(
        update={
            'stage': stage,
            'analysis': analysis,
            'messages': [ToolMessage(json.dumps(analysis, ensure_ascii=False), tool_call_id=tool_call_id)]
        }
    )


@tool
def notify_hr_tool(title: str, report: str, stage: str, contact_info: str) -> bool:
    """
    notify HR when the candidate is in SEEK stage and has been contacted.
    Args:
        title: str - The title of the notification, in less than 20 words.
        report: str - The summary of the notification (in less than 100 words) in markdown format. 
            It should include the candidate name, the stage of the candidate, and the analysis and reasoning for the decision.
            Also include instructions for the HR to follow up conversation with the candidate.
        stage: str - The stage of the candidate
        contact_info: str - Contact information received from the candidate (phone, WeChat, etc.)
    Returns:
        bool: True if notification sent successfully, False otherwise
    Usage:
        Call this tool when the candidate is in SEEK stage and contact information is received from the candidate
    """
    if stage != 'SEEK':
        raise ValueError(f"Candidate is not in SEEK stage: {stage}")

    runtime = get_runtime(RecruiterState)
    webhook_url = runtime.context.dingtalk_webhook
    
    if not webhook_url:
        raise ValueError("DingTalk webhook URL is not configured, skipping notification")
    
    # Format message for DingTalk
    message = f"{report}\n\n联系方式: {contact_info}"
    
    success = _send_dingtalk_message(webhook_url, message, title)
    return success


# ============================================================================
# Recruiter Chat Tools
# ============================================================================

@tool
def send_chat_message_tool(chat_id: str, message: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """
    Send message to candidate in chat page
    Note: not working for recommend mode
    
    This tool sends a text message to a specific candidate in their chat.
    Use this for all communication with candidates including greetings, questions, and follow-ups.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        message (str): Text message to send to the candidate
        
    Returns:
        str: Confirmation message if sent successfully, error message otherwise
        
    Usage:
        - Use chat_id from navigate_to_candidates_tool results
        - Message should be natural and professional
        - Keep messages concise and relevant to recruitment context
    """
    runtime = get_runtime(RecruiterState)
    web_portal = runtime.context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/{chat_id}/send_message", {"message": message})
    return Command(
        update={
            'messages': [
                ToolMessage(content='已发送消息', tool_call_id=tool_call_id),
                AIMessage(content=message),
            ]
        }
    )


@tool
def get_chat_messages_tool(chat_id: str, state: Annotated[RecruiterState, InjectedState], tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """
    Note: not working for recommend mode
    
    This tool retrieves the complete message history for a candidate chat.
    Use this to understand conversation context and candidate responses.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        
    Returns:
        str: JSON array of messages with timestamps, senders, and content
        
    Usage:
        - Call with chat_id to get conversation history
        - Use to understand candidate's communication style and responses
        - Helpful for generating contextual follow-up messages
    """
    runtime = get_runtime(RecruiterState)
    web_portal = runtime.context.web_portal
    all_messages_in_boss = _call_api("GET", f"{web_portal}/chat/{chat_id}/messages")
    # append new candidate messages to state.messages
    state_candidate_messagess = [m.content for m in state.messages if m.type == 'human']
    new_user_messages = [ToolMessage(content='已获取消息历史', tool_call_id=tool_call_id)]
    for message in all_messages_in_boss:
        if message['type'] == 'candidate' and message['message'] not in state_candidate_messagess:
            candidate_message = HumanMessage(content=message['message'])
            new_user_messages.append(candidate_message)
            logger.info(f"Inserted candidate message: {message}")

    return Command(
        update={
            'messages': new_user_messages
        }
    )


@tool
def greet_candidate_tool(identifier: str, message: str, mode: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """
    Send greeting message to candidate.
    
    This tool sends an initial greeting message to a candidate.
    Use this to start conversations with new potential candidates.
    
    Args:
        identifier (str): chat_id for chat/greet/followup modes, or candidate index for recommend mode
        message (str): Greeting message to send to the candidate
        mode (str): Mode of operation - "chat", "greet", "followup", or "recommend" (default: "chat")
        
    Returns:
        str: Confirmation message if greeting sent successfully, error message otherwise
        
    Usage:
        - For chat/greet/followup modes: use chat_id from get_candidates_tool results
        - For recommend mode: use candidate index from get_recommended_candidates_tool results
        - Message should be professional and introduce the opportunity
        - This initiates the recruitment conversation
        - Mode parameter determines which endpoint to use:
          * "chat", "greet", "followup" - Uses /chat/greet with chat_id
          * "recommend" - Uses /recommend/candidate/{index}/greet with candidate index
    """
    runtime = get_runtime(RecruiterState)
    web_portal = runtime.context.web_portal
    if mode == "recommend":
        # For recommend mode, identifier is the candidate index
        result = _call_api("POST", f"{web_portal}/recommend/candidate/{identifier}/greet", {"message": message})
    else:
        # For chat/greet/followup modes, identifier is the chat_id
        result = _call_api("POST", f"{web_portal}/chat/greet", {"chat_id": identifier, "message": message})
    if result is not True:
        raise ValueError(f"Failed to send greeting message: {result}")
    
    return Command(
        update={
            'messages': [
                ToolMessage(content='已发送问候消息', tool_call_id=tool_call_id),
                AIMessage(content=message),
            ]
        }
    )


@tool
def request_contact_tool(chat_id: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """
    This tool sends a request for contact information (phone number, WeChat number) to a candidate.
    Use this when the candidate is in SEEK stage and before you send notification message to HR.
    It will also send a dingtalk message to HR.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
    Returns:
        str: Confirmation message if contact request sent successfully, error message otherwise
    Usage:
        - Use when candidate shows strong fit for the position and is in SEEK stage.
        - We request contact information for further communication with the candidate.
    """
    runtime = get_runtime(RecruiterState)
    stage = runtime.state.stage
    if stage != 'SEEK':
        raise ValueError(f"Candidate is not in SEEK stage: {stage}")
    web_portal = runtime.context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/contact/request", {"chat_id": chat_id})
    
    return Command(
        update={
            'messages': [ToolMessage(content='已请求联系方式', tool_call_id=tool_call_id)]  
        }
    )

# ============================================================================
# Resume Tools (Unified for all modes)
# ============================================================================

@tool
def request_full_resume_tool(chat_id: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """
    Request full resume from candidate.
    
    This tool sends a request to the candidate asking for their complete resume.
    Use this when you need more detailed information than the online resume provides.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        
    Returns:
        str: Confirmation message if request sent successfully, error message otherwise
        
    Usage:
        - Use when online resume is insufficient for analysis
        - Typically used after initial screening shows potential
        - Candidate will receive a request for their full resume
    """
    runtime = get_runtime(RecruiterState)
    web_portal = runtime.context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/resume/request_full", {"chat_id": chat_id})
    return Command(
        update={
            'messages': [ToolMessage(content=f'已向候选人请求完整简历，请稍后检查完整简历是否存在', tool_call_id=tool_call_id)]
        }
    )


@tool
def view_online_resume_tool(
        chat_id: Optional[str], 
        index:Optional[int], 
        mode: str, 
        state: Annotated[RecruiterState, InjectedState],
        config: RunnableConfig,
        tool_call_id: Annotated[str, InjectedToolCallId]
    ) -> Command:
    """
    View online resume details.
    
    This tool retrieves the candidate's online resume from Boss直聘.
    Use this to get basic resume information for initial screening.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate for chat/greet/followup modes
        index (int): Candidate index for recommend mode
        mode (str): Mode of operation - "chat", "greet", "followup", or "recommend"
        
    Returns:
        str: JSON data containing resume text, candidate name, and chat_id
        
    Usage:
        - Use for initial candidate screening in any mode
        - Provides basic resume information
        - Faster than requesting full resume
        - Mode parameter determines which endpoint to use:
          * "chat", "greet", "followup" - Uses /chat/resume/online/{chat_id}
          * "recommend" - Uses /recommend/candidate/{index}/resume
    """
    runtime = get_runtime(RecruiterState)
    web_portal = runtime.context.web_portal
    if mode == "recommend":
        # For recommend mode, chat_id is actually the candidate index
        assert index is not None, "Index is required for recommend mode"
        result = _call_api("GET", f"{web_portal}/recommend/candidate/{index}/resume")
    else:
        # For chat/greet/followup modes, use chat_id as normal
        assert chat_id is not None, "Chat ID is required for chat/greet/followup modes"
        result = _call_api("GET", f"{web_portal}/chat/resume/online/{chat_id}")
    
    # Extract resume_text from result regardless of mode
    resume_text = result.get('text', '')
    
    if chat_id:
        from agent.graph import NAME_SPACE
        store = runtime.store
        store.put(
            namespace=NAME_SPACE, 
            key=chat_id, 
            value={
                'resume': resume_text,
                'checkpoint_ns': config['configurable']['checkpoint_ns'],
            }, 
            index=["resume"]
        )

    return Command(
        update={
            'messages': [
                ToolMessage(content=f'已获取在线简历', tool_call_id=tool_call_id),
                HumanMessage(content=f'这是我的在线简历，请查收：\n {resume_text}'),
            ]
        }
    )


@tool
def view_full_resume_tool(chat_id: str, mode:str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """
    View full resume details in chat page only. Not working for recommend mode.
    
    This tool retrieves the candidate's complete resume with all details.
    Use this when you need comprehensive resume information for detailed analysis.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        mode (str): Mode of operation - "chat", "greet", "followup", or "recommend" (default: "chat")
        
    Returns:
        str: status of getting full resume
        
    Usage:
        - Use for detailed candidate analysis in any mode
        - Provides complete resume information
        - May take longer to retrieve than online resume
        - Mode parameter determines which endpoint to use:
          * "chat", "greet", "followup" - Uses /chat/resume/full/{chat_id}
          * "recommend" - Uses /recommend/candidate/{index}/resume (same as online for recommend)
    """
    assert mode != "recommend", "Full resume is not available for recommend mode"
    runtime = get_runtime(RecruiterState)
    web_portal = runtime.context.web_portal
    result = _call_api("GET", f"{web_portal}/chat/resume/full/{chat_id}")
    return Command(
        update={
            'messages': [
                ToolMessage(content=f'已获取完整简历', tool_call_id=tool_call_id),
                HumanMessage(content=f'这是我的完整简历，请查收：\n {result}'),
            ]
        }
    )



@tool
def check_resume_availability_tool(chat_id: str) -> str:
    """
    Check if full resume is available for candidate.
    
    This tool checks whether a candidate has a full resume available.
    Use this to determine if you can request a full resume from the candidate.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        
    Returns:
        str: Boolean result indicating if full resume is available
        
    Usage:
        - Use before viewing full resume
        - Returns true if full resume is available, false otherwise
        - Helps determine next steps in the recruitment process
    """
    runtime = get_runtime(RecruiterState)
    web_portal = runtime.context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/resume/check_full_resume_available", {"chat_id": chat_id})
    return result



@tool
def accept_full_resume_tool(chat_id: str) -> str:
    """
    Accept candidate's fullresume.
    
    This tool accepts a candidate's full resume in the chat interface.
    Use this when you want to accept a candidate's resume submission.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        
    Returns:
        str: Confirmation message if resume accepted successfully, error message otherwise
        
    Usage:
        - Use when candidate has submitted a resume and you want to accept it
        - This confirms acceptance of the candidate's resume
        - Typically used after `check_resume_availability_tool` is true
    """
    runtime = get_runtime(RecruiterState)
    web_portal = runtime.context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/resume/accept", {"chat_id": chat_id})
    return '已接受简历' if result else '简历未成功接收或为收到完整简历'



# TODO: deprecated, not working for recommend mode
@tool
def discard_candidate_tool(chat_id: str) -> str:
    """
    Discard candidate from chat.
    
    This tool discards a candidate from the chat interface.
    Use this when a candidate is not suitable for the position.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        
    Returns:
        str: Confirmation message if candidate discarded successfully, error message otherwise
        
    Usage:
        - Use chat_id from get_candidates_tool results
        - This removes the candidate from active consideration
        - Use when candidate doesn't meet requirements
    """
    runtime = get_runtime(RecruiterState)
    web_portal = runtime.context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/candidate/discard", {"chat_id": chat_id})
    return result


# ============================================================================
# Tool Groups
# ============================================================================

# Browser tools
manager_tools = [
    get_candidates_tool,
    dispatch_candidate_tool,
    manager_finish_tool
]

# Communication tools  
chat_tools: List[Callable[..., Any]] = [
    send_chat_message_tool,
    get_chat_messages_tool,
    greet_candidate_tool,
    request_contact_tool
]

# Resume tools
resume_tools: List[Callable[..., Any]] = [
    request_full_resume_tool,
    view_online_resume_tool,
    view_full_resume_tool,
    # accept_resume_tool,
    check_resume_availability_tool,
]

action_tools: List[Callable[..., Any]] = [
    finish_tool,
    analyze_resume_tool,
    notify_hr_tool,
]
