# from __future__ import annotations
import typing_extensions
import json
try:
    import regex as re
except ImportError:
    import re
try:
    from numba import njit
    _NUMBA_AVAILABLE = True
except ImportError:
    # Fallback decorator if numba is not available (e.g., Python 3.14+)
    def njit(func):
        return func
    _NUMBA_AVAILABLE = False
import time
import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional
from .config import get_openai_config
from .global_logger import logger
from openai import OpenAI
_openai_config = get_openai_config()
_openai_client = OpenAI(api_key=_openai_config["api_key"], base_url=_openai_config["base_url"])

#------------------------Thread management (deprecated)---------------------------------
@typing_extensions.deprecated("The Assistants API is deprecated in favor of the Responses API")
def get_thread_messages(thread_id: str) -> Dict[str, Any]:
    """List all messages in a thread, paginated.
    1.	Fetch the first page (since after is None initially).
    2.	Collect all messages from that batch.
    3.	If the API says has_more=True, set after to the last message ID of the batch and loop again.
    4.	Stop when has_more=False.
    """
    messages: List[Dict[str, str]] = []
    after: Optional[str] = None

    while True:
        response = _openai_client.beta.threads.messages.list(
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

    objects = get_objects_from_thread_messages(messages)

    return {
        "messages": messages,
        "analysis": objects.get("analysis"),
        "action": objects.get("action")
    }

@typing_extensions.deprecated("The Assistants API is deprecated in favor of the Responses API")
def get_objects_from_thread_messages(messages: list) -> Dict[str, Any]:
    """Get analysis from thread."""
    objects = {}
    for message in messages:
        if message["role"] == "assistant":
            # extract json from message["content"] using regex
            json_obj = extract_json_from_message(message["content"])
            if json_obj.get("skill"):
                objects["analysis"] = json_obj
            elif json_obj.get("action"):
                objects["action"] = json_obj
    return objects

@typing_extensions.deprecated("The Assistants API is deprecated in favor of the Responses API")
def extract_json_from_message(message: str) -> Dict[str, Any]:
    """Extract JSON from message."""
    from robust_json import loads
    return loads(message)

@njit
def extract_json_block(text: str) -> str | None:
    """Greedy search for first {...} block, with brace counting."""
    start = text.find("{")
    if start == -1:
        return None

    stack = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            stack += 1
        elif text[i] == "}":
            stack -= 1
            if stack == 0:
                return text[start:i + 1]

    # If we reached end without full closure, return what we have (partial)
    return text[start:]


@typing_extensions.deprecated("The Assistants API is deprecated in favor of the Responses API")
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

@typing_extensions.deprecated("The Assistants API is deprecated in favor of the Responses API")
def _sync_thread_with_history(
    thread_id: str,
    thread_messages: List[Dict[str, str]],
    history_messages: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Sync thread messages with chat history, adding missing messages."""
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
        _openai_client.beta.threads.messages.create(
            thread_id=thread_id,
            role=message["role"],
            content=message["content"],
        )
        thread_messages.append({"role": message["role"], "content": message["content"]})

    return thread_messages

@typing_extensions.deprecated("The Assistants API is deprecated in favor of the Responses API")
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
    if thread_messages:
        for message in thread_messages:
            if message.get("role") == role and message.get("content") == content:
                return False
        thread_messages.append({"role": role, "content": content})
    message = _openai_client.beta.threads.messages.create(thread_id=thread_id, role=role, content=content)
    return bool(message)
    
@typing_extensions.deprecated("The Assistants API is deprecated in favor of the Responses API")
def _wait_for_run_completion(thread_id: str, run_id: str, timeout: int = 60) -> bool:
    """Wait for AI assistant run to complete with timeout."""
    start = time.time()
    while time.time() - start < timeout:
        run_status = _openai_client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        status = getattr(run_status, "status", "")
        if status == "completed":
            return True
        if status in {"failed", "cancelled", "expired"}:
            logger.error("Run %s stopped with status %s", run_id, status)
            return False
        time.sleep(1)
    logger.error("Run %s timed out", run_id)
    _openai_client.beta.threads.runs.cancel(thread_id=thread_id, run_id=run_id)
    return False

@typing_extensions.deprecated("The Assistants API is deprecated in favor of the Responses API")
def _extract_latest_assistant_message(thread_id: str) -> str:
    """Extract the latest assistant message from thread."""
    response = _openai_client.beta.threads.messages.list(
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


# ------------------------Conversation API (replaces Threads API)-----------------------

def get_conversation_messages(conversation_id: str) -> Dict[str, Any]:
    """Get all messages from an OpenAI conversation using Conversations API.
    
    Replaces deprecated get_thread_messages() which used Threads API.
    
    Args:
        conversation_id: OpenAI conversation identifier
    
    Returns:
        dict: Response containing:
            - messages: List of conversation messages with id, role, and content
            - has_more: Boolean (always False for conversations API, no pagination)
            - analysis: Optional analysis dict if found in messages
            - action: Optional action dict if found in messages
    
    Raises:
        ValueError: If conversation not found or retrieval fails
    """
    try:
        conversation = _openai_client.conversations.retrieve(conversation_id)
        
        # Extract messages from conversation.items
        messages = []
        analysis = None
        action = None
        
        for item in getattr(conversation, 'items', []):
            # Handle message items
            if hasattr(item, 'type') and item.type == 'message':
                role = getattr(item, 'role', 'unknown')
                content = getattr(item, 'content', '')
                item_id = getattr(item, 'id', '')
                
                messages.append({
                    "id": item_id,
                    "role": role,
                    "content": content
                })
                
                # Extract analysis/action from assistant messages
                if role == "assistant" and content:
                    json_obj = extract_json_from_message(content)
                    if json_obj.get("skill") or json_obj.get("overall"):
                        analysis = json_obj
                    elif json_obj.get("action"):
                        action = json_obj
        
        return {
            "messages": messages,
            "has_more": False,  # Conversations API doesn't paginate
            "analysis": analysis,
            "action": action
        }
        
    except Exception as e:
        logger.error(f"Failed to get conversation messages: {e}")
        raise ValueError(f"Conversation not found or retrieval failed: {e}")


def get_analysis_from_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Get analysis result from conversation messages.
    
    Extracts the most recent analysis from conversation messages, typically generated
    by ANALYZE_ACTION purpose.
    
    Args:
        conversation_id: OpenAI conversation identifier
    
    Returns:
        Optional[dict]: Analysis dictionary if found in conversation, None otherwise
    """
    try:
        result = get_conversation_messages(conversation_id)
        # Return analysis if found, otherwise None
        return result.get("analysis")
    except Exception as e:
        logger.error(f"Failed to get analysis from conversation: {e}")
        return None


