"""Zilliz/Milvus-backed QA and candidate interaction store integration."""
from difflib import SequenceMatcher
from functools import lru_cache
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pymilvus import MilvusClient, DataType, FieldSchema
from pymilvus.exceptions import MilvusException
from tenacity import retry, stop_after_attempt, wait_exponential
from .global_logger import logger
from .config import get_zilliz_config

# ------------------------------------------------------------------
# Schema Definition
# ------------------------------------------------------------------

_zilliz_config = get_zilliz_config()
_max_length = _zilliz_config["max_length"]
_collection_name = _zilliz_config["candidate_collection_name"]

def get_collection_schema() -> list[FieldSchema]:
    """Get the collection schema definition.
    
    Returns the schema as a list of FieldSchema objects.
    This serves as both documentation and a reference for field definitions.
    """
    fields: list[FieldSchema] = [
        FieldSchema(name="candidate_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
        FieldSchema(name="resume_vector", dtype=DataType.FLOAT_VECTOR, dim=_zilliz_config["embedding_dim"]),
        FieldSchema(name="chat_id", dtype=DataType.VARCHAR, max_length=100, nullable=True),
        FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=200, nullable=True),
        FieldSchema(name="job_applied", dtype=DataType.VARCHAR, max_length=128, nullable=True),
        FieldSchema(name="last_message", dtype=DataType.VARCHAR, max_length=2048, nullable=True),
        FieldSchema(name="resume_text", dtype=DataType.VARCHAR, max_length=_max_length, nullable=True),
        FieldSchema(name="metadata", dtype=DataType.JSON, nullable=True),
        FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64, nullable=True),
        FieldSchema(name="analysis", dtype=DataType.JSON, nullable=True),
        FieldSchema(name="stage", dtype=DataType.VARCHAR, max_length=20, nullable=True),
        FieldSchema(name="full_resume", dtype=DataType.VARCHAR, max_length=_max_length, nullable=True),
        FieldSchema(name="conversation_id", dtype=DataType.VARCHAR, max_length=100, nullable=True),
        FieldSchema(name="generated_message", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
        FieldSchema(name="notified", dtype=DataType.BOOL, nullable=True),
    ]
    return fields
# Define field names for the collection
_all_fields = [f.name for f in get_collection_schema()]

# List of all field names except "resume_vector"
_readable_fields = [f.name for f in get_collection_schema() if f.dtype != DataType.FLOAT_VECTOR]

# ------------------------------------------------------------------
# MilvusClient Connection
# ------------------------------------------------------------------

def _create_client() -> MilvusClient:
    """Create and return a MilvusClient instance.
    
    Raises:
        RuntimeError: If connection fails, the application should not start.
    """
    endpoint = _zilliz_config["endpoint"]
    client = MilvusClient(
        uri=endpoint,
        token=_zilliz_config.get("token", ''),
        user=_zilliz_config["user"],
        password=_zilliz_config["password"],
        secure=endpoint.startswith("https://"),
    )
    logger.info("✅ Connected to Zilliz endpoint: %s", endpoint)
    return client

# Global client instance - raises RuntimeError if connection fails
try:
    _client: MilvusClient = _create_client()
except Exception as exc:
    logger.critical("❌ 初始化Zilliz客户端失败. 应用无法启动: %s", exc, exc_info=True)
    raise RuntimeError(f"Zilliz 数据库启动失败: {exc}") from exc

# ------------------------------------------------------------------
# Embedding Generation
# ------------------------------------------------------------------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
@lru_cache(maxsize=1000)
def get_embedding(text: str) -> Optional[List[float]]:
    """Generate embedding for text using OpenAI.
    
    Args:
        text: Text to generate embedding for (truncated to 4096 chars)
        
    Returns:
        List of floats representing the embedding vector, or None if failed
    """
    try:
        from .assistant_actions import _openai_client
        response = _openai_client.embeddings.create(
            model=_zilliz_config["embedding_model"],
            input=text[:4096],
            dimensions=_zilliz_config["embedding_dim"],
        )
        return response.data[0].embedding
    except Exception as exc:
        logger.exception("Failed to generate embedding: %s", exc)
        return None

# ------------------------------------------------------------------
# Collection Management
# ------------------------------------------------------------------

