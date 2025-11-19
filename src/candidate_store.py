"""Zilliz/Milvus-backed QA and candidate interaction store integration."""
from functools import lru_cache
import json
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
        FieldSchema(name="candidate_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True, auto_id=True),
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

def _create_client() -> Optional[MilvusClient]:
    """Create and return a MilvusClient instance, or None if connection fails."""
    try:    
        endpoint = _zilliz_config["endpoint"]
        client = MilvusClient(
            uri=endpoint,
            token=_zilliz_config.get("token", ''),
            user=_zilliz_config["user"],
            password=_zilliz_config["password"],
            secure=endpoint.startswith("https://"),
        )
        logger.debug("Connected to Zilliz endpoint %s", endpoint)
        return client
    except Exception as exc:
        logger.error("Failed to create Zilliz client: %s", exc, exc_info=True)
        return None

# Global client instance
_client: Optional[MilvusClient] = _create_client()

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
            auto_id=True,
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
def get_candidate_by_dict(kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get a candidate by a candidate object"""

    candidate_id = kwargs.get("candidate_id")
    chat_id = kwargs.get("chat_id")
    conversation_id = kwargs.get("conversation_id")
    name = kwargs.get("name")
    names = [name] if name else None
    job_applied = kwargs.get("job_applied")
    identifiers = [candidate_id, chat_id, conversation_id]
    identifiers = [id for id in identifiers if id] or None
    resume_text = kwargs.get("resume_text")
    fields = kwargs.get("fields", _readable_fields)
    
    results = get_candidates(
        identifiers=identifiers, 
        names=names, 
        job_applied=job_applied, 
        limit=1, 
        fields=fields
    )

    if identifiers and not results and resume_text:
        results = search_candidates_by_resume(
            resume_text=resume_text, 
            filter_expr=f'job_applied == "{job_applied}"' if job_applied else None, 
            fields=fields, 
            limit=1
        )
    return results[0] if results else {}

def get_candidates(
    identifiers: Optional[List[str]] = None,
    names: Optional[List[str]] = None,
    job_applied: Optional[str] = None,
    limit: Optional[int] = None,
    fields: Optional[List[str]] = _readable_fields,
) -> List[Dict[str, Any]]:
    """Query candidates by identifiers (chat_id/candidate_id/conversation_id) or by names/job_applied.
    
    Args:
        identifiers: List of chat_id, candidate_id, or conversation_id values
        names: List of candidate names (requires job_applied)
        job_applied: Single job_applied value (required with names)
        resume_text: Single resume_text value (required with names)
        limit: Maximum number of results to return
        fields: Fields to return (defaults to _readable_fields)
        
    Returns:
        List[Dict[str, Any]]: List of candidate records
    """
    
    # Remove None from identifiers, names, and job_applied
    identifiers = [id for id in identifiers if id] or None if identifiers else None
    names = [name.strip() for name in names if (name.strip())] or None if names else None
    job_applied = job_applied.strip() or None if job_applied else None
    
    if identifiers:
        quoted_ids = [f"'{id}'" for id in identifiers]
        ids_str = ', '.join(quoted_ids)
        expr_1 = f"chat_id in [{ids_str}] or candidate_id in [{ids_str}] or conversation_id in [{ids_str}]"
        query_limit = (limit or len(identifiers)) * 2
    else:
        expr_1 = None
        
    if names and job_applied:
        quoted_names = [f"'{n}'" for n in names]
        names_str = ', '.join(quoted_names)
        expr_2 = f"name in [{names_str}] and job_applied == '{job_applied}'"
        query_limit = (limit or len(names)) * 2
    else:
        expr_2 = None

    if expr_1 and expr_2:
        filter_expr = f'({expr_1}) or ({expr_2})'
    else:
        filter_expr = expr_1 or expr_2
    
    
    # Execute query
    if filter_expr:
        results = _client.query(
            collection_name=_collection_name,
            filter=filter_expr,
            output_fields=fields,
            limit=query_limit,
            output_fields_order='updated_at DESC',
        )
    else:
        logger.error("No valid identifiers or resume_text provided, returning empty list")
        return []

    # Remove empty fields
    candidates = [{k: v for k, v in result.items() if v or v == 0} for result in results]

    # Sort by updated_at in descending order (most recent first)
    candidates.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    # Apply the original limit after sorting
    return candidates[:limit]
        

truncate_field = lambda field, length: field.encode('utf-8')[:length].decode('utf-8', errors='ignore')

def upsert_candidate(**kwargs) -> Optional[str]:
    """Insert or update candidate information.
    
    Automatically generates resume_vector embedding if not provided and resume_text is available.
    Truncates resume_text and full_resume to field max_length.
    
    Args:
        **kwargs: Candidate data (chat_id, name, resume_text, job_applied, etc.)
        
    Returns:
        str: candidate_id if successful, None otherwise
    """
    # Prepare data
    chat_id = kwargs.get("chat_id")
    conversation_id = kwargs.get("conversation_id")
    stored_candidate = get_candidate_by_dict(kwargs)
    candidate_id = stored_candidate.get('candidate_id') if stored_candidate else None
    if candidate_id and candidate_id != kwargs.get("candidate_id"):
        logger.warning(f"candidate_id mismatch: {kwargs.get('candidate_id')} -> {candidate_id}")
        kwargs['candidate_id'] = candidate_id
    
    # fixing fields types
    for k, v in kwargs.items():
        if not (v or v == 0) or not k in _all_fields:
            continue
        field = next((f for f in get_collection_schema() if f.name == k), None)
        if field.dtype == DataType.VARCHAR:
            kwargs[k] = truncate_field(v, field.max_length)
        elif field.dtype == DataType.BOOL:
            kwargs[k] = True if v==1 or v.lower() in ['true', '1'] else False
    
    # Parse JSON fields if strings
    analysis = kwargs.get("analysis")
    if analysis and isinstance(analysis, str):
        kwargs['analysis'] = json.loads(analysis)
    metadata = kwargs.get("metadata")
    if metadata and isinstance(metadata, str):
        kwargs['metadata'] = json.loads(metadata)
    
    kwargs['updated_at'] = datetime.now().isoformat()
    
    # Filter to only valid fields
    kwargs = {k: v.strip() if isinstance(v, str) else v for k, v in kwargs.items() if(k in _all_fields and (v or v == 0))}
    
    # Generate embedding if needed
    resume_text = kwargs.get("resume_text")
    resume_vector = kwargs.get("resume_vector")
    
    # For updates with candidate_id, let it fail if invalid and recover
    if not resume_vector and resume_text:
        # Generate embedding from resume_text
        kwargs["resume_vector"] = get_embedding(resume_text)
    
    # Insert if no candidate_id
    if not candidate_id:
        logger.debug(f'upsert_candidate: no candidate_id, inserting new candidate: {kwargs.get("name")}');
        kwargs["resume_vector"] = [0.0] * _zilliz_config["embedding_dim"] if not resume_vector else resume_vector
        results = _client.insert(collection_name=_collection_name, data=kwargs)
        return results['ids'][0]

    # Update if candidate_id exists
    try:
        result = _client.upsert(
            collection_name=_collection_name,
            data=[kwargs],
            partial_update=bool(candidate_id),  # Partial update if candidate_id exists
        )
        return result['ids'][0]
    except MilvusException as exc:
        error_code, error_message = exc.code, exc.message
        if error_code == 1100 and "resume_vector" in error_message.lower():
            # This happens when partial_update=True but candidate_id is invalid
            # and resume_vector is missing. Try to find the actual record.
            logger.warning("Upsert failed with missing resume_vector, attempting to find existing record...")
            # Try to find existing record by chat_id or conversation_id
            existing_candidate_id = get_candidate_by_dict(kwargs).get('candidate_id')
            if existing_candidate_id:
                logger.info(f"Found existing record with candidate_id: {existing_candidate_id}")
                # Update kwargs with correct candidate_id and resume_vector
                kwargs["candidate_id"] = existing_candidate_id
                result = upsert_candidate(**kwargs)
                # Return the existing candidate_id we found (not the result which might be a new ID)
                return result
            else:
                logger.error(f"No existing record found with: {kwargs}")
        logger.exception("Failed to upsert candidate: %s", exc)
        raise exc


def search_candidates_by_resume(
    resume_text: str,
    filter_expr: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    similarity_threshold: float = 0.9,
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
            limit=limit or _zilliz_config["similarity_top_k"],
            output_fields=fields or _readable_fields,
            search_params={"metric_type": "IP", "params": {}},
        )
        
        # Filter by similarity threshold
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
    "get_candidates",
    "upsert_candidate",
    "search_candidates_by_resume",
    "get_candidate_count",
]
