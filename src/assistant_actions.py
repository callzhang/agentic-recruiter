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
OPENAI_DEFAULT_MODEL = 'gpt-4o-mini'
from pydantic_core.core_schema import str_schema
from tenacity import retry, stop_after_attempt, wait_exponential
from deprecated import deprecated
from .candidate_store import CandidateStore, candidate_store
from .config import settings
from .global_logger import logger

# Constants
MAX_CONTEXT_CHARS = 4000  # Maximum characters for context truncation
DEFAULT_PROMPTS = {
    "chat": "请根据上述沟通历史，为候选人撰写下一条回复，语气专业且真诚。",
    "greet": "请生成首次打招呼消息，突出公司与岗位亮点并认可候选人背景，请保持简短，不要超过50字。",
    "analyze": """请根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。
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
    "contact": "已接收候选人简历，请发出一条请求电话或者微信的消息。",
}

def load_openai_key() -> str | None:
    """Load OpenAI API key from settings."""
    return settings.OPENAI_API_KEY



class AssistantActions:
    """Handles AI-powered assistant actions with optional Zilliz storage."""

    
    def __init__(self, store: CandidateStore | None = None) -> None:
        self.store = store or candidate_store
        self.enabled = bool(self.store and getattr(self.store, "enabled", False))
        api_key = load_openai_key()
        if OpenAI and api_key:
            self.client = OpenAI(api_key=api_key)
        else:
            self.client = None
        
    
    # Assistants ----------------------------------------------------
    @lru_cache(maxsize=1)
    def get_assistants(self) -> List[Dict[str, Any]]:
        """Get all assistants."""
        api_key = load_openai_key()
        client = OpenAI(api_key=api_key)
        return client.beta.assistants.list()

    # Embeddings ----------------------------------------------------
    @lru_cache(maxsize=1000)
    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text."""
        if not self.enabled or not self.client:
            return None
        response = self.client.embeddings.create(
            model=settings.ZILLIZ_EMBEDDING_MODEL, 
            input=text[:4096],
            dimensions=settings.ZILLIZ_EMBEDDING_DIM,
        )
        return response.data[0].embedding

    # Candidate Management --------------------------------------
    # @lru_cache(maxsize=1000)
    def get_candidate_by_id(self, chat_id: str, fields: Optional[List[str]] = ["*"]) -> Optional[Dict[str, Any]]:
        """Get candidate by chat_id."""
        record = self.store.get_candidate_by_chat_id(chat_id, fields)
        if record:
            record.pop("resume_vector", None)
        return record

    
    def _upsert_candidate(self, **kwargs) -> bool:
        """Insert or update candidate information to the store.
        Used by: boss_service.py (upsert endpoint), src/scheduler.py (automation), generate_message (internal)
        """
        # Generate embedding for new candidates
        existing_candidate = self.get_candidate_by_id(kwargs.get("chat_id"))
        if not existing_candidate:  # create a new candidate
            resume_text = kwargs.get("resume_text")
            if resume_text:
                embedding = self.get_embedding(resume_text)
                kwargs["resume_vector"] = embedding
        
            # Truncate resume text to avoid token limits
            resume_text = kwargs.get("resume_text")
            if resume_text:
                kwargs["resume_text"] = resume_text[:8000]
                
            return self.store.insert_candidate(**kwargs)
        else:
            return self.store.update_candidate(**kwargs)






    # AI Generation with Threads API ------------------------------

    def get_thread_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """Get thread messages."""
        return self._list_thread_messages(thread_id)

    def init_chat(
        self,
        name: str,
        job_info: Dict[str, Any],
        resume_text: str,
        chat_history: List[Dict[str, Any]],
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
        thread = self.client.beta.threads.create(metadata=thread_metadata)
        thread_id = thread.id
        thread_messages: List[Dict[str, str]] = []
        
        # Add job description to thread
        job_info_text = json.dumps(job_info, ensure_ascii=False)
        job_description = f'你好，我是招聘顾问。以下是岗位描述，用于你的匹配程度，我们在后面的对话中都需要参考:\n{job_info_text}'
        self._append_message_to_thread(thread_id, thread_messages, "assistant", job_description)
        logger.info("Added job description to thread %s", thread_id)
        
        # Sync thread with chat history if provided
        history_messages = self._normalise_history(chat_history)
        thread_messages = self._sync_thread_with_history(thread_id, thread_messages, history_messages)
        logger.info("Synced chat history to thread %s", thread_id)
        if len(chat_history) > 0:
            last_message = chat_history[-1].get("message")
        else:
            last_message = ""
        
        # Add candidate resume to thread
        candidate_resume_text = f'请查看我的简历:\n{resume_text[:2000]}'
        self._append_message_to_thread(thread_id, thread_messages, "user", candidate_resume_text)
        logger.info("Added candidate resume to thread %s", thread_id)
        
        # Create/update Zilliz record
        candidate_id = None
        # Generate embedding for semantic search
        embedding = self.get_embedding(resume_text)
        
        # create candidate record
        success = self._upsert_candidate(
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
            "candidate_id": candidate_id,
            "success": success
        }
        


    ## ------------Main Message Generation----------------------------------
    
    def generate_message(
        self,
        chat_id: str,
        assistant_id: str,
        purpose: str,
        user_message: str,
        full_resume: Optional[str] = None,
        format_json: Optional[bool] = False,
    ) -> Dict[str, Any]:
        """
        Generate message using chat_id - thread_id lookup is handled internally.
        
        This method generates the next message in an existing conversation thread.
        It adds any new context (user message, full resume, etc.) to the thread
        and generates an appropriate response based on the purpose.
        
        Args:
            chat_id: Chat ID to look up thread (required)
            assistant_id: OpenAI assistant ID (required)
            purpose: Message purpose - "analyze", "greet", "chat", "followup"
            user_message: Latest message from candidate (required)
            full_resume: Complete resume text to add to thread context (optional)
            format_json: Whether to request JSON response format
            
        Returns:
            Dict with:
                - message: str (generated message)
                - analysis: dict (if purpose="analyze")
                - success: bool
                - thread_id: str
        """
        assert chat_id, "chat_id is required"
        assert assistant_id, "assistant_id is required"
        assert purpose, "purpose is required"
        
        # Get thread_id from Zilliz store using chat_id
        thread_id = self.get_thread_id(chat_id=chat_id)
        if not thread_id:
            return {
                "message": "抱歉，未找到对应的对话线程，请先初始化对话。",
                "analysis": None,
                "success": False,
                "thread_id": None
            }
        
        # Add full resume to thread if provided
        if full_resume:
            full_resume_text = f'完整简历信息:\n{full_resume[:2000]}'
            self._append_message_to_thread(thread_id, [], "user", full_resume_text)
            logger.info("Added full resume to thread %s", thread_id)
        
        # Add user message to thread
        self._append_message_to_thread(thread_id, [], "user", user_message)
        logger.info("Added user message to thread %s", thread_id)
        
        # Get instruction for purpose
        instruction = DEFAULT_PROMPTS.get(purpose)
        assert instruction, f"prompt for {purpose} is not found"
        if purpose == "analyze":
            format_json = True
        
        # Create a new run
        run = self.client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
            additional_instructions=instruction,
            response_format={"type": "json_object"} if format_json else None,
        )
        
        # Wait for completion
        if not self._wait_for_run_completion(thread_id, run.id):
            logger.error("Run failed or timed out for thread %s", thread_id)
            return {
                "message": "抱歉，消息生成失败，请稍后重试。",
                "analysis": None,
                "success": False,
                "thread_id": thread_id
            }
        
        # Extract generated message
        generated_message = self._extract_latest_assistant_message(thread_id).strip()
        
        # Parse analysis if purpose is "analyze"
        analysis = None
        if purpose == "analyze" and format_json:
            try:
                analysis = json.loads(generated_message)
                logger.info("Parsed analysis from thread %s", thread_id)
                # Analysis is kept in the thread - no need to store in Zilliz
                    
            except json.JSONDecodeError as e:
                logger.error("Failed to parse analysis JSON: %s", str(e))
                analysis = {"error": "Failed to parse analysis", "raw_message": generated_message}
        
        return {
            "message": generated_message,
            "analysis": analysis,
            "success": True,
            "thread_id": thread_id
        }


    def get_thread_id(self, chat_id: Optional[str] = None, candidate_resume: Optional[str] = None) -> Optional[str]:
        """
        Get thread_id from chat_id or candidate_resume.
        
        Args:
            chat_id: Chat ID to look up
            candidate_resume: Resume text for semantic search
            
        Returns:
            thread_id if found, None otherwise
        """
        assert chat_id or candidate_resume, "chat_id or candidate_resume is required"
            
        # Try chat_id lookup first
        if chat_id:
            record = self.store.get_candidate_by_id(chat_id)
            if record:
                # metadata = record.get("metadata") or {}
                thread_id = record.get("thread_id")
                if thread_id:
                    return thread_id
        
        # Try semantic search by resume
        if candidate_resume:
            embedding = self.get_embedding(candidate_resume)
            if embedding:
                match = self.store.search_candidates(embedding, limit=1)
                if match and match.get("entity"):
                    entity = match["entity"]
                    thread_id = entity.get("thread_id")
                    if thread_id:
                        return thread_id
        
        return None


    def _list_thread_messages(self, thread_id: str) -> List[Dict[str, str]]:
        """List all messages in a thread, paginated.
        1.	Fetch the first page (since after is None initially).
        2.	Collect all messages from that batch.
        3.	If the API says has_more=True, set after to the last message ID of the batch and loop again.
        4.	Stop when has_more=False.
        """
        messages: List[Dict[str, str]] = []
        after: Optional[str] = None

        while True:
            response = self.client.beta.threads.messages.list(
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

    def _normalise_history(self, chat_history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
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
        self,
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
            self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role=message["role"],
                content=message["content"],
            )
            thread_messages.append({"role": message["role"], "content": message["content"]})

        return thread_messages

    def _append_message_to_thread(
        self,
        thread_id: str,
        thread_messages: List[Dict[str, str]],
        role: str,
        content: str,
    ) -> bool:
        """Add message to thread if not already present.
        return True if the message is added, False if the message is already present.
        return: bool
        """
        for message in thread_messages:
            if message.get("role") == role and message.get("content") == content:
                return False
        self.client.beta.threads.messages.create(thread_id=thread_id, role=role, content=content)
        thread_messages.append({"role": role, "content": content})
        return True


    def _format_analysis_message(self, analysis: Dict[str, Any]) -> str:
        """Format candidate analysis into readable message."""
        if not isinstance(analysis, dict):
            return str(analysis)
        key_map = {
            "skill": "技能匹配度",
            "startup_fit": "创业契合度",
            "willingness": "加入意愿",
            "overall": "综合评分",
        }
        lines: List[str] = []
        for key in key_map.keys():
            value = analysis.get(key)
            lines.append(f"{key_map[key]}: {value}")
        summary = analysis.get("summary")
        if summary:
            lines.append(f"简历分析总结: {summary}")
        if not lines:
            return ""
        return "你好，以下是对你简历的评估评估:\n" + "\n".join(lines)


    def _wait_for_run_completion(self, thread_id: str, run_id: str, timeout: int = 60) -> bool:
        """Wait for AI assistant run to complete with timeout."""
        start = time.time()
        while time.time() - start < timeout:
            run_status = self.client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
            status = getattr(run_status, "status", "")
            if status == "completed":
                return True
            if status in {"failed", "cancelled", "expired"}:
                logger.error("Run %s stopped with status %s", run_id, status)
                return False
            time.sleep(1)
        logger.error("Run %s timed out", run_id)
        return False

    def _extract_latest_assistant_message(self, thread_id: str) -> str:
        """Extract the latest assistant message from thread."""
        response = self.client.beta.threads.messages.list(
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





# Global instance
assistant_actions = AssistantActions()

__all__ = ["assistant_actions", "AssistantActions", "get_assistants"]