def create_collection(collection_name: Optional[str] = None) -> bool:
    """Create the candidates collection with the defined schema.
    
    Args:
        collection_name: Name of collection to create (defaults to candidate collection name from config)
        
    Returns:
        bool: True if successful, False otherwise
    """
    collection_name = collection_name or _collection_name
    
    try:
        # Check if collection already exists
        if _client.has_collection(collection_name=collection_name):
            logger.warning(f"Collection {collection_name} already exists")
            return False
        
        logger.info(f"Creating collection {collection_name}...")
        
        # Create collection with schema
        _client.create_collection(
            collection_name=collection_name,
            dimension=_zilliz_config["embedding_dim"],
            primary_field_name="candidate_id",
            vector_field_name="resume_vector",
            id_type="string",
            auto_id=False,
            max_length=64,
            metric_type="IP",
            schema=get_collection_schema(),
        )
        
        # Create scalar field indexes for faster queries
        logger.info("Creating scalar indexes...")
        _client.create_index(collection_name=collection_name, field_name="chat_id", index_type="INVERTED")
        _client.create_index(collection_name=collection_name, field_name="conversation_id", index_type="INVERTED")
        _client.create_index(collection_name=collection_name, field_name="stage", index_type="INVERTED")
        
        logger.info(f"✅ Collection {collection_name} created successfully")
        return True
        
    except Exception as exc:
        logger.exception(f"Failed to create collection {collection_name}: %s", exc)
        return False

# ------------------------------------------------------------------
# Candidate Operations
# ------------------------------------------------------------------
def get_candidate_by_dict(kwargs: Dict[str, Any], strict: bool = True) -> Optional[Dict[str, Any]]:
    """Get a candidate by a candidate object"""

    candidate_id = kwargs.get("candidate_id")
    chat_id = kwargs.get("chat_id")
    conversation_id = kwargs.get("conversation_id")
    name = kwargs.get("name")
    job_applied = kwargs.get("job_applied")
    resume_text = kwargs.get("resume_text")
    fields = kwargs.get("fields", _readable_fields)
    last_message = kwargs.get("last_message", '')
    has_id = candidate_id or chat_id or conversation_id
    
    results = search_candidates_advanced(
        candidate_ids=[candidate_id] if candidate_id else None,
        chat_ids=[chat_id] if chat_id else None,
        conversation_ids=[conversation_id] if conversation_id else None,
        names=[name] if not has_id else None,
        job_applied=job_applied,
        limit=1,
        fields=fields,
        strict=strict,
    )
    stored_candidate = results[0] if results else {}
    # stored_last_message = stored_candidate.get("last_message", '')
    # similarity = SequenceMatcher(a=last_message, b=stored_last_message).ratio()
    # if stored_candidate and similarity < 0.8:
    #     logger.warning(f"last_message similarity mismatch: {similarity} for {kwargs} and {stored_candidate}")
    #     results = []

    if not results and resume_text:
        results = search_candidates_by_resume(
            resume_text=resume_text, 
            filter_expr=f'name == "{name}" and job_applied == "{job_applied}"' if name and job_applied else None, 
            fields=fields, 
            limit=1
        )
        stored_candidate = results[0] if results else {}
    return stored_candidate

