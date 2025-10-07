"""Assistant actions for recruitment automation with AI and storage."""
from __future__ import annotations

import logging
import json
import time
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from openai import OpenAI
OPENAI_DEFAULT_MODEL = 'gpt-4o-mini'
from pydantic_core.core_schema import str_schema
from tenacity import retry, stop_after_attempt, wait_exponential
from .candidate_store import CandidateStore, candidate_store
from .scheduler import BRDWorkScheduler
from .config import settings

logger = logging.getLogger(__name__)

# Constants
MAX_CONTEXT_CHARS = 4000  # Maximum characters for context truncation

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
        
        # Scheduler management
        import threading
        self.scheduler: BRDWorkScheduler | None = None
        self.scheduler_lock = threading.Lock()
        self.scheduler_config: dict[str, Any] = {}
    
        
    @lru_cache(maxsize=1)
    def get_assistants(self) -> List[Dict[str, Any]]:
        """Get all assistants."""
        api_key = load_openai_key()
        client = OpenAI(api_key=api_key)
        return client.beta.assistants.list()

    # Embeddings ----------------------------------------------------
    @lru_cache(maxsize=1000)
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _embed(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text."""
        if not self.enabled or not self.client:
            return None
        response = self.client.embeddings.create(
            model="text-embedding-3-small", 
            input=text
        )
        return response.data[0].embedding

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Public method to get embeddings.
        
        Used by: upsert_candidate, record_qa
        """
        return self._embed(text)


    def get_cached_resume(self, candidate_id: str) -> Optional[str]:
        """Return cached resume text for a candidate if it exists in the vector store."""
        if not candidate_id or not self.enabled or not self.store:
            return None
        record = self.store.get_candidate_by_id(candidate_id)
        if not record:
            return None
        metadata = record.get("metadata") or {}
        return record.get("resume_text") or metadata.get("resume_text")



    # AI Generation with Threads API ------------------------------

    def generate_message(
        self,
        prompt: str,
        chat_history: List[dict],
        job_info: dict,
        *,
        assistant_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        candidate_resume: Optional[str] = None,
        candidate_summary: Optional[str] = None,
        analysis: Optional[dict] = None,
        thread_id: Optional[str] = None,
        purpose: str = "chat",
        format_json: bool = False,
    ) -> tuple[str, str]:
        """
        Generate a follow-up message for a candidate using the OpenAI Threads API, with full chat history synchronization.

        This method ensures that the assistant's context is up-to-date by:
        - Retrieving or creating a thread associated with the candidate (using chat_id, thread_id, or candidate_resume).
            - if thread_id is provided, use it
            - elif chat_id is provided, try to find the thread_id in the candidate record
            - elif candidate_resume is provided, try to find the thread_id by semantic search from candidate resume
            - elif no thread_id is found, create a new thread
        - Synchronizing the thread with the provided chat history, appending any missing messages.
        - Optionally appending candidate analysis (as an assistant message) and candidate summary (as a user message) if not already present.
        - Building comprehensive run instructions that include the prompt, job information, analysis, summary, and resume.
        - Creating a new assistant run and waiting for its completion.
        - Extracting and returning the latest assistant-generated message and the thread_id.

        Args:
            prompt (str): The message prompt or task for the assistant.
            chat_history (List[dict]): The conversation history between recruiter and candidate.
            assistant_id (str): The OpenAI assistant ID to use for the run.
            job_info (dict): Information about the job position.
            chat_id (str, optional): Unique identifier for the candidate chat.
            candidate_resume (str, optional): The candidate's resume text.
            candidate_summary (str, optional): A summary of the candidate's background.
            analysis (dict, optional): Quantitative and qualitative analysis of the candidate.
            thread_id (str, optional): Existing thread ID to use.

        Returns:
            tuple[str, str]: The generated assistant message and the thread_id used.
        """
        assert chat_id or thread_id or candidate_resume, "chat_id or thread_id or candidate_resume is required to identify the thread"

        record: Optional[Dict[str, Any]] = None
        existing_metadata: Dict[str, Any] = {}
        if chat_id and self.enabled:
            record = self.store.get_candidate_by_id(chat_id)
            if record:
                existing_metadata = dict(record.get("metadata") or {})
                if not candidate_resume:
                    candidate_resume = record.get("resume_text") or existing_metadata.get("resume_text")
        if not candidate_resume and chat_id:
            cached_resume = self.get_cached_resume(chat_id)
            if cached_resume:
                candidate_resume = cached_resume

        assistant_id = self._resolve_assistant_id(
            assistant_id=assistant_id,
            job_info=job_info,
            metadata=existing_metadata,
        )

        if chat_id and not thread_id:
            thread_id = existing_metadata.get("thread_id")

        if not thread_id and candidate_resume and self.enabled:
            embedding = self.get_embedding(candidate_resume)
            if embedding:
                match = self.store.search_candidates(embedding)
                if match:
                    entity = match.get("entity", {})
                    thread_id = (entity.get("metadata") or {}).get("thread_id")

        if not thread_id:
            thread_metadata = {"chat_id": chat_id or f"anonymous-{uuid4().hex[:8]}", "assistant_id": assistant_id}
            thread = self.client.beta.threads.create(metadata=thread_metadata)
            thread_id = thread.id
            thread_messages: List[Dict[str, str]] = []
        else:
            thread_messages = self._list_thread_messages(thread_id)
        # sync thread with chat history
        if chat_history:
            history_messages = self._normalise_history(chat_history)
            if thread_messages:
                thread_messages = self._sync_thread_with_history(thread_id, thread_messages, history_messages)
        if analysis:
            analysis_text = self._format_analysis_message(analysis)
            if analysis_text:
                self._append_if_missing(thread_id, thread_messages, "assistant", analysis_text)

        if candidate_summary:
            self._append_if_missing(thread_id, thread_messages, "assistant", candidate_summary)

        instructions = self._build_run_instructions(
            prompt=prompt,
            job_info=job_info,
            analysis=analysis,
            candidate_summary=candidate_summary,
            candidate_resume=candidate_resume,
            purpose=purpose,
        )

        run = self.client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
            additional_instructions=instructions,
            response_format={"type": "json_object"} if format_json else None,
        )

        if not self._wait_for_run_completion(thread_id, run.id):
            logger.error("Run failed or timed out for chat %s", chat_id)
            return "抱歉，消息生成失败，请稍后重试。", thread_id

        generated_message = self._extract_latest_assistant_message(thread_id).strip()
        if not generated_message:
            generated_message = "消息生成成功，但内容为空。"


        metadata_to_store = dict(existing_metadata)
        metadata_to_store["thread_id"] = thread_id
        if assistant_id:
            metadata_to_store["assistant_id"] = assistant_id
        if record:
            self.store.update_candidate_metadata(chat_id, metadata_to_store)
        else:
            self.upsert_candidate(candidate_id=chat_id or thread_id, metadata=metadata_to_store)

        return generated_message, thread_id


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
                (you haven’t yet reached the end of the thread’s history).
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
                logger.warning(f"不支持的消息内容: {entry}")
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

    def _append_if_missing(
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
        for key in ("skill", "startup_fit", "willingness", "overall"):
            value = analysis.get(key)
            if value is not None:
                lines.append(f"{key_map[key]}: {value}")
        summary = analysis.get("summary")
        if summary:
            lines.append(f"总结: {summary}")
        if not lines:
            return ""
        return "内部评估:\n" + "\n".join(lines)

    def _resolve_assistant_id(
        self,
        *,
        assistant_id: Optional[str],
        job_info: Optional[Dict[str, Any]],
        metadata: Dict[str, Any],
    ) -> str:
        """Determine which assistant ID to use for thread runs."""
        candidates = [
            assistant_id,
            metadata.get("assistant_id"),
            (job_info or {}).get("assistant_id"),
        ]
        for value in candidates:
            if value:
                return value
        raise ValueError("assistant_id is required for message generation. Provide it explicitly or configure it in job metadata.")

    def _build_run_instructions(
        self,
        *,
        prompt: str,
        job_info: Optional[Dict[str, Any]],
        analysis: Optional[Dict[str, Any]],
        candidate_summary: Optional[str],
        candidate_resume: Optional[str],
        purpose: str,
    ) -> str:
        """Build comprehensive instructions for AI assistant run."""
        default_prompts = {
            "chat": "请为候选人撰写下一条回复，语气专业且真诚。",
            "greet": "请生成首次打招呼消息，突出公司与岗位亮点并认可候选人背景。",
            "analyze": "请总结候选人优势与风险，并给出是否继续推进的建议。",
            "add_resume": "请确认已接收候选人简历，并说明下一步动作。",
        }

        effective_prompt = (prompt or "").strip() or default_prompts.get(purpose, default_prompts["chat"])
        parts = [
            "你是公司的人才招聘负责人，请以专业真诚的语气，用中文撰写下一条发送给候选人的消息。",
            f"【当前任务】\n{effective_prompt}",
        ]

        if job_info:
            parts.append(f"【岗位信息】\n{json.dumps(job_info, ensure_ascii=False, indent=2)}")

        if analysis:
            formatted = self._format_analysis_message(analysis)
            if formatted:
                parts.append(formatted)

        if candidate_summary:
            parts.append(f"【候选人概要】\n{candidate_summary.strip()}")

        if candidate_resume:
            snippet = candidate_resume[:1200]
            parts.append(f"【候选人简历片段】\n{snippet}")

        return "\n\n".join(part for part in parts if part)


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
                for block in getattr(message, "content", [])
                if getattr(block, "type", None) == "text"
            ]
            content = "\n".join(text_blocks).strip()
            if content:
                return content
        return ""



    def analyze_candidate(
        self, 
        job_info: dict,   
        candidate_resume: str,
        chat_history: dict,
        candidate_summary: str = None,
    ) -> Optional[Dict[str, Any]]:
        """Analyze candidate and return scoring results.
        
        Used by: boss_service.py (analysis endpoint), src/scheduler.py (automation), pages/6_推荐牛人.py (UI)
        """
        if not self.client:
            raise SystemError("OpenAI client not available for candidate analysis")
        
        prompt = f"""请基于以下信息对候选人做出量化评估。
【岗位描述】
{job_info}

【候选人材料】
{candidate_summary}
{candidate_resume}

【近期对话】
{chat_history}

请给出 1-10 的四个评分：技能匹配度、创业契合度、加入意愿、综合评分，并提供简要分析。输出严格使用 JSON 格式：
{{
  "skill": <int>,
  "startup_fit": <int>,
  "willingness": <int>,
  "overall": <int>,
  "summary": "..."
}}
"""
        response = self.client.chat.completions.create(
            model=OPENAI_DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}  # Ensures the model outputs valid JSON
        )
        data = json.loads(response.choices[0].message.content)
        if not data:
            logger.error("无法解析评分结果")
        return data

    # Candidate Management --------------------------------------

    def upsert_candidate(
        self,
        candidate_id: str,
        name: Optional[str] = None,
        job_applied: Optional[str] = None,
        last_message: Optional[str] = None,
        resume_text: Optional[str] = None,
        scores: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = {},
    ) -> bool:
        """Upsert candidate information to the store.
        
        Used by: boss_service.py (upsert endpoint), src/scheduler.py (automation), generate_message (internal)
        """
        if not self.enabled or not self.store:
            logger.warning("Store not available, cannot upsert candidate")
            return False

        embedding = self.get_embedding(resume_text)

        return self.store.upsert_candidate(
            chat_id=candidate_id,
            name=name,
            job_applied=job_applied,
            last_message=last_message,
            resume_text=resume_text,
            scores=scores,
            metadata=metadata,
            resume_vector=embedding,
        )

