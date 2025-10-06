"""Zilliz/Milvus-backed QA and candidate interaction store integration."""
from __future__ import annotations

import json
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

# DEFAULT_COLLECTION = "CN_recruitment"
CANDIDATE_COLLECTION = "CN_candidates"
# DEFAULT_RECORDS_COLLECTION = "candidate_records"
# DEFAULT_ACTIONS_COLLECTION = "candidate_actions"
DEFAULT_DIMENSION = 1536
DEFAULT_TOP_K = 5

class CandidateStore:
    def __init__(
        self,
        endpoint: str,
        collection_name: str = CANDIDATE_COLLECTION,
        embedding_dim: int = DEFAULT_DIMENSION,
        similarity_top_k: int = DEFAULT_TOP_K,
        token: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        secure: Optional[bool] = None,
    ) -> None:
        self.endpoint = endpoint
        self.token = token
        self.user = user
        self.password = password
        self.collection_name = collection_name
        self.embedding_dim = embedding_dim
        self.similarity_top_k = similarity_top_k
        self.secure = secure if secure is not None else endpoint.startswith("https://")
        self.collection: Optional[Collection] = None
        self.enabled = self._connect_and_prepare()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def _connect_and_prepare(self) -> bool:

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
            self.collection = self._ensure_candidate_collection(self.collection_name)
            return True

    def _ensure_candidate_collection(self, name: str) -> Collection:
        if not utility.has_collection(name):
            logger.error("Creating candidate collection %s", name)
            dim = self.embedding_dim if self.embedding_dim else DEFAULT_DIMENSION
            fields = [
                FieldSchema(name="candidate_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
                FieldSchema(name="resume_vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="job_applied", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="last_message", dtype=DataType.VARCHAR, max_length=2048),
                FieldSchema(name="resume_text", dtype=DataType.VARCHAR, max_length=8192),
                FieldSchema(name="scores", dtype=DataType.JSON),
                FieldSchema(name="metadata", dtype=DataType.JSON),
                FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64),
            ]
            schema = CollectionSchema(fields, description="Candidate profiles")
            collection = Collection(name=name, schema=schema)
            index_params = {
                "index_type": "AUTOINDEX",
                "metric_type": "IP",
                "params": {},
            }
            collection.create_index(field_name="resume_vector", index_params=index_params)
        collection = Collection(name)
        logger.info("Loading collection %s", name)
        collection.load()
        return collection


    # ------------------------------------------------------------------
    # Candidate operations
    # ------------------------------------------------------------------
    def upsert_candidate(
        self,
        *,
        candidate_id: str,
        name: Optional[str] = None,
        job_applied: Optional[str] = None,
        last_message: Optional[str] = None,
        resume_text: Optional[str] = None,
        scores: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        resume_vector: Optional[Iterable[float]] = None,
    ) -> bool:
        """Insert or update candidate data using Milvus upsert method."""
        if not self.enabled or not self.collection:
            return False
        
        # Prepare data as dictionary for upsert
        data = {
            "candidate_id": candidate_id,
            "resume_vector": self._normalise_vector(resume_vector) if resume_vector else [],
            "name": name or "",
            "job_applied": job_applied or "",
            "last_message": last_message or "",
            "resume_text": resume_text or "",
            "scores": scores or {},
            "metadata": metadata or {},
            "updated_at": datetime.now().isoformat(),
        }

        if candidate_id:        
            # Use upsert for atomic insert/update
            self.collection.upsert([data], partial=True)
            self.collection.flush()
            return True
        else:
            '''use semantic search to find the most similar candidate'''
            results = self.search_candidates(data["resume_vector"])
            if results:
                data['candidate_id'] = results[0]['entity']['candidate_id']
                self.collection.upsert([data], partial=True)
                self.collection.flush()
                return True
            else:
                return False

    def search_candidates(
        self,
        vector: List[float],
        top_k: Optional[int] = 1,
        similarity_threshold: Optional[float] = 0.9
    ) -> List[Dict[str, Any]]:
        """Search for similar candidates by resume vector."""
        if not self.enabled or not self.collection:
            return []
        limit = top_k or self.similarity_top_k
        search_params = {
            "metric_type": "IP",
            "params": {"ef": 32},
        }
        results: List[SearchResult] = self.collection.search(
            data=[vector],
            anns_field="resume_vector",
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

    def get_candidate_by_id(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single candidate record by its primary key."""
        if not candidate_id or not self.enabled or not self.collection:
            return None

        expr = f"candidate_id == {json.dumps(candidate_id)}"
        try:
            results = self.collection.query(
                expr=expr,
                output_fields=[
                    "candidate_id",
                    "name",
                    "job_applied",
                    "last_message",
                    "resume_text",
                    "scores",
                    "metadata",
                    "updated_at",
                ],
                limit=1,
            )
        except Exception as exc:  # pragma: no cover - Milvus errors surface here
            logger.exception("Failed to query candidate %s: %s", candidate_id, exc)
            return None

        if not results:
            return None
        return results[0]

    def update_candidate_metadata(self, candidate_id: str, metadata: Dict[str, Any]) -> bool:
        """Merge metadata updates for a candidate without touching other fields."""
        if not candidate_id or not self.enabled or not self.collection:
            return False

        payload = {
            "candidate_id": candidate_id,
            "metadata": metadata or {},
            "updated_at": datetime.now().isoformat(),
        }

        try:
            self.collection.upsert([payload], partial=True)
            self.collection.flush()
        except Exception as exc:  # pragma: no cover - Milvus errors surface here
            logger.exception("Failed to update metadata for %s: %s", candidate_id, exc)
            return False
        return True

# ------------------------------------------------------------------
# Candidate record persistence
# ------------------------------------------------------------------



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
    )

default_store = _create_candidate_store()

candidate_store = default_store

__all__ = ["candidate_store", "CandidateStore"]