def search_candidates_advanced(
    candidate_ids: Optional[List[str]] = [],
    chat_ids: Optional[List[str]] = [],
    conversation_ids: Optional[List[str]] = [],
    names: Optional[List[str]] = [],
    job_applied: Optional[str] = None,
    stage: Optional[str] = None,
    notified: Optional[bool] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
    resume_contains: Optional[str] = None,
    semantic_query: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: int = 100,
    sort_by: str = "updated_at",
    sort_direction: str = "desc",
    fields: Optional[List[str]] = None,
    strict = True
) -> List[Dict[str, Any]]:
    """
    Search candidates in the store with advanced, multi-field queries.

    Supports filtering by one or more of:
        - Identifiers: candidate_ids, chat_ids, conversation_ids, names
        - Candidate/job metadata: job_applied, stage, notified status
        - Update window: updated_from, updated_to (based on updated_at)
        - Resume keyword: resume_contains matches `resume_text` or `full_resume`
        - Semantic score: min_score (matches analysis["overall"])
        - Custom result fields (default: _readable_fields)
        - Strict/relaxed combining of identifier conditions (strict = AND, else OR)
        - Sorting and result count limit

    Args:
        candidate_ids: List of candidate_id values to filter by.
        chat_ids: List of chat_id values to filter by.
        conversation_ids: List of conversation_id values to filter by.
        names: List of candidate names to filter by.
        job_applied: String job position filter.
        stage: Candidate stage to filter (e.g. 'CHAT', 'PASS').
        notified: Only return candidates that have been notified if True/False.
        updated_from: Start ISO date string for updated_at.
        updated_to: End ISO date string for updated_at.
        resume_contains: Keyword to search for in resumes.
        semantic_query: (Not implemented) Reserved for semantic search phrase.
        min_score: Minimum overall analysis score for candidate.
        limit: Maximum number of results (default 100).
        sort_by: Field to sort by (default 'updated_at').
        sort_direction: 'asc' or 'desc' (default 'desc').
        fields: List of result fields to return. Uses `_readable_fields` if None.
        strict: If True (default), combine identifier clauses with AND. If False, use OR.

    Returns:
        List of candidate records matching all supplied filters, up to `limit`.
    """
    _quote = lambda value: f"'{value.strip()}'" if value else ''
    _build_in_clause = lambda field, values: f"{field} in [{', '.join(_quote(v) for v in values if v and v.strip())}]" if values else None

    fields = fields or _readable_fields

    identifiers = []
    identifiers.append(_build_in_clause("candidate_id", candidate_ids))
    identifiers.append(_build_in_clause("chat_id", chat_ids))
    identifiers.append(_build_in_clause("conversation_id", conversation_ids))
    identifiers.append(_build_in_clause("name", names))
    conditions = []
    if job_applied:
        conditions.append(f"job_applied == {_quote(job_applied)}")
    if stage:
        conditions.append(f"stage == {_quote(stage.upper())}")
    if isinstance(notified, bool):
        conditions.append(f"notified == {notified}")
    if updated_from:
        conditions.append(f"updated_at >= {_quote(updated_from)}")
    if updated_to:
        conditions.append(f"updated_at <= {_quote(updated_to)}")
    if resume_contains:
        # Use Milvus like operator to search in both resume_text and full_resume
        # Note: like is case-sensitive in Milvus
        keyword = resume_contains.strip().replace("'", "\\'")
        conditions.append(f"(resume_text like '%{keyword}%') or (full_resume like '%{keyword}%')")
    if min_score is not None:
        # Use bracket notation to filter JSON field: analysis["overall"] >= min_score
        identifiers.append(f'analysis["overall"] >= {min_score}')

    filter_expr = f" {'and' if strict else 'or'} ".join([c for c in identifiers if c])
    if conditions:
        filter_expr = f" {filter_expr} and {'and'.join(conditions)}" if filter_expr else ' and '.join(conditions)

    sortable_fields = {
        "updated_at",
        "name",
        "job_applied",
        "stage",
        "notified",
        "candidate_id",
        "chat_id",
        "conversation_id",
    }
    sort_by_normalized = sort_by if sort_by in sortable_fields else "updated_at"
    sort_dir = "DESC" if sort_direction.lower() != "asc" else "ASC"
    order_clause = f"{sort_by_normalized} {sort_dir}"

    try:
        # Cap the limit to stay within Milvus's max query result window of 16384
        # The function multiplies limit by 3, so we cap the effective limit
        effective_limit = limit * 3 if limit else None
        if effective_limit and effective_limit > 16384:
            effective_limit = 16384
        
        if semantic_query:
            results = search_candidates_by_resume(
                resume_text=semantic_query,
                filter_expr=filter_expr,
                fields=fields,
                limit=effective_limit,
                similarity_threshold=0.5,
            )
        else:
            results = _client.query(
                collection_name=_collection_name,
                filter=filter_expr,
                output_fields=fields,
                limit=effective_limit,
                output_fields_order=order_clause,
            )
        
        candidates = [{k: v for k, v in result.items() if v or v == 0} for result in results or []]
        
        for candidate in candidates:
            candidate["score"] = candidate.get("analysis", {}).get("overall")

        reverse = sort_direction.lower() != "asc"
        candidates.sort(key=lambda c: c.get(sort_by_normalized) or "", reverse=reverse)

        return candidates[:limit] if limit else candidates
    except Exception as exc:
        logger.exception("Failed advanced candidate search: %s", exc)
        return []
        

truncate_field = lambda string, length: string.encode('utf-8')[:length].decode('utf-8', errors='ignore').strip()

