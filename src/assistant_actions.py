"""Assistant actions for recruitment automation with AI and storage."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from openai import OpenAI
OPENAI_DEFAULT_MODEL = 'gpt-4o-mini'
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



    # AI Generation with Threads API ------------------------------
    def generate_message(
        self,
        *,
        chat_id: str,
        prompt: str,
        chat_history: List[Dict[str, Any]],
        assistant_id: Optional[str] = None,
        job_info: Optional[Dict[str, Any]] = None,
        candidate_summary: Optional[str] = None,
        candidate_resume: Optional[str] = None,
        analysis: Optional[Dict[str, Any]] = None,
        thread_id: Optional[str] = None,
    ) -> tuple[str, str]:
        """Generate a message using the Threads API with history synchronisation.
        
        Used by: generate_followup_message (internal)
        """

        record = self.get_candidate_record(chat_id)
        existing_metadata: Dict[str, Any] = dict(record.get("metadata") or {}) if record else {}
        thread_id = thread_id or existing_metadata.get("thread_id")

        if not thread_id:
            thread_metadata = {"chat_id": chat_id}
            if assistant_id:
                thread_metadata["assistant_id"] = assistant_id
            thread = self.client.beta.threads.create(metadata=thread_metadata)
            thread_id = thread.id

        thread_messages = self._list_thread_messages(thread_id)
        history_messages = self._normalise_history(chat_history)
        if history_messages:
            thread_messages = self._sync_thread_with_history(thread_id, thread_messages, history_messages)

        if analysis:
            analysis_text = self._format_analysis_message(analysis)
            thread_messages = self._append_if_missing(thread_id, thread_messages, "assistant", analysis_text)

        if candidate_summary:
            thread_messages = self._append_if_missing(thread_id, thread_messages, "user", candidate_summary)

        instructions = self._build_run_instructions(
            prompt=prompt,
            job_info=job_info,
            analysis=analysis,
            candidate_summary=candidate_summary,
            candidate_resume=candidate_resume,
        )

        run = self.client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
            instructions=instructions,
        )

        if not self._wait_for_run_completion(thread_id, run.id):
            logger.error("Run failed or timed out for chat %s", chat_id)
            return "抱歉，消息生成失败，请稍后重试。", thread_id

        generated_message = self._extract_latest_assistant_message(thread_id).strip()
        if not generated_message:
            generated_message = "消息生成成功，但内容为空。"

        if self.store and getattr(self.store, "enabled", False):
            metadata_to_store = dict(existing_metadata)
            metadata_to_store["thread_id"] = thread_id
            if assistant_id:
                metadata_to_store["assistant_id"] = assistant_id
            if record:
                self.store.update_candidate_metadata(chat_id, metadata_to_store)
            else:
                self.upsert_candidate(candidate_id=chat_id, metadata=metadata_to_store)

        return generated_message, thread_id


    def _list_thread_messages(self, thread_id: str) -> List[Dict[str, str]]:
        """List all messages in a thread, paginated."""
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
                break
            if response.data:
                after = response.data[-1].id
            else:
                break

        return messages

    def _normalise_history(self, chat_history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Convert chat history to thread message format."""
        role_map = {"candidate": "user", "recruiter": "assistant"}
        normalised: List[Dict[str, str]] = []
        for entry in chat_history or []:
            role = role_map.get(entry.get("type"))
            message = (entry.get("message") or "").strip()
            if not role or not message:
                continue
            normalised.append({"role": role, "content": message})
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
            if msg.get("role") in {"assistant", "user"}
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
        content: Optional[str],
    ) -> List[Dict[str, str]]:
        """Add message to thread if not already present."""
        text = (content or "").strip()
        if not text:
            return thread_messages
        for message in thread_messages:
            if message.get("role") == role and message.get("content") == text:
                return thread_messages
        self.client.beta.threads.messages.create(thread_id=thread_id, role=role, content=text)
        thread_messages.append({"role": role, "content": text})
        return thread_messages

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

    def _build_run_instructions(
        self,
        *,
        prompt: str,
        job_info: Optional[Dict[str, Any]],
        analysis: Optional[Dict[str, Any]],
        candidate_summary: Optional[str],
        candidate_resume: Optional[str],
    ) -> str:
        """Build comprehensive instructions for AI assistant run."""
        parts = [
            "你是公司的人才招聘负责人，请以专业真诚的语气，用中文撰写下一条发送给候选人的消息。",
            f"【当前任务】\n{(prompt or '请为候选人撰写跟进消息。').strip()}",
        ]

        if job_info:
            parts.append(f"【岗位信息】\n{self._format_job_info(job_info)}")

        if analysis:
            analysis_text = self._format_analysis_message(analysis)
            if analysis_text:
                parts.append(analysis_text)

        if candidate_summary:
            parts.append(f"【候选人概要】\n{candidate_summary.strip()}")

        resume_segment = self._truncate_text(candidate_resume)
        if resume_segment:
            parts.append(f"【候选人简历片段】\n{resume_segment}")

        return "\n\n".join(part for part in parts if part)

    def _format_job_info(self, job_info: Dict[str, Any]) -> str:
        """Format job information into readable text."""
        if isinstance(job_info, dict):
            lines = []
            for key, value in job_info.items():
                if not value:
                    continue
                lines.append(f"{key}: {value}")
            return "\n".join(lines)
        return str(job_info)

    def _truncate_text(self, text: Optional[str]) -> str:
        """Truncate text to maximum context length."""
        content = (text or "").strip()
        if not content:
            return ""
        if len(content) <= MAX_CONTEXT_CHARS:
            return content
        return content[:MAX_CONTEXT_CHARS] + "..."

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


    def generate_followup_message(
        self,
        chat_id: str,
        prompt: str,
        *,
        chat_history: List[Dict[str, Any]],
        job_info: Optional[Dict[str, Any]] = None,
        assistant_id: Optional[str] = None,
        candidate_summary: Optional[str] = None,
        candidate_resume: Optional[str] = None,
        analysis: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Compatibility wrapper around generate_message for follow-up flows.
        
        Used by: boss_service.py (followup message endpoint)
        """
        message, _ = self.generate_message(
            chat_id=chat_id,
            prompt=prompt or "请生成一条跟进消息。",
            chat_history=chat_history,
            assistant_id=assistant_id,
            job_info=job_info,
            candidate_summary=candidate_summary,
            candidate_resume=candidate_resume,
            analysis=analysis,
        )
        return message

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def generate_greeting_message(
        self,
        candidate_name: str = None,
        candidate_title: str = None,
        candidate_summary: str = None,
        candidate_resume: str = None,
        job_info: dict = None
    ) -> str:
        """Generate AI-powered greeting message for a specific candidate.
        
        Used by: boss_service.py (greeting endpoint), src/scheduler.py (automation)
        
        Args:
            candidate_name: Name of the candidate (optional)
            candidate_title: Current job title of the candidate (optional)
            candidate_summary: Brief summary of candidate's background (optional)
            candidate_resume: Full resume text of the candidate (optional)
            job_info: The job info we're recruiting for (optional)
            
        Returns:
            str: Generated greeting message
        """
        if not self.client:
            return ""
        
        summary_clean = (candidate_summary or "").replace("\n", "")
        prompt = f"""你是公司的人才招聘负责人，请根据候选人信息和招聘信息，生成一条专业的打招呼消息。
1. 专业且真诚的打招呼消息
2. 突出公司与岗位的亮点
3. 体现对候选人背景的认可
4. 长度控制在50-100字
5. 使用中文，语气友好专业
6. 直接输出可以直接发送给候选人的消息，不要包含其他说明文字
7. 不要包含placeholder、占位符，例如“[公司名]“
------
【候选人信息】
姓名：{candidate_name}
当前职位：{candidate_title}
背景简介：{summary_clean}
完整简历：
{candidate_resume}
------
【招聘信息】
{job_info}
"""

        response = self.client.chat.completions.create(
            model=OPENAI_DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300
        )
        
        message = response.choices[0].message.content if response.choices else ""
        return message.strip() 

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
        )
        text = response.choices[0].message.content if response.choices else ""
        data = self._parse_json_from_text(text)
        if not data:
            logger.error("无法解析评分结果")
        return data

    def _parse_json_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from text content, handling mixed content."""
        import json
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            return json.loads(text[start:end + 1])
        return None

    # Candidate Management --------------------------------------
    def get_candidate_record(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve candidate record by chat identifier from the store.
        
        Used by: generate_message (internal)
        """
        if not candidate_id or not self.enabled or not self.store:
            return None
        return self.store.get_candidate_by_id(candidate_id)

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
            candidate_id=candidate_id,
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
