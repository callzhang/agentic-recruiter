"""LangGraph tools that call FastAPI service endpoints."""

import requests
import json
from typing import Any, Dict, List, Optional, Callable
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from langchain_core.messages import AnyMessage
from src.global_logger import logger
from agent.states import ContextSchema
from langgraph.runtime import Runtime



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



# ============================================================================
# Manager Tools
# ============================================================================

@tool
def get_candidates_tool(mode: str, job_title: str, limit: int, context: ContextSchema) -> str:
    """
    Navigate to candidates page and get candidate list.
    
    This tool retrieves a list of candidates from Boss直聘 based on candidate type.
    Use this to discover available candidates for recruitment.
    
    Args:
        candidate_type (str): Candidate type filter - "greet", "chat", "followup", "recommend" (default: "recommend")
        job_title (str): Job title filter - specific job title to filter by (default: "")
        context (ContextSchema): Context schema containing browser endpoint and web portal
        
    Returns:
        str: JSON list of candidates with their details (chat_id, name, last_message, time, unread status)
        
    Usage:
        - Call after start_browser_tool to get candidate list
        - Use candidate_type to filter by recruitment stage:
          * "greet" - New greetings/candidates
          * "chat" - Candidates in communication
          * "followup" - Candidates who read but haven't replied
          * "recommend" - Navigate to recommendation page and get recommended candidates
        - Returns candidate data including chat_id for further operations
    """
    web_portal = context.web_portal
    # Handle recommend mode separately
    if mode == "recommend":
        result = _call_api("GET", f"{web_portal}/recommend/candidates", {"job_title": job_title, "limit": limit})
        return result
    
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
    
    params = f"?tab={tab_filter}&status={status_filter}&job_title={job_title}"
    result = _call_api("GET", f"{web_portal}/chat/dialogs{params}")
    return result



# ============================================================================
# Recruiter Read Tools
# ============================================================================

@tool
def send_chat_message_tool(chat_id: str, message: str, context: ContextSchema) -> str:
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
    web_portal = context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/{chat_id}/message", {"message": message})
    return result


@tool
def get_chat_messages_tool(chat_id: str, context: ContextSchema) -> str:
    """
    Read message history from chat page.
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
    web_portal = context.web_portal
    result = _call_api("GET", f"{web_portal}/chat/{chat_id}/messages")
    return result


@tool
def ask_contact_tool(chat_id: str, message: str, context: ContextSchema) -> str:
    """
    Ask candidate for contact information in chat page.
    Note: not working for recommend mode
    
    This tool sends a message specifically requesting contact details (phone, WeChat, etc.)
    from the candidate. Use this when the candidate shows interest and you need their contact info.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        message (str): Message requesting contact information
        
    Returns:
        str: Confirmation message if sent successfully, error message otherwise
        
    Usage:
        - Use when candidate shows strong interest in the position
        - Message should politely request contact information
        - Typically used after initial screening and positive responses
    """
    web_portal = context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/{chat_id}/message", {"message": message})
    return result


# ============================================================================
# Resume Tools (Unified for all modes)
# ============================================================================

@tool
def request_full_resume_tool(chat_id: str, context: ContextSchema) -> str:
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
    web_portal = context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/resume/request", {"chat_id": chat_id})
    return result


@tool
def view_online_resume_tool(chat_id: str, index:int, mode: str, context: ContextSchema) -> str:
    """
    View online resume details.
    
    This tool retrieves the candidate's online resume from Boss直聘.
    Use this to get basic resume information for initial screening.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        mode (str): Mode of operation - "chat", "greet", "followup", or "recommend" (default: "chat")
        
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
    web_portal = context.web_portal
    if mode == "recommend":
        # For recommend mode, chat_id is actually the candidate index
        result = _call_api("GET", f"{web_portal}/recommend/candidate/{index}/resume")
    else:
        # For chat/greet/followup modes, use chat_id as normal
        result = _call_api("GET", f"{web_portal}/chat/resume/online/{chat_id}")
    
    return result


