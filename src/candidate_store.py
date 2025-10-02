"""Zilliz/Milvus-backed QA store integration."""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional
from pymilvus import (Collection, CollectionSchema, DataType, FieldSchema,
                      connections, utility, SearchResult)

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "CN_recruitment"
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

    def _connect_and_prepare(self) -> bool:
        try:
            logger.info("Connecting to Zilliz endpoint %s", self.endpoint)
            connect_args: Dict[str, Any] = {"alias": "default"}
            if self.token:
                connect_args.update({"uri": self.endpoint, "token": self.token, "secure": self.secure})
            else:
                connect_args.update({
                    "uri": self.endpoint,
                    "user": self.user,
                    "password": self.password,
                    "secure": self.secure,
                })
            connections.connect(**connect_args)
            self.collection = self._ensure_collection(self.collection_name)
            return True
        except Exception as exc:  # pragma: no cover - network operations
            logger.error("Failed to connect to Zilliz: %s", exc)
            self.collection = None
            return False

    def _ensure_collection(self, name: str) -> Collection:
        if not utility.has_collection(name):
            logger.info("Creating collection %s", name)
            dim = self.embedding_dim if self.embedding_dim else DEFAULT_DIMENSION
            fields = [
                FieldSchema(name="qa_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
                FieldSchema(name="question", dtype=DataType.VARCHAR, max_length=2048),
                FieldSchema(name="answer", dtype=DataType.VARCHAR, max_length=4096),
                FieldSchema(name="qa_vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="keywords", dtype=DataType.JSON),
            ]
            schema = CollectionSchema(fields, description="Candidate store (resume embeddings)")
            collection = Collection(name=name, schema=schema)
            index_params = {
                "index_type": "AUTOINDEX",
                "metric_type": "IP",
                "params": {}
            }
            collection.create_index(field_name="qa_vector", index_params=index_params)
        collection = Collection(name)
        try:
            collection.load()
        except Exception:
            logger.info("Loading collection %s", name)
            collection.load()
        return collection

    # Public API -----------------------------------------------------

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
        """Search for similar QA entries.

        Args:
            vector: Query embedding vector
            top_k: Maximum number of results to return
            similarity_threshold: Minimum similarity score (0-1).
                                 For Inner Product metric, scores typically range from 0-1.
                                 Only results with score >= threshold are returned.

        Returns:
            List of results with similarity scores, filtered by threshold if specified.
        """
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
            anns_field="candidate_store",
            limit=limit,
            param=search_params,
        )
        hits: List[Dict[str, Any]] = []
        for hit in results[0][:limit]:
            score = hit.score
            # Apply similarity threshold filter
            if similarity_threshold is not None and score < similarity_threshold:
                continue
            hits.append({
                "score": score,
                "entity": hit.entity
            })
        return hits


# Create global instance with safe defaults
# Load configuration from environment or config file
def _create_candidate_store() -> CandidateStore:
    """Create candidate store instance with configuration."""
    import os
    import yaml
    from pathlib import Path
    
    # Try to load from config/secrets.yaml
    config_path = Path("config/secrets.yaml")
    endpoint = os.getenv("ZILLIZ_ENDPOINT", "")
    token = os.getenv("ZILLIZ_TOKEN", "")
    collection_name = os.getenv("ZILLIZ_CANDIDATE_COLLECTION", DEFAULT_COLLECTION)
    
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}
                zilliz_config = config.get("zilliz", {})
                endpoint = endpoint or zilliz_config.get("endpoint", "")
                token = token or zilliz_config.get("token", "")
                collection_name = collection_name or zilliz_config.get("candidate_collection", DEFAULT_COLLECTION)
        except Exception as e:
            logger.warning(f"Failed to load config from {config_path}: {e}")
    
    # Create store (will be disabled if no valid config)
    if not endpoint:
        logger.info("No Zilliz endpoint configured, candidate store will be disabled")
        # Create a dummy instance that will fail to connect
        endpoint = "http://localhost:19530"  # Dummy endpoint
    
    return CandidateStore(
        endpoint=endpoint,
        collection_name=collection_name,
        token=token if token else None,
    )

candidate_store = _create_candidate_store()

__all__ = ["candidate_store", "CandidateStore"]