def upsert_candidate(**candidate) -> Optional[str]:
    """Insert or update candidate information.
    
    Automatically generates resume_vector embedding if not provided and resume_text is available.
    Truncates resume_text and full_resume to field max_length.
    
    Args:
        **kwargs: Candidate data (chat_id, name, resume_text, job_applied, etc.)
        
    Returns:
        str: candidate_id if successful, None otherwise
    """
    # prevent kwargs only has `candidate_id` field
    if not candidate or (len(candidate) == 1 and 'candidate_id' in candidate):
        logger.warning(f"upsert: candidate_id provided but no updates: {candidate}")
        return candidate.get("candidate_id")
    
    # Get candidate_id from kwargs if provided
    candidate_id = candidate.get("candidate_id")
    stored_candidate = None
    
    # Only check for existing candidate if candidate_id is not provided
    # If candidate_id is provided, we use it directly without checking
    if not candidate_id:
        stored_candidate = get_candidate_by_dict(candidate)
        candidate_id = stored_candidate.get('candidate_id') if stored_candidate else None
        candidate['candidate_id'] = candidate_id
    
    # Merge metadata if updating existing candidate and metadata is being updated
    if candidate_id and stored_candidate and "metadata" in candidate:
        existing_metadata = stored_candidate.get("metadata", {}) or {}
        new_metadata = candidate.get("metadata", {}) or {}
        existing_metadata.update(new_metadata) 
        candidate["metadata"] = existing_metadata
    
    # fixing fields types and filtering only valid fields
    candidate['updated_at'] = datetime.now().isoformat()
    candidate = {k: v for k, v in candidate.items() if k in _all_fields and (v or v == 0)}
    for k, v in candidate.items():
        field = next((f for f in get_collection_schema() if f.name == k), None)
        if field.dtype == DataType.VARCHAR:
            candidate[k] = truncate_field(str(v), field.max_length)
        elif field.dtype == DataType.BOOL and isinstance(v, str):
            candidate[k] = True if v.lower() in ['true', 'yes', '1'] else False
        elif field.dtype == DataType.JSON and isinstance(v, str):
            candidate[k] = json.loads(v)
    
    
    # Generate embedding if needed
    resume_text = candidate.get("resume_text")
    resume_vector = candidate.get("resume_vector")
    if not resume_vector and resume_text:
        # Generate embedding from resume_text
        candidate["resume_vector"] = get_embedding(resume_text)
    
    # Determine insert vs update:
    if candidate_id:
        _client.upsert(
            collection_name=_collection_name,
            data=[candidate],
            partial_update=True,  # Partial update for existing records
        )
        return candidate_id
    else:
        # Generate a unique candidate_id using UUID
        candidate_id = str(uuid.uuid4())
        candidate['candidate_id'] = candidate_id
        logger.debug(f'upsert_candidate: generated candidate_id {candidate_id} for new candidate: {candidate.get("name")}');
        if not candidate.get("resume_vector"): # generate embedding if not provided
            candidate["resume_vector"] = [0.0] * _zilliz_config["embedding_dim"]
        _client.insert(collection_name=_collection_name, data=[candidate])
        return candidate_id


def search_candidates_by_resume(
    resume_text: str,
    filter_expr: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    similarity_threshold: float = 0.95,
) -> Optional[Dict[str, Any]]:
    """Search for similar candidates by resume text.
    
    Args:
        resume_text: Resume text to search for
        limit: Maximum number of results (defaults to similarity_top_k from config)
        similarity_threshold: Minimum similarity score (default 0.9)
        
    Returns:
        Dict with candidate data if found, None otherwise
    """
        
    resume_vector = get_embedding(resume_text)
    
    try:
        results = _client.search(
            collection_name=_collection_name,
            data=[resume_vector],
            filter=filter_expr,
            limit=limit*3 or _zilliz_config["similarity_top_k"], # set a larger limit to ensure we get enough candidates
            output_fields=fields or _readable_fields,
            search_params={"metric_type": "IP"}, # use cosine to be guaranteed that the result is normalized to 0-1
        )
        
        # Filter by similarity threshold
        # candidates.sort(key=lambda x: x['distance'], reverse=True)
        results_str = '\n'.join([f'{r["entity"]["candidate_id"]}({r["entity"]["name"]}): {r["distance"]}' for r in results[0]])
        logger.debug(f"search_candidates_by_resume: results: \n{results_str}")
        candidates = [r['entity'] for r in results[0] if  r['distance'] > similarity_threshold]
        return candidates
    except Exception as exc:
        logger.exception("Failed to search candidates: %s", exc)
        return []

def get_candidate_count() -> int:
    """Get the number of candidates in the collection."""
    return _client.get_collection_stats(collection_name=_collection_name)['row_count']

__all__ = [
    "get_collection_schema",
    "get_embedding",
    "create_collection",
    "search_candidates_advanced",
    "upsert_candidate",
    "search_candidates_by_resume",
    "get_candidate_count",
]