@tool
def view_full_resume_tool(chat_id: str, mode:str, context: ContextSchema) -> str:
    """
    View full resume details in chat page only. Not working for recommend mode.
    
    This tool retrieves the candidate's complete resume with all details.
    Use this when you need comprehensive resume information for detailed analysis.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        mode (str): Mode of operation - "chat", "greet", "followup", or "recommend" (default: "chat")
        
    Returns:
        str: JSON data containing full resume text and page images
        
    Usage:
        - Use for detailed candidate analysis in any mode
        - Provides complete resume information
        - May take longer to retrieve than online resume
        - Mode parameter determines which endpoint to use:
          * "chat", "greet", "followup" - Uses /chat/resume/full/{chat_id}
          * "recommend" - Uses /recommend/candidate/{index}/resume (same as online for recommend)
    """
    assert mode != "recommend", "Full resume is not available for recommend mode"
    web_portal = context.web_portal
    result = _call_api("GET", f"{web_portal}/chat/resume/full/{chat_id}")
    return result



@tool
def check_resume_availability_tool(chat_id: str, context: ContextSchema) -> str:
    """
    Check if full resume is available for candidate.
    
    This tool checks whether a candidate has a full resume available.
    Use this to determine if you can request a full resume from the candidate.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        
    Returns:
        str: Boolean result indicating if full resume is available
        
    Usage:
        - Use before requesting full resume
        - Returns true if full resume is available, false otherwise
        - Helps determine next steps in the recruitment process
    """
    web_portal = context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/resume/check_full_resume_available", {"chat_id": chat_id})
    return result



@tool
def accept_resume_tool(chat_id: str, context: ContextSchema) -> str:
    """
    Accept candidate's resume.
    
    This tool accepts a candidate's resume in the chat interface.
    Use this when you want to accept a candidate's resume submission.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        
    Returns:
        str: Confirmation message if resume accepted successfully, error message otherwise
        
    Usage:
        - Use when candidate has submitted a resume and you want to accept it
        - This confirms acceptance of the candidate's resume
        - Typically used after reviewing the resume
    """
    web_portal = context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/resume/accept", {"chat_id": chat_id})
    return result


# ============================================================================
# Recruiter Actions Tools, should be combined with human-in-the-loop actions
# ============================================================================

