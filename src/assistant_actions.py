"""Assistant actions for recruitment automation with AI and storage."""
from __future__ import annotations

import logging
import json
from functools import lru_cache
from typing import Any, Dict, List, Optional
from openai import OpenAI
from .candidate_store import upsert_candidate
from .config import settings
from .global_logger import logger
from .assistant_utils import _openai_client
from pydantic import BaseModel, Field

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
    "CHAT_ACTION": """针对候选人简历，根据岗位信息里面的drill_down_questions，提出问题，让候选人回答经验细节，或者澄清模棱两可的地方。重点在于挖掘简历细节，判断候选人是否符合岗位要求。
如果候选人有问题，也同时回答问题。
请直接生成一条可以发送给候选人的自然语言消息，不要超过100字。不要发模板或者嵌入占位符，不要使用任何格式化、引号、JSON或括号。
""",
    "ANALYZE_ACTION": f"""请根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。
        重点关注keyword里面的正负向关键词要进行加分和减分。
        仔细查看候选人的项目经历，检查是否有言过其词的情况。
        最后，还要查看候选人的过往工作经历，判断是否符合岗位要求。
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
    overall: int = Field(description="综合评分，满分10分")
    summary: str = Field(description="分析总结，不要超过200字")
    followup_tips: str = Field(description="后续招聘顾问跟进的沟通策略，不要超过200字")


# Assistants ----------------------------------------------------

@lru_cache(maxsize=1)
def get_assistants() -> List[Dict[str, Any]]:
    """Get all assistants."""
    return _openai_client.beta.assistants.list()


# AI Generation with Responses API ------------------------------
def init_chat(
    mode: str,
    name: str,
    job_info: Dict[str, Any],
    online_resume_text: str,
    chat_history: List[Dict[str, Any]]=[],
    chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Initialize conversation and Zilliz record.
    
    Creates OpenAI conversation with job description and resume, then creates/updates Zilliz record
    with conversation_id for future message generation.
    
    Note: This function is called ONLY when we have the resume_text and BEFORE analyzing it.
    
    Args:
        name: str (candidate name)
        job_info: Dict with job position, description, requirements
        resume_text: str (candidate resume text - REQUIRED)
        chat_id: Optional[str] (for chat workflows, None for recommend workflow)
        chat_history: Optional existing chat history to sync
        
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
    system_prompt = {
        'type': 'message', 
        'role': 'developer', 
        'content': f'你是招聘顾问。以下是岗位描述，用于分析候选人的匹配程度:\n{job_info_text}'
    }
    
    # Add candidate resume to thread
    candidate_resume_text = f'请查看我的简历:\n{online_resume_text}'
    candidate_message = {'type': 'message', 'role': 'user', 'content': candidate_resume_text}
    full_history = [system_prompt, candidate_message]
    role_map = {'candidate': 'user', 'recruiter': 'assistant', 'system': 'developer'}
    for msg in chat_history:
        role = role_map.get(msg.get('type'), msg.get('type'))
        full_history.append({'type': 'message', 'role': role, 'content': msg.get('message')})
    
    # Create openai conversation
    conversation = _openai_client.conversations.create(
        metadata=conversation_metadata, 
        items=full_history
    )

    # create candidate record
    success = upsert_candidate(
        chat_id=chat_id,
        name=name,
        job_applied=job_info["position"],
        resume_text=online_resume_text,
        stage=None,  # Not analyzed yet
        conversation_id=conversation.id,
        metadata={'history': chat_history},
    )
    if not success:
        raise ValueError("Failed to create candidate record")
    
    return conversation.id

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
    if json_schema:
        if purpose == "ANALYZE_ACTION":
            response = _openai_client.responses.parse(
                conversation=conversation_id,
                instructions=instruction,
                input= input_message,
                text_format=json_schema,
                model="gpt-5-mini",
            )
            result = response.output_parsed.model_dump() 
            upsert_candidate(conversation_id=conversation_id, analysis=result)
        else:
            raise NotImplementedError(f"Unsupported purpose: {purpose}")
        return result
    else:
        response = _openai_client.responses.create(
            conversation=conversation_id,
            instructions=instruction,
            input=input_message,
            model="gpt-5-mini",
        )
        return response.output_text
    


__all__ = [
    "get_assistants",
    "init_chat",
    "generate_message",
]
