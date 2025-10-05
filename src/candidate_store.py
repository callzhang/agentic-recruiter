"""Zilliz/Milvus-backed QA and candidate interaction store integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    SearchResult,
    connections,
    utility,
)

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "CN_recruitment"
DEFAULT_RECORDS_COLLECTION = "candidate_records"
DEFAULT_ACTIONS_COLLECTION = "candidate_actions"
DEFAULT_DIMENSION = 1536
DEFAULT_TOP_K = 5


class CandidateStore:
    def __init__(
        self,
        endpoint: str,
        collection_name: str,
        embedding_dim: int = DEFAULT_DIMENSION,
        similarity_top_k: int = DEFAULT_TOP_K,
        token: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        secure: Optional[bool] = None,
        records_collection_name: str = DEFAULT_RECORDS_COLLECTION,
        actions_collection_name: str = DEFAULT_ACTIONS_COLLECTION,
    ) -> None:
        self.endpoint = endpoint
        self.token = token
        self.user = user
        self.password = password
        self.collection_name = collection_name
        self.records_collection_name = records_collection_name
        self.actions_collection_name = actions_collection_name
        self.embedding_dim = embedding_dim
        self.similarity_top_k = similarity_top_k
        self.secure = secure if secure is not None else endpoint.startswith("https://")
        self.collection: Optional[Collection] = None
        self.records_collection: Optional[Collection] = None
        self.actions_collection: Optional[Collection] = None
        self.enabled = self._connect_and_prepare()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def _connect_and_prepare(self) -> bool:
        try:
            logger.info("Connecting to Zilliz endpoint %s", self.endpoint)
            connect_args: Dict[str, Any] = {"alias": "default"}
            if self.token:
                connect_args.update({
                    "uri": self.endpoint,
                    "token": self.token,
                    "secure": self.secure,
                })
            else:
                connect_args.update(
                    {
                        "uri": self.endpoint,
                        "user": self.user,
                        "password": self.password,
                        "secure": self.secure,
                    }
                )
            connections.connect(**connect_args)
            self.collection = self._ensure_qa_collection(self.collection_name)
            self.records_collection = self._ensure_records_collection(self.records_collection_name)
            self.actions_collection = self._ensure_actions_collection(self.actions_collection_name)
            return True
        except Exception as exc:  # pragma: no cover - network operations
            logger.error("Failed to connect to Zilliz: %s", exc)
            self.collection = None
            self.records_collection = None
            self.actions_collection = None
            return False

    def _ensure_qa_collection(self, name: str) -> Collection:
        if not utility.has_collection(name):
            logger.info("Creating QA collection %s", name)
            dim = self.embedding_dim if self.embedding_dim else DEFAULT_DIMENSION
            fields = [
                FieldSchema(name="qa_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
                FieldSchema(name="question", dtype=DataType.VARCHAR, max_length=2048),
                FieldSchema(name="answer", dtype=DataType.VARCHAR, max_length=4096),
                FieldSchema(name="qa_vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="keywords", dtype=DataType.JSON),
            ]
            schema = CollectionSchema(fields, description="Candidate QA entries")
            collection = Collection(name=name, schema=schema)
            index_params = {
                "index_type": "AUTOINDEX",
                "metric_type": "IP",
                "params": {},
            }
            collection.create_index(field_name="qa_vector", index_params=index_params)
        collection = Collection(name)
        try:
            collection.load()
        except Exception:
            logger.info("Loading collection %s", name)
            collection.load()
        return collection

    def _ensure_records_collection(self, name: str) -> Optional[Collection]:
        try:
            if not utility.has_collection(name):
                logger.info("Creating candidate record collection %s", name)
                dim = self.embedding_dim if self.embedding_dim else DEFAULT_DIMENSION
                fields = [
                    FieldSchema(name="record_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
                    FieldSchema(name="candidate_id", dtype=DataType.VARCHAR, max_length=64),
                    FieldSchema(name="chat_id", dtype=DataType.VARCHAR, max_length=64),
                    FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=255),
                    FieldSchema(name="job_applied", dtype=DataType.VARCHAR, max_length=255),
                    FieldSchema(name="status", dtype=DataType.VARCHAR, max_length=64),
                    FieldSchema(name="overall_score", dtype=DataType.FLOAT),
                    FieldSchema(name="score_detail", dtype=DataType.JSON),
                    FieldSchema(name="last_message", dtype=DataType.VARCHAR, max_length=4096),
                    FieldSchema(name="resume_embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
                    FieldSchema(name="metadata", dtype=DataType.JSON),
                    FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64),
                ]
                schema = CollectionSchema(fields, description="Candidate profile records")
                collection = Collection(name=name, schema=schema)
                index_params = {
                    "index_type": "AUTOINDEX",
                    "metric_type": "IP",
                    "params": {},
                }
                collection.create_index(field_name="resume_embedding", index_params=index_params)
            collection = Collection(name)
            collection.load()
            return collection
        except Exception as exc:  # pragma: no cover - network operations
            logger.warning("Failed to initialise candidate records collection %s: %s", name, exc)
            return None

    def _ensure_actions_collection(self, name: str) -> Optional[Collection]:
        try:
            if not utility.has_collection(name):
                logger.info("Creating candidate actions collection %s", name)
                dim = self.embedding_dim if self.embedding_dim else DEFAULT_DIMENSION
                fields = [
                    FieldSchema(name="action_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
                    FieldSchema(name="candidate_id", dtype=DataType.VARCHAR, max_length=64),
                    FieldSchema(name="chat_id", dtype=DataType.VARCHAR, max_length=64),
                    FieldSchema(name="action_type", dtype=DataType.VARCHAR, max_length=64),
                    FieldSchema(name="score", dtype=DataType.FLOAT),
                    FieldSchema(name="summary", dtype=DataType.VARCHAR, max_length=1024),
                    FieldSchema(name="metadata", dtype=DataType.JSON),
                    FieldSchema(name="action_embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
                    FieldSchema(name="timestamp", dtype=DataType.VARCHAR, max_length=64),
                ]
                schema = CollectionSchema(fields, description="Candidate action logs")
                collection = Collection(name=name, schema=schema)
                index_params = {
                    "index_type": "AUTOINDEX",
                    "metric_type": "IP",
                    "params": {},
                }
                collection.create_index(field_name="action_embedding", index_params=index_params)
            collection = Collection(name)
            collection.load()
            return collection
        except Exception as exc:  # pragma: no cover - network operations
            logger.warning("Failed to initialise candidate actions collection %s: %s", name, exc)
            return None

    def _zero_vector(self) -> List[float]:
        dim = self.embedding_dim if self.embedding_dim else DEFAULT_DIMENSION
        return [0.0] * dim

    def _normalise_vector(self, vector: Optional[Iterable[float]]) -> List[float]:
        if not vector:
            return self._zero_vector()
        data = list(vector)
        dim = self.embedding_dim if self.embedding_dim else DEFAULT_DIMENSION
        if len(data) != dim:
            logger.debug("Embedding dimension mismatch, padding to %s", dim)
            padded = self._zero_vector()
            for idx, value in enumerate(data[:dim]):
                padded[idx] = float(value)
            return padded
        return [float(x) for x in data]

    # ------------------------------------------------------------------
    # QA operations
    # ------------------------------------------------------------------
    def insert(self, entries: Iterable[Dict[str, Any]]) -> None:
        if not self.enabled or not self.collection:
            return
        if not entries:
            return
        qa_ids: List[str] = []
        questions: List[str] = []
        answers: List[str] = []
        vectors: List[List[float]] = []
        keywords_col: List[Any] = []

        for entry in entries:
            try:
                qa_ids.append(str(entry["qa_id"]))
                questions.append(entry.get("question", ""))
                answers.append(entry.get("answer", ""))
                vectors.append(list(entry["qa_vector"]))
                keywords_col.append(entry.get("keywords", []))
            except KeyError as err:
                logger.warning("Skipping incomplete QA entry: %s", err)
            except Exception as exc:
                logger.warning("Skipping malformed QA entry: %s", exc)

        if qa_ids:
            data = [qa_ids, questions, answers, vectors, keywords_col]
            self.collection.insert(data)
            self.collection.flush()

    def search(
        self,
        vector: List[float],
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = 0.9
    ) -> List[Dict[str, Any]]:
        """Search for similar QA entries."""
        if not self.enabled or not self.collection:
            return []
        if not vector:
            return []
        limit = top_k or self.similarity_top_k
        search_params = {
            "metric_type": "IP",
            "params": {"ef": 32},
        }
        results: List[SearchResult] = self.collection.search(
            data=[vector],
            anns_field="qa_vector",
            limit=limit,
            param=search_params,
        )
        hits: List[Dict[str, Any]] = []
        for hit in results[0][:limit]:
            score = hit.score
            if similarity_threshold is not None and score < similarity_threshold:
                continue
            hits.append(
                {
                    "score": score,
                    "entity": hit.entity,
                }
            )
        return hits

    # ------------------------------------------------------------------
    # Candidate record persistence
    # ------------------------------------------------------------------
    def upsert_candidate_profile(
        self,
        *,
        candidate_id: str,
        chat_id: Optional[str],
        name: Optional[str],
        job_applied: Optional[str],
        status: str,
        overall_score: Optional[float],
        score_detail: Optional[Dict[str, Any]],
        last_message: Optional[str],
        embedding: Optional[Iterable[float]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.enabled or not self.records_collection:
            return False
        record = {
            "record_id": uuid4().hex,
            "candidate_id": candidate_id,
            "chat_id": chat_id or "",
            "name": name or "",
            "job_applied": job_applied or "",
            "status": status,
            "overall_score": float(overall_score) if overall_score is not None else None,
            "score_detail": score_detail or {},
            "last_message": last_message or "",
            "resume_embedding": self._normalise_vector(embedding),
            "metadata": metadata or {},
            "updated_at": datetime.utcnow().isoformat(),
        }
        try:
            self.records_collection.insert([record])
            self.records_collection.flush()
            return True
        except Exception as exc:  # pragma: no cover - network operations
            logger.warning("Failed to upsert candidate profile %s: %s", candidate_id, exc)
            return False

    def get_candidate_profile(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled or not self.records_collection:
            return None
        try:
            results = self.records_collection.query(
                expr=f"candidate_id == '{candidate_id}'",
                output_fields=[
                    "record_id",
                    "candidate_id",
                    "chat_id",
                    "name",
                    "job_applied",
                    "status",
                    "overall_score",
                    "score_detail",
                    "last_message",
                    "metadata",
                    "updated_at",
                ],
                consistency_level="Strong",
            )
        except Exception as exc:  # pragma: no cover - network operations
            logger.warning("Failed to query candidate profile %s: %s", candidate_id, exc)
            return None
        if not results:
            return None
        latest = max(results, key=lambda item: item.get("updated_at", ""))
        return latest

    def log_candidate_action(
        self,
        *,
        candidate_id: str,
        chat_id: Optional[str],
        action_type: str,
        score: Optional[float],
        summary: str,
        embedding: Optional[Iterable[float]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.enabled or not self.actions_collection:
            return False
        entry = {
            "action_id": uuid4().hex,
            "candidate_id": candidate_id,
            "chat_id": chat_id or "",
            "action_type": action_type,
            "score": float(score) if score is not None else None,
            "summary": summary,
            "metadata": metadata or {},
            "action_embedding": self._normalise_vector(embedding),
            "timestamp": datetime.now().isoformat(),
        }
        try:
            self.actions_collection.insert([entry])
            self.actions_collection.flush()
            return True
        except Exception as exc:  # pragma: no cover - network operations
            logger.warning("Failed to log candidate action %s: %s", candidate_id, exc)
            return False


# Create global instance with safe defaults
# Load configuration from environment or config file
def _create_candidate_store() -> CandidateStore:
    """Create candidate store instance with configuration."""
    from .config import settings
    
    # Use settings from config.py
    endpoint = settings.ZILLIZ_ENDPOINT
    user = settings.ZILLIZ_USER
    password = settings.ZILLIZ_PASSWORD
    collection_name = settings.ZILLIZ_COLLECTION_NAME
    embedding_dim = settings.ZILLIZ_EMBEDDING_DIM
    similarity_top_k = settings.ZILLIZ_SIMILARITY_TOP_K
    
    # Use default collection names for records and actions
    records_collection_name = DEFAULT_RECORDS_COLLECTION
    actions_collection_name = DEFAULT_ACTIONS_COLLECTION

    if not endpoint:
        logger.info("No Zilliz endpoint configured, candidate store will be disabled")
        endpoint = "http://localhost:19530"

    return CandidateStore(
        endpoint=endpoint,
        collection_name=collection_name,
        embedding_dim=embedding_dim,
        similarity_top_k=similarity_top_k,
        user=user if user else None,
        password=password if password else None,
        records_collection_name=records_collection_name,
        actions_collection_name=actions_collection_name,
    )


default_store = _create_candidate_store()

candidate_store = default_store

__all__ = ["candidate_store", "CandidateStore"]
