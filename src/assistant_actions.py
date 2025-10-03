"""Assistant actions for recruitment automation with AI and storage."""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional
from uuid import uuid4

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

from tenacity import retry, stop_after_attempt, wait_exponential

from .candidate_store import CandidateStore, candidate_store

logger = logging.getLogger(__name__)

DEFAULT_GREETING = "您好，我们是一家AI科技公司，对您的背景十分感兴趣，希望能进一步沟通。"
OPENAI_DEFAULT_MODEL = os.getenv("BOSSZP_GPT_MODEL", "gpt-4o-mini")


class AssistantActions:
    """Handles AI-powered assistant actions with optional Zilliz storage."""
    
    def __init__(self, store: CandidateStore | None = None) -> None:
        self.store = store or candidate_store
        self.enabled = bool(self.store and self.store.enabled)
        api_key = self._load_openai_key()
        if OpenAI and api_key:
            self.client = OpenAI(api_key=api_key)
        else:
            self.client = None
    
    def _load_openai_key(self) -> Optional[str]:
        """Load OpenAI API key from environment or config file."""
        # Try environment variable first
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            return api_key
        
        # Try loading from config/secrets.yaml
        try:
            import yaml
            from pathlib import Path
            config_path = Path("config/secrets.yaml")
            if config_path.exists():
                with open(config_path, "r") as f:
                    config = yaml.safe_load(f) or {}
                    openai_config = config.get("openai", {})
                    api_key = openai_config.get("api_key", "")
                    if api_key:
                        return api_key
        except Exception as e:
            logger.warning(f"Failed to load OpenAI key from config: {e}")
        
        return None

    # Embeddings ----------------------------------------------------
    @lru_cache(maxsize=1000)
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _embed(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text."""
        if not self.enabled or not self.client:
            return None
        try:
            response = self.client.embeddings.create(
                model="text-embedding-3-small", 
                input=text
            )
            return response.data[0].embedding
        except Exception as exc:
            logger.warning("Embedding generation failed: %s", exc)
            raise

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Public method to get embeddings."""
        return self._embed(text)

    # Retrieval -----------------------------------------------------
    def retrieve_relevant_answers(
        self, 
        query: str, 
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant QA entries for a query."""
        if not self.enabled:
            return []
        vector = self._embed(query)
        if not vector:
            return []
        return self.store.search(vector, top_k, similarity_threshold)

    # AI Generation with Threads API ------------------------------
    def generate_message(
        self, 
        prompt: str,
        thread_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[str, str]:
        """
        Generate a message using OpenAI Threads API for continuous conversation.
        
        Args:
            prompt: The user's request/context for message generation
            thread_id: Existing thread ID to continue conversation, or None to create new
            context: Additional context (resume, job description, etc.)
            
        Returns:
            tuple[str, str]: (generated_message, thread_id)
        """
        if not self.client:
            return "感谢您的关注，期待进一步沟通。", ""
        
        try:
            # Create or get thread
            if thread_id:
                # Continue existing conversation
                thread = None  # We'll use existing thread_id
            else:
                # Create new thread with initial context
                thread = self.client.beta.threads.create()
                thread_id = thread.id
                
                # Add system context as first message if creating new thread
                if context:
                    context_message = self._build_context_message(context)
                    if context_message:
                        self.client.beta.threads.messages.create(
                            thread_id=thread_id,
                            role="user",
                            content=context_message
                        )
            
            # Add user's current request
            self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=prompt
            )
            
            # Run with assistant
            run = self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=self._get_or_create_assistant(),
            )
            
            # Wait for completion
            import time
            max_wait = 30  # 30 seconds timeout
            elapsed = 0
            while elapsed < max_wait:
                run_status = self.client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
                
                if run_status.status == "completed":
                    break
                elif run_status.status in {"failed", "cancelled", "expired"}:
                    logger.error(f"Run failed with status: {run_status.status}")
                    return "抱歉，消息生成失败，请稍后重试。", thread_id
                
                time.sleep(1)
                elapsed += 1
            
            if elapsed >= max_wait:
                logger.error("Run timed out")
                return "消息生成超时，请稍后重试。", thread_id
            
            # Get the latest assistant message
            messages = self.client.beta.threads.messages.list(
                thread_id=thread_id,
                order="desc",
                limit=1
            )
            
            if messages.data and messages.data[0].role == "assistant":
                content_blocks = []
                for content in messages.data[0].content:
                    if hasattr(content, "text") and hasattr(content.text, "value"):
                        content_blocks.append(content.text.value)
                
                generated_message = "\n".join(content_blocks) if content_blocks else "消息生成成功，但内容为空。"
                return generated_message, thread_id
            
            return "未能获取生成的消息。", thread_id
            
        except Exception as exc:
            logger.error(f"Message generation failed: {exc}")
            return "抱歉，消息生成失败，请稍后重试。", thread_id or ""
    
    def _build_context_message(self, context: Dict[str, Any]) -> str:
        """Build initial context message for new thread."""
        parts = []
        
        if context.get("company_description"):
            parts.append(f"【公司介绍】\n{context['company_description']}")
        
        if context.get("job_description"):
            parts.append(f"【岗位描述】\n{context['job_description']}")
        
        if context.get("target_profile"):
            parts.append(f"【理想人选】\n{context['target_profile']}")
        
        if context.get("candidate_resume"):
            parts.append(f"【候选人简历】\n{context['candidate_resume']}")
        
        if context.get("chat_history"):
            parts.append(f"【历史对话】\n{context['chat_history']}")
        
        if parts:
            return "以下是背景信息，请在后续对话中参考：\n\n" + "\n\n".join(parts)
        
        return ""
    
    def _get_or_create_assistant(self) -> str:
        """Get or create a persistent assistant for recruitment conversations."""
        # Check if we have a cached assistant ID
        if hasattr(self, "_assistant_id") and self._assistant_id:
            return self._assistant_id
        
        # Create new assistant
        assistant = self.client.beta.assistants.create(
            name="招聘助理",
            instructions=(
                "你是一个专业的招聘顾问助理。你的职责是：\n"
                "1. 根据候选人背景和公司需求，生成专业、真诚的招聘消息\n"
                "2. 对于首次联系，生成友好的打招呼消息，突出公司亮点\n"
                "3. 对于跟进消息，基于之前的对话历史，生成个性化的跟进内容\n"
                "4. 保持专业、简洁、真诚的沟通风格\n"
                "5. 突出候选人与岗位的匹配点\n\n"
                "请始终使用中文回复，消息长度控制在100-200字。"
            ),
            model=OPENAI_DEFAULT_MODEL,
        )
        
        self._assistant_id = assistant.id
        return self._assistant_id
    
    # Backward compatibility wrappers
    def generate_greeting(self, prompt_context: str, thread_id: Optional[str] = None) -> str:
        """
        Generate greeting message (backward compatibility).
        
        Returns only the message. Use generate_message() for thread_id.
        """
        message, _ = self.generate_message(
            prompt=f"候选人资料：{prompt_context}\n\n请生成一条合适的首次打招呼消息。",
            thread_id=thread_id
        )
        return message
    
    def generate_followup_message(
        self, 
        candidate_id: str, 
        prompt: str, 
        context: Dict[str, Any]
    ) -> str:
        """
        Generate followup message (backward compatibility).
        
        Returns only the message. Use generate_message() for thread_id.
        """
        # Try to get thread_id from candidate record
        record = self.get_candidate_record(candidate_id)
        thread_id = record.get("metadata", {}).get("thread_id") if record else None
        
        message, new_thread_id = self.generate_message(
            prompt=prompt or "请生成一条跟进消息。",
            thread_id=thread_id,
            context=context
        )
        
        # Update candidate record with thread_id if it's new
        if new_thread_id and not thread_id:
            self.upsert_candidate(
                candidate_id=candidate_id,
                metadata_extra={"thread_id": new_thread_id}
            )
        
        return message
    
    def generate_greeting_for_candidate(
        self,
        candidate_name: str = None,
        candidate_title: str = None,
        candidate_summary: str = None,
        candidate_resume: str = None,
        job_info: dict = None
    ) -> str:
        """
        Generate AI-powered greeting message for a specific candidate.
        
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
            return DEFAULT_GREETING
        
        # Build candidate info section with available data
        candidate_sections = []
        if candidate_name:
            candidate_sections.append(f"姓名：{candidate_name}")
        if candidate_title:
            candidate_sections.append(f"当前职位：{candidate_title}")
        if candidate_summary:
            candidate_sections.append(f"背景简介：{candidate_summary}")
        if candidate_resume:
            candidate_sections.append(f"完整简历：{candidate_resume}")
        
        candidate_info = "\n".join(candidate_sections) if candidate_sections else "候选人信息：暂无详细信息"
        
        # Build job info section
        job_sections = []
        if job_info:
            if job_info.get("title"):
                job_sections.append(f"岗位：{job_info['title']}")
            if job_info.get("company_description"):
                job_sections.append(f"公司介绍：{job_info['company_description']}")
            if job_info.get("target_profile"):
                job_sections.append(f"理想人选：{job_info['target_profile']}")
        
        job_info_text = "\n".join(job_sections) if job_sections else "招聘信息：暂无详细信息"

        prompt = f"""请为以下候选人生成一条专业的打招呼消息：

【候选人信息】
{candidate_info}

【招聘信息】
{job_info_text}

请生成一条：
1. 专业且真诚的打招呼消息
2. 突出公司与岗位的亮点
3. 体现对候选人背景的认可
4. 长度控制在100-200字
5. 使用中文，语气友好专业

直接输出消息内容，不要包含其他说明文字。"""

        try:
            response = self.client.chat.completions.create(
                model=OPENAI_DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=300
            )
            
            message = response.choices[0].message.content if response.choices else ""
            return message.strip() if message else DEFAULT_GREETING
            
        except Exception as exc:
            logger.error(f"Greeting generation failed: {exc}")
            return DEFAULT_GREETING

    def analyze_candidate(
        self, 
        candidate_id: str, 
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Analyze candidate and return scoring results."""
        if not self.client:
            raise SystemError("OpenAI client not available for candidate analysis")
        
        prompt = f"""请基于以下信息对候选人做出量化评估。

【公司介绍】
{context.get('company_description', '')}

【岗位描述】
{context.get('job_description', '')}

【理想人选画像】
{context.get('target_profile', '')}

【候选人材料】
{context.get('candidate_resume', '')}

【近期对话】
{context.get('chat_history', '')}

请给出 1-10 的四个评分：技能匹配度、创业契合度、加入意愿、综合评分，并提供简要分析。输出严格使用 JSON 格式：
{{
  "skill": <int>,
  "startup_fit": <int>,
  "willingness": <int>,
  "overall": <int>,
  "summary": "..."
}}
"""
        try:
            response = self.client.chat.completions.create(
                model=OPENAI_DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.choices[0].message.content if response.choices else ""
            data = self._parse_json_from_text(text)
            if not data:
                logger.error("无法解析评分结果")
            return data
        except Exception as exc:
            logger.error(f"调用 OpenAI 失败: {exc}")
            return None

    def _parse_json_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from text content."""
        try:
            import json
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                return json.loads(text[start:end + 1])
        except Exception:
            pass
        return None

    # Candidate Management --------------------------------------
    def get_candidate_record(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve candidate record from store."""
        if not self.enabled:
            return None
        # This would query Zilliz - simplified for now
        return None

    def upsert_candidate(
        self,
        candidate_id: str,
        *,
        name: Optional[str] = None,
        job_applied: Optional[str] = None,
        last_message: Optional[str] = None,
        resume_text: Optional[str] = None,
        scores: Optional[Dict[str, Any]] = None,
        metadata_extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Upsert candidate information to the store."""
        if not self.enabled:
            logger.warning("Store not available, cannot upsert candidate")
            return False
        
        # Simplified implementation - in full version this would:
        # 1. Get existing record
        # 2. Merge with new data
        # 3. Generate embeddings if resume_text changed
        # 4. Upsert to Zilliz
        logger.info(f"Upsert candidate {candidate_id} (store enabled but simplified)")
        return True

    # QA Persistence ---------------------------------------------------
    def record_qa(
        self, 
        *, 
        qa_id: str | None = None, 
        question: str, 
        answer: str,
        keywords: Optional[List[str]] = None
    ) -> str | None:
        """Record a QA entry in the store."""
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
        """List QA entries from store."""
        if not self.enabled:
            return []
        # Simplified - would query Zilliz in full version
        return []

    def delete_entry(self, resume_id: str) -> bool:
        """Delete a QA entry from store."""
        if not self.enabled:
            return False
        # Simplified - would delete from Zilliz in full version
        return False

    @staticmethod
    def generate_id() -> str:
        """Generate a unique ID."""
        return uuid4().hex


# Global instance
assistant_actions = AssistantActions()

__all__ = ["assistant_actions", "AssistantActions", "DEFAULT_GREETING"]