# QA Persistence ---------------------------------------------------
    def retrieve_relevant_answers(
        self, 
        query: str, 
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant QA entries for a query.
        
        Used by: boss_service.py (QA search endpoint)
        """
        if not self.enabled:
            return []
        vector = self._embed(query)
        if not vector:
            return []
        return self.store.search(vector, top_k, similarity_threshold)

    def record_qa(
        self, 
        *,
        qa_id: str | None = None, 
        question: str, 
        answer: str,
        keywords: Optional[List[str]] = None
    ) -> str | None:
        """Record a QA entry in the store.
        
        Used by: boss_service.py (QA endpoint), pages/7_问答库.py (UI)
        """
        if not self.enabled:
            return None
        text = f"问题: {question}\n回答: {answer}"
        vector = self._embed(text)
        if not vector:
            vector = [0.0] * 1536  # Default dimension
        qa_id = (qa_id or self.generate_id()).strip()
        entry = {
            "qa_id": qa_id,
            "question": question,
            "answer": answer,
            "qa_vector": vector,
            "keywords": keywords or [],
        }
        self.store.insert([entry])
        return qa_id

    def list_entries(self, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        """List QA entries from store.
        
        Used by: boss_service.py (list endpoint), pages/7_问答库.py (UI)
        """
        if not self.enabled:
            return []
        # TODO: - would query Zilliz in full version
        return []

    def delete_entry(self, resume_id: str) -> bool:
        """Delete a QA entry from store.
        
        Used by: boss_service.py (delete endpoint), pages/7_问答库.py (UI)
        """
        if not self.enabled:
            return False
        # TODO - would delete from Zilliz in full version
        return False

    @staticmethod
    def generate_id() -> str:
        """Generate a unique ID.
        
        Used by: boss_service.py (ID generation endpoint), pages/7_问答库.py (UI), record_qa (internal)
        """
        return uuid4().hex

    # Scheduler Management -----------------------------------------
    def get_scheduler_status(self) -> Dict[str, Any]:
        """Get scheduler status and configuration.
        
        Used by: boss_service.py (status endpoints)
        """
        with self.scheduler_lock:
            status = {
                'running': self.scheduler is not None,
                'config': dict(self.scheduler_config) if self.scheduler is not None else {}
            }
            if self.scheduler is not None and hasattr(self.scheduler, 'get_status'):
                status.update(self.scheduler.get_status())
            return status

    def start_scheduler(self, payload: Dict[str, Any]) -> tuple[bool, str]:
        """Start the automation scheduler.
        
        Used by: boss_service.py (start endpoint)
        """
        with self.scheduler_lock:
            if self.scheduler:
                return False, '调度器已运行'
            
            """Build scheduler options from payload."""

            options: Dict[str, Any] = {
                'job': payload.get('job'),
                'recommend_limit': payload.get('check_recommend_candidates_limit') or 20,
                'enable_recommend': bool(payload.get('check_recommend_candidates', True)),
                'overall_threshold': payload.get('match_threshold') or 9.0,
                'enable_chat_processing': bool(payload.get('check_new_chats')),
                'enable_followup': bool(payload.get('check_followups')),
                'assistant': self,
                'base_url': settings.BOSS_SERVICE_BASE_URL,  # Pass API base URL instead of page
            }

            scheduler = BRDWorkScheduler(**options)
            scheduler.start()
            self.scheduler = scheduler
            options.pop('assistant')
            self.scheduler_config = options
            return True, '调度器已启动'

    def stop_scheduler(self) -> tuple[bool, str]:
        """Stop the automation scheduler.
        
        Used by: boss_service.py (stop endpoint)
        """
        with self.scheduler_lock:
            if not self.scheduler:
                return False, '调度器未运行'
            scheduler = self.scheduler
            self.scheduler = None
            self.scheduler_config = {}
        
        # Stop scheduler directly - it has its own timeout handling
        scheduler.stop()
        return True, '已停止调度器'




# Global instance
assistant_actions = AssistantActions()

__all__ = ["assistant_actions", "AssistantActions", "get_assistants"]
