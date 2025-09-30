"""Assistant actions that pair OpenAI-generated greetings with Zilliz storage."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

import yaml

from tenacity import retry, stop_after_attempt, wait_exponential

from .qa_store import QAStore, qa_store

logger = logging.getLogger(__name__)

DEFAULT_GREETING = "您好，我们是一家AI科技公司，对您的背景十分感兴趣，希望能进一步沟通。"
OPENAI_DEFAULT_MODEL = os.getenv("BOSSZP_GPT_MODEL", "gpt-4o-mini")


class AssistantActions:
    def __init__(self, store: QAStore | None = None) -> None:
        self.store = store or qa_store
        self.enabled = bool(self.store and self.store.enabled)
        api_key = os.getenv("OPENAI_API_KEY") or self._load_openai_key()
        if OpenAI and api_key:
            os.environ.setdefault("OPENAI_API_KEY", api_key)
            self.client = OpenAI(api_key=api_key)
        else:
            self.client = None
            if self.enabled:
                logger.info("OpenAI API key not configured; falling back to static greetings")

    @staticmethod
    def _load_openai_key(path: Path = Path("config/secrets.yaml")) -> Optional[str]:
        if not path.exists():
            return None
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and "openai" in item:
                    entries = item["openai"]
                    if isinstance(entries, list):
                        for entry in entries:
                            if isinstance(entry, dict) and entry.get("api_key"):
                                return str(entry["api_key"])
        if isinstance(payload, dict):
            if "openai" in payload and isinstance(payload["openai"], dict):
                return str(payload["openai"].get("api_key") or "") or None
            if payload.get("openai_api_key"):
                return str(payload["openai_api_key"])
        return None

    # Embeddings ----------------------------------------------------
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _embed(self, text: str) -> Optional[List[float]]:
        if not self.enabled or not self.client:
            return None
        config = self.store.config if self.store else None
        model = config.embedding_model if config else "text-embedding-3-small"
        try:
            response = self.client.embeddings.create(model=model, input=text)
            return response.data[0].embedding  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - network failure
            logger.warning("Embedding generation failed: %s", exc)
            raise

    def get_embedding(self, text: str) -> Optional[List[float]]:
        try:
            return self._embed(text)
        except Exception:
            return None

    # Candidate store helpers -----------------------------------------------

    def get_candidate_record(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        if not self.store or not hasattr(self.store, "get_candidate"):
            return None
        try:
            return self.store.get_candidate(candidate_id)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug("Failed to fetch candidate record: %s", exc)
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
    ) -> None:
        if not self.store or not hasattr(self.store, "upsert_candidates"):
            return

        existing = self.get_candidate_record(candidate_id) or {}
        metadata = dict(existing.get("metadata") or {})
        if metadata_extra:
            metadata.update(metadata_extra)

        stored_resume = existing.get("resume_text", "")
        resume_value = resume_text if resume_text is not None else stored_resume

        vector: List[float]
        if resume_text is not None and resume_text.strip() and resume_text.strip() != stored_resume:
            vector = self.get_embedding(resume_text.strip()) or [0.0] * (self.store.config.embedding_dim if self.store and self.store.config else 1536)
        else:
            vector = existing.get("resume_vector") or []
            if not vector:
                vector = [0.0] * (self.store.config.embedding_dim if self.store and self.store.config else 1536)

        entry = {
            "candidate_id": candidate_id,
            "name": name if name is not None else existing.get("name", ""),
            "job_applied": job_applied if job_applied is not None else existing.get("job_applied", ""),
            "last_message": last_message if last_message is not None else existing.get("last_message", ""),
            "resume_vector": vector,
            "resume_text": resume_value,
            "scores": scores if scores is not None else existing.get("scores", {}),
            "metadata": metadata,
            "updated_at": datetime.utcnow().isoformat(),
        }

        try:
            self.store.upsert_candidates([entry])  # type: ignore[attr-defined]
        except Exception as exc:
            logger.error("Failed to upsert candidate %s: %s", candidate_id, exc)

    def _build_background_text(self, context: Dict[str, Any]) -> str:
        return (
            f"公司介绍:\n{context.get('company_description', '')}\n\n"
            f"岗位描述:\n{context.get('job_description', '')}\n\n"
            f"理想人选画像:\n{context.get('target_profile', '')}\n\n"
            f"候选人简历:\n{context.get('candidate_resume', '')}\n\n"
            f"近期对话:\n{context.get('chat_history', '')}"
        )

    def _ensure_thread(self, candidate_id: str, context: Dict[str, Any]) -> Optional[str]:
        if not self.client:
            return None
        record = self.get_candidate_record(candidate_id) or {}
        metadata = dict(record.get("metadata") or {})
        thread_id = metadata.get("thread_id")
        if thread_id:
            return thread_id
        background = self._build_background_text(context)
        try:
            thread = self.client.beta.threads.create()
            if background.strip():
                self.client.beta.threads.messages.create(
                    thread_id=thread.id,
                    role="user",
                    content=f"以下是候选人背景资料，请在后续对话中记住：\n\n{background}",
                )
            metadata["thread_id"] = thread.id
            self.upsert_candidate(candidate_id, metadata_extra=metadata)
            return thread.id
        except Exception as exc:
            logger.error("Failed to create thread: %s", exc)
            return None

    # Retrieval -----------------------------------------------------
    def retrieve_relevant_answers(self, query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        vector = self._embed(query)
        if not vector:
            limit = top_k or (self.store.config.similarity_top_k if self.store and self.store.config else 5)
            logger.debug("Embedding unavailable for query; returning last %s entries", limit)
            return self.store.list_entries(limit=limit)
        return self.store.search(vector, top_k)

    # Generation ----------------------------------------------------
    def generate_greeting(self, prompt_context: str, fallback: str = DEFAULT_GREETING) -> str:
        if not self.client or not self.enabled:
            return fallback
        context_snippets = self.retrieve_relevant_answers(prompt_context)
        context_blocks = []
        for snippet in context_snippets:
            question = snippet.get("question") or ""
            answer = snippet.get("answer") or ""
            if question or answer:
                context_blocks.append(f"Q: {question}\nA: {answer}")
        context_text = "\n---\n".join(context_blocks)
        system_prompt = (
            "你是一个友好的招聘顾问，需要用中文向候选人发送第一条问候消息。"
            "保持专业、真诚、精简，同时突出公司的亮点。"
        )
        user_prompt = (
            f"候选人资料: {prompt_context}\n\n"
            f"历史问答参考: {context_text if context_text else '无'}\n\n"
            "请生成一条合适的首条打招呼消息。"
        )
        try:
            response = self.client.responses.create(
                model=OPENAI_DEFAULT_MODEL,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            output = response.output[0].content[0].text.strip()  # type: ignore[attr-defined]
            return output or fallback
        except Exception as exc:  # pragma: no cover - network failure
            logger.error("Greeting generation failed: %s", exc)
            return fallback

    # Persistence ---------------------------------------------------
    def record_qa(self, *, qa_id: str | None = None, question: str, answer: str,
                  keywords: Optional[List[str]] = None) -> str | None:
        if not self.enabled:
            return None
        text = f"问题: {question}\n回答: {answer}"
        vector = self._embed(text)
        if not vector:
            store_cfg = self.store.config if self.store else None
            dim = store_cfg.embedding_dim if store_cfg else 1536
            logger.debug("Embedding unavailable; storing zero-vector of dim %s", dim)
            vector = [0.0] * dim
        qa_id = (qa_id or self.generate_id()).strip()
        self.store.delete_entry(qa_id)
        entry = {
            "qa_id": qa_id,
            "question": question,
            "answer": answer,
            "qa_vector": vector,
            "keywords": keywords or [],
        }
        self.store.insert([entry])
        return qa_id

    def generate_followup_message(self, candidate_id: str, prompt: str, context: Dict[str, Any]) -> Optional[str]:
        if not self.client:
            return None
        thread_id = self._ensure_thread(candidate_id, context)
        if not thread_id:
            return None
        message_text = prompt.strip() or "请根据当前进展生成下一条沟通消息。"
        try:
            self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message_text,
            )
            run = self.client.beta.threads.runs.create(
                thread_id=thread_id,
                model=OPENAI_DEFAULT_MODEL,
                instructions="请作为专业的中文招聘顾问，结合已记录的候选人背景信息生成回复。",
            )
            while True:
                run_status = self.client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                if run_status.status == "completed":
                    break
                if run_status.status in {"failed", "cancelled", "expired"}:
                    logger.error("Thread run ended with status: %s", run_status.status)
                    return None
                time.sleep(1)
            messages = self.client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=10)
            for msg in messages.data:
                if getattr(msg, "role", "") == "assistant":
                    parts: List[str] = []
                    for part in getattr(msg, "content", []):
                        text_part = getattr(getattr(part, "text", None), "value", None)
                        if text_part:
                            parts.append(text_part)
                    if parts:
                        return "\n".join(parts).strip()
            return None
        except Exception as exc:
            logger.error("Failed to generate follow-up message: %s", exc)
            return None

    def list_entries(self, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        return self.store.list_entries(limit=limit, offset=offset)

    def delete_entry(self, resume_id: str) -> bool:
        if not self.enabled:
            return False
        return self.store.delete_entry(resume_id)

    def analyze_candidate(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Analyze candidate based on context and return scoring results."""
        if not self.client:
            logger.warning("OpenAI client not available for candidate analysis")
            return None
        
        prompt = f"""
你是一名资深招聘顾问，请基于以下信息对候选人做出量化评估。

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
            response = self.client.responses.create(
                model=OPENAI_DEFAULT_MODEL,
                input=[{"role": "user", "content": prompt}],
            )
            text = response.output[0].content[0].text  # type: ignore[attr-defined]
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
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                import json
                return json.loads(text[start:end + 1])
        except Exception:
            pass
        return None

    @staticmethod
    def generate_id() -> str:
        return uuid4().hex


assistant_actions = AssistantActions()

__all__ = ["assistant_actions", "AssistantActions", "DEFAULT_GREETING"]
