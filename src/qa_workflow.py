"""Workflow helpers that pair OpenAI-generated greetings with Zilliz storage."""
from __future__ import annotations

import logging
import os
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


class QAWorkflow:
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

    def list_entries(self, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        return self.store.list_entries(limit=limit, offset=offset)

    def delete_entry(self, resume_id: str) -> bool:
        if not self.enabled:
            return False
        return self.store.delete_entry(resume_id)

    @staticmethod
    def generate_id() -> str:
        return uuid4().hex


qa_workflow = QAWorkflow()

__all__ = ["qa_workflow", "QAWorkflow", "DEFAULT_GREETING"]
