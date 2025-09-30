"""Zilliz/Milvus-backed QA store integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml
from pymilvus import (Collection, CollectionSchema, DataType, FieldSchema,
                      connections, utility)

logger = logging.getLogger(__name__)

DEFAULT_QA_COLLECTION = "CN_recruitment"
DEFAULT_CANDIDATE_COLLECTION = "CN_candidates"
DEFAULT_DIMENSION = 1536
DEFAULT_TOP_K = 5


@dataclass
class ZillizConfig:
    endpoint: str
    token: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    collection_name: str = DEFAULT_QA_COLLECTION
    embedding_model: str = "text-embedding-3-small"
    similarity_top_k: int = DEFAULT_TOP_K
    embedding_dim: int = DEFAULT_DIMENSION
    enable_cache: bool = False
    region: Optional[str] = None
    cluster: Optional[str] = None

    @property
    def secure(self) -> bool:
        return self.endpoint.startswith("https://")


def _load_raw_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        logger.warning("Secrets file %s not found", path)
        return {}
    payload = yaml.safe_load(path.read_text())
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and "zilliz" in item:
                entries = item["zilliz"]
                flattened: Dict[str, Any] = {}
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            flattened.update(entry)
                return flattened
    if isinstance(payload, dict) and "zilliz" in payload:
        node = payload["zilliz"]
        if isinstance(node, dict):
            return node
    return {}


def load_config(path: Path = Path("config/secrets.yaml")) -> Optional[ZillizConfig]:
    raw = _load_raw_config(path)
    endpoint = raw.get("endpoint") or raw.get("uri")
    token = raw.get("token") or raw.get("api_key")
    user = raw.get("user")
    password = raw.get("password")
    if not endpoint or not (token or (user and password)):
        logger.warning("Incomplete Zilliz configuration, skipping QA store initialisation")
        return None
    collection_name = raw.get("collection_name") or DEFAULT_QA_COLLECTION
    embedding_model = raw.get("embedding_model") or "text-embedding-3-small"
    similarity_top_k = int(raw.get("similarity_top_k") or DEFAULT_TOP_K)
    embedding_dim = int(raw.get("embedding_dim") or DEFAULT_DIMENSION)
    enable_cache = bool(raw.get("enable_cache") or False)
    region = raw.get("region")
    cluster = raw.get("cluster")
    return ZillizConfig(
        endpoint=endpoint,
        token=token,
        user=user,
        password=password,
        collection_name=collection_name,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        similarity_top_k=similarity_top_k,
        enable_cache=enable_cache,
        region=region,
        cluster=cluster,
    )


class QAStore:
    def __init__(self, config: Optional[ZillizConfig] = None) -> None:
        self.config = config or load_config()
        self.collection: Optional[Collection] = None
        self.candidate_collection: Optional[Collection] = None
        if not self.config:
            self.enabled = False
            return
        self.enabled = self._connect_and_prepare()

    def _connect_and_prepare(self) -> bool:
        cfg = self.config
        try:
            logger.info("Connecting to Zilliz endpoint %s", cfg.endpoint)
            connect_args: Dict[str, Any] = {"alias": "default"}
            if cfg.token:
                connect_args.update({"uri": cfg.endpoint, "token": cfg.token, "secure": cfg.secure})
            else:
                connect_args.update({
                    "uri": cfg.endpoint,
                    "user": cfg.user,
                    "password": cfg.password,
                    "secure": cfg.secure,
                })
            connections.connect(**connect_args)
            self.collection = self._ensure_collection(cfg.collection_name)
            self.candidate_collection = self._ensure_candidate_collection(DEFAULT_CANDIDATE_COLLECTION)
            return True
        except Exception as exc:  # pragma: no cover - network operations
            logger.error("Failed to connect to Zilliz: %s", exc)
            self.collection = None
            return False

    def _ensure_collection(self, name: str) -> Collection:
        cfg = self.config
        expected_fields = {
            "qa_id",
            "question",
            "answer",
            "qa_vector",
            "keywords",
        }
        if utility.has_collection(name):
            existing = Collection(name)
            existing_fields = {field.name for field in existing.schema.fields}
            if existing_fields != expected_fields:
                logger.warning("Collection %s schema mismatch (%s), dropping and recreating", name, existing_fields)
                existing.release()
                utility.drop_collection(name)
        if not utility.has_collection(name):
            logger.info("Creating collection %s", name)
            dim = cfg.embedding_dim if cfg else DEFAULT_DIMENSION
            fields = [
                FieldSchema(name="qa_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
                FieldSchema(name="question", dtype=DataType.VARCHAR, max_length=2048),
                FieldSchema(name="answer", dtype=DataType.VARCHAR, max_length=4096),
                FieldSchema(name="qa_vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="keywords", dtype=DataType.JSON),
            ]
            schema = CollectionSchema(fields, description="FAQ store (question-answer embeddings)")
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

    def _ensure_candidate_collection(self, name: str) -> Optional[Collection]:
        cfg = self.config
        expected_fields = {
            "candidate_id",
            "name",
            "job_applied",
            "last_message",
            "resume_vector",
            "resume_text",
            "scores",
            "metadata",
            "updated_at",
        }
        if utility.has_collection(name):
            existing = Collection(name)
            existing_fields = {field.name for field in existing.schema.fields}
            if existing_fields != expected_fields:
                logger.warning("Candidate collection %s schema mismatch (%s); recreating", name, existing_fields)
                existing.release()
                utility.drop_collection(name)
        if not utility.has_collection(name):
            logger.info("Creating candidate collection %s", name)
            dim = cfg.embedding_dim if cfg else DEFAULT_DIMENSION
            fields = [
                FieldSchema(name="candidate_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
                FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="job_applied", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="last_message", dtype=DataType.VARCHAR, max_length=2048),
                FieldSchema(name="resume_vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="resume_text", dtype=DataType.VARCHAR, max_length=8192),
                FieldSchema(name="scores", dtype=DataType.JSON),
                FieldSchema(name="metadata", dtype=DataType.JSON),
                FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64),
            ]
            schema = CollectionSchema(fields, description="Candidate profile embeddings")
            collection = Collection(name=name, schema=schema)
            index_params = {
                "index_type": "AUTOINDEX",
                "metric_type": "IP",
                "params": {}
            }
            collection.create_index(field_name="resume_vector", index_params=index_params)
        collection = Collection(name)
        try:
            collection.load()
        except Exception:
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

    def list_entries(self, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        if not self.enabled or not self.collection:
            return []
        try:
            output_fields = ["qa_id", "question", "answer", "keywords"]
            results = self.collection.query(
                expr='qa_id != ""',
                output_fields=output_fields,
                limit=limit,
                offset=offset,
            )
            return results
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to query QA entries: %s", exc)
            return []

    def delete_entry(self, resume_id: str) -> bool:
        if not self.enabled or not self.collection or not resume_id:
            return False
        try:
            self.collection.delete(f'qa_id == "{resume_id}"')
            self.collection.flush()
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to delete QA entry %s: %s", resume_id, exc)
            return False

    def get_candidate(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled or not self.candidate_collection:
            return None
        try:
            results = self.candidate_collection.query(
                expr=f'candidate_id == "{candidate_id}"',
                output_fields=[
                    "candidate_id",
                    "name",
                    "job_applied",
                    "last_message",
                    "resume_vector",
                    "resume_text",
                    "scores",
                    "metadata",
                    "updated_at",
                ],
                limit=1,
            )
            return results[0] if results else None
        except Exception as exc:
            logger.debug("Candidate lookup failed: %s", exc)
            return None

    # Candidate operations -------------------------------------------------

    def upsert_candidates(self, entries: Iterable[Dict[str, Any]]) -> None:
        if not self.enabled or not self.candidate_collection:
            return
        candidate_ids: List[str] = []
        names: List[str] = []
        jobs: List[str] = []
        messages: List[str] = []
        vectors: List[List[float]] = []
        resumes: List[str] = []
        scores_col: List[Any] = []
        metadata_col: List[Any] = []
        updated_col: List[str] = []

        dim = self.config.embedding_dim if self.config else DEFAULT_DIMENSION

        for entry in entries:
            try:
                cid = str(entry["candidate_id"])
                vec = entry.get("resume_vector") or []
                vec_list = list(vec)
                if not vec_list:
                    vec_list = [0.0] * dim
                candidate_ids.append(cid)
                names.append(entry.get("name", ""))
                jobs.append(entry.get("job_applied", ""))
                messages.append(entry.get("last_message", ""))
                vectors.append(vec_list)
                resumes.append(entry.get("resume_text", ""))
                scores_col.append(entry.get("scores", {}))
                metadata_col.append(entry.get("metadata", {}))
                updated_col.append(entry.get("updated_at", ""))
            except KeyError as err:
                logger.warning("Skipping candidate entry missing field: %s", err)

        if not candidate_ids:
            return

        try:
            self.candidate_collection.delete(
                " or ".join(f'candidate_id == "{cid}"' for cid in candidate_ids)
            )
        except Exception:
            pass

        data = [
            candidate_ids,
            names,
            jobs,
            messages,
            vectors,
            resumes,
            scores_col,
            metadata_col,
            updated_col,
        ]
        self.candidate_collection.insert(data)
        self.candidate_collection.flush()

    def search(self, vector: List[float], top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.enabled or not self.collection:
            return []
        if not vector:
            return []
        limit = top_k or self.config.similarity_top_k
        search_params = {
            "metric_type": "IP",
            "params": {"ef": 32},
        }
        results = self.collection.search(
            data=[vector],
            anns_field="qa_vector",
            limit=limit,
            output_fields=["qa_id", "question", "answer", "keywords"],
            param=search_params,
        )
        hits: List[Dict[str, Any]] = []
        for hit in results[0]:
            hits.append({
                "score": hit.score,
                "qa_id": hit.entity.get("qa_id"),
                "question": hit.entity.get("question"),
                "answer": hit.entity.get("answer"),
                "keywords": hit.entity.get("keywords"),
            })
        return hits


qa_store = QAStore()

__all__ = ["qa_store", "QAStore", "ZillizConfig", "load_config"]