@tool
def greet_candidate_tool(identifier: str, message: str, mode: str, context: ContextSchema) -> str:
    """
    Send greeting message to candidate.
    
    This tool sends an initial greeting message to a candidate.
    Use this to start conversations with new potential candidates.
    
    Args:
        identifier (str): Chat ID for chat/greet/followup modes, or candidate index for recommend mode
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
    web_portal = context.web_portal
    if mode == "recommend":
        # For recommend mode, identifier is the candidate index
        result = _call_api("POST", f"{web_portal}/recommend/candidate/{identifier}/greet", {"message": message})
    else:
        # For chat/greet/followup modes, identifier is the chat_id
        result = _call_api("POST", f"{web_portal}/chat/greet", {"chat_id": identifier, "message": message})
    return result


@tool
def discard_candidate_tool(chat_id: str, context: ContextSchema) -> str:
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
    web_portal = context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/candidate/discard", {"chat_id": chat_id})
    return result


@tool
def request_contact_tool(chat_id: str, context: ContextSchema) -> str:
    """
    Request contact information from candidate.
    
    This tool sends a request for contact information (phone, WeChat, etc.) to a candidate.
    Use this when the candidate shows interest and you need their contact details.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        
    Returns:
        str: Confirmation message if contact request sent successfully, error message otherwise
        
    Usage:
        - Use when candidate shows strong interest in the position
        - This requests contact information for further communication
        - Typically used after initial screening and positive responses
    """
    web_portal = context.web_portal
    result = _call_api("POST", f"{web_portal}/chat/contact/request", {"chat_id": chat_id})
    return result


# ============================================================================
# Store Tools
# ============================================================================

@tool
def get_candidate_from_store_tool(chat_id: str, context: ContextSchema) -> str:
    """
    Get candidate information from store.
    
    This tool retrieves candidate information from the Zilliz vector store.
    Use this to get stored candidate data including analysis and history.
    
    Args:
        chat_id (str): Unique chat identifier for the candidate
        
    Returns:
        str: JSON data containing candidate information from store
        
    Usage:
        - Use to retrieve stored candidate data
        - Returns comprehensive candidate information including analysis
        - Useful for checking existing candidate records
    """
    web_portal = context.web_portal
    result = _call_api("GET", f"{web_portal}/store/candidate/{chat_id}")
    return result


@tool
def find_candidate_by_resume_tool(resume_text: str, context: ContextSchema) -> str:
    """
    Find candidate by resume similarity.
    
    This tool searches for existing candidates by resume text similarity.
    Use this to check if a candidate already exists in the system.
    
    Args:
        resume_text (str): Resume text to search for
        
    Returns:
        str: JSON data containing matching candidate information
        
    Usage:
        - Use to check for duplicate candidates
        - Returns similar candidates based on resume content
        - Helps avoid processing the same candidate multiple times
    """
    web_portal = context.web_portal
    result = _call_api("POST", f"{web_portal}/store/candidate/get-by-resume", {"resume_text": resume_text})
    return result


# ============================================================================
# Thread Management Tools
# ============================================================================

@tool
def init_chat_thread_tool(candidate_id: str, assistant_id: str, job_id: str, context: ContextSchema) -> str:
    """
    Initialize chat thread for candidate.
    
    This tool initializes a new chat thread for a candidate with an assistant.
    Use this to start a new conversation thread for AI-powered interactions.
    
    Args:
        candidate_id (str): Unique identifier for the candidate
        assistant_id (str): OpenAI assistant ID to use
        job_id (str): Job ID for context
        
    Returns:
        str: Thread ID and initialization status
        
    Usage:
        - Use to start new AI conversations with candidates
        - Returns thread_id for subsequent operations
        - Required before using AI analysis tools
    """
    web_portal = context.web_portal
    data = {
        "candidate_id": candidate_id,
        "assistant_id": assistant_id,
        "job_id": job_id
    }
    result = _call_api("POST", f"{web_portal}/chat/init-chat", data)
    return result


@tool
def get_thread_messages_tool(thread_id: str, context: ContextSchema) -> str:
    """
    Get messages from chat thread.
    
    This tool retrieves all messages from a specific chat thread.
    Use this to get the conversation history for a thread.
    
    Args:
        thread_id (str): Unique thread identifier
        
    Returns:
        str: JSON array of messages from the thread
        
    Usage:
        - Use to retrieve conversation history
        - Returns all messages in chronological order
        - Useful for understanding conversation context
    """
    web_portal = context.web_portal
    result = _call_api("GET", f"{web_portal}/chat/{thread_id}/messages")
    return result

# ============================================================================
# Tool Groups
# ============================================================================

# Browser tools
manager_tools = [
    get_candidates_tool,
]

# Communication tools  
chat_tools: List[Callable[..., Any]] = [
    send_chat_message_tool,
    get_chat_messages_tool,
    ask_contact_tool,
    greet_candidate_tool,
    # discard_candidate_tool,
    request_contact_tool,
]

# Resume tools
resume_tools: List[Callable[..., Any]] = [
    request_full_resume_tool,
    view_online_resume_tool,
    view_full_resume_tool,
    accept_resume_tool,
    check_resume_availability_tool,
]

# # Store tools
# store_tools: List[Callable[..., Any]] = [
#     get_candidate_from_store_tool,
#     find_candidate_by_resume_tool,
# ]

# # Thread management tools
# thread_tools: List[Callable[..., Any]] = [
#     init_chat_thread_tool,
#     get_thread_messages_tool,
# ]

# # Assistant management tools
# assistant_tools: List[Callable[..., Any]] = [
#     list_assistants_tool,
#     create_assistant_tool,
#     update_assistant_tool,
#     delete_assistant_tool,
# ]

# Create separate tool nodes
manager_tool_node = ToolNode(manager_tools)
recruiter_tool_node = ToolNode(chat_tools+resume_tools)

# All tools combined
all_tools = (
    manager_tools + 
    chat_tools + 
    resume_tools
)
all_tools_node = ToolNode(all_tools)