"""Zilliz/Milvus-backed QA and candidate interaction store integration."""
from __future__ import annotations

from functools import lru_cache
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from pymilvus import MilvusClient, DataType, FieldSchema
from pymilvus.exceptions import MilvusException
from retry import retry
from .global_logger import logger
from .config import settings

# ------------------------------------------------------------------
# Schema Definition
# ------------------------------------------------------------------

def get_collection_schema() -> list[FieldSchema]:
    """Get the collection schema definition.
    
    Returns the schema as a list of FieldSchema objects.
    This serves as both documentation and a reference for field definitions.
    """
    fields: list[FieldSchema] = [
        FieldSchema(name="candidate_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True, auto_id=True),
        FieldSchema(name="resume_vector", dtype=DataType.FLOAT_VECTOR, dim=settings.ZILLIZ_EMBEDDING_DIM),
        FieldSchema(name="chat_id", dtype=DataType.VARCHAR, max_length=100, nullable=True),
        FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=200, nullable=True),
        FieldSchema(name="job_applied", dtype=DataType.VARCHAR, max_length=128, nullable=True),
        FieldSchema(name="last_message", dtype=DataType.VARCHAR, max_length=2048, nullable=True),
        FieldSchema(name="resume_text", dtype=DataType.VARCHAR, max_length=25000, nullable=True),
        FieldSchema(name="metadata", dtype=DataType.JSON, nullable=True),
        FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64, nullable=True),
        FieldSchema(name="analysis", dtype=DataType.JSON, nullable=True),
        FieldSchema(name="stage", dtype=DataType.VARCHAR, max_length=20, nullable=True),
        FieldSchema(name="full_resume", dtype=DataType.VARCHAR, max_length=25000, nullable=True),
        FieldSchema(name="conversation_id", dtype=DataType.VARCHAR, max_length=100, nullable=True),
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
    """Create and return a MilvusClient instance."""
        # Check if token is available (optional attribute)
    token = getattr(settings, 'ZILLIZ_TOKEN', None)
    
    if token:
        client = MilvusClient(
            uri=settings.ZILLIZ_ENDPOINT,
            token=token,
            secure=settings.ZILLIZ_ENDPOINT.startswith("https://"),
        )
    else:
        client = MilvusClient(
            uri=settings.ZILLIZ_ENDPOINT,
            user=settings.ZILLIZ_USER,
            password=settings.ZILLIZ_PASSWORD,
            secure=settings.ZILLIZ_ENDPOINT.startswith("https://"),
        )
    logger.debug("Connected to Zilliz endpoint %s", settings.ZILLIZ_ENDPOINT)
    return client

# Global client instance
_client: Optional[MilvusClient] = _create_client()
_collection_name = settings.ZILLIZ_COLLECTION_NAME

# ------------------------------------------------------------------
# Embedding Generation
# ------------------------------------------------------------------
@retry(tries=3, delay=1, backoff=2)
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
            model=settings.ZILLIZ_EMBEDDING_MODEL,
            input=text[:4096],
            dimensions=settings.ZILLIZ_EMBEDDING_DIM,
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
        collection_name: Name of collection to create (defaults to settings.ZILLIZ_COLLECTION_NAME)
        
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
            dimension=settings.ZILLIZ_EMBEDDING_DIM,
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
def get_candidate_id_by_dict(kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get a candidate by a candidate object"""

    candidate_id = kwargs.get("candidate_id")
    chat_id = kwargs.get("chat_id")
    conversation_id = kwargs.get("conversation_id")
    name = kwargs.get("name")
    names = [name] if name else None
    job_applied = kwargs.get("job_applied")
    identifiers = [candidate_id, chat_id, conversation_id]
    
    results = get_candidates(
        identifiers=identifiers, 
        names=names, 
        job_applied=job_applied, 
        limit=1, 
        fields=['candidate_id']
    )
    return results[0].get('candidate_id') if results else None

def get_candidates(
    identifiers: Optional[List[str]] = None,
    names: Optional[List[str]] = None,
    job_applied: Optional[str] = None,
    limit: Optional[int] = None,
    fields: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Query candidates by identifiers (chat_id/candidate_id/conversation_id) or by names/job_applied.
    
    Args:
        identifiers: List of chat_id, candidate_id, or conversation_id values
        names: List of candidate names (requires job_applied)
        job_applied: Single job_applied value (required with names)
        limit: Maximum number of results to return
        fields: Fields to return (defaults to _readable_fields)
        
    Returns:
        List[Dict[str, Any]]: List of candidate records
    """
    if fields is None:
        fields = _readable_fields
    
    # Remove None from identifiers, names, and job_applied
    if identifiers:
        identifiers = [id for id in identifiers if id] or None
    if names:
        names = [name.strip() for name in names if (name and name.strip())] or None
    if job_applied:
        job_applied = job_applied.strip() or None
    
    # Build query expression
    query_limit = limit or 100
    
    if identifiers:
        quoted_ids = [f"'{id}'" for id in identifiers]
        ids_str = ', '.join(quoted_ids)
        expr_1 = f"chat_id in [{ids_str}] or candidate_id in [{ids_str}] or conversation_id in [{ids_str}]"
        query_limit = limit or len(identifiers)
    else:
        expr_1 = None
        
    if names and job_applied:
        quoted_names = [f"'{n}'" for n in names]
        names_str = ', '.join(quoted_names)
        expr_2 = f"name in [{names_str}] and job_applied == '{job_applied}'"
        query_limit = limit or len(names)
    else:
        expr_2 = None

    if expr_1 and expr_2:
        filter_expr = f'({expr_1}) or ({expr_2})'
    else:
        filter_expr = expr_1 or expr_2
    
    if not filter_expr:
        logger.warning("No filter expression provided")
        return []
    
    # Execute query
    try:
        results = _client.query(
            collection_name=_collection_name,
            filter=filter_expr,
            output_fields=fields,
            limit=query_limit,
        )
        # Remove empty fields
        return [{k: v for k, v in result.items() if v} for result in results]
    except Exception as exc:
        logger.exception("Failed to query candidates: %s", exc)
        return []


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
    candidate_id = get_candidate_id_by_dict(kwargs)
    if candidate_id != kwargs.get("candidate_id"):
        kwargs['candidate_id'] = candidate_id
    
    # Truncate long fields
    if kwargs.get("resume_text"):
        kwargs['resume_text'] = kwargs['resume_text'][:25000]
    if kwargs.get("full_resume"):
        kwargs['full_resume'] = kwargs['full_resume'][:25000]
    
    # Parse JSON fields if strings
    analysis = kwargs.get("analysis")
    if analysis and isinstance(analysis, str):
        kwargs['analysis'] = json.loads(analysis)
    metadata = kwargs.get("metadata")
    if metadata and isinstance(metadata, str):
        kwargs['metadata'] = json.loads(metadata)
    
    kwargs['updated_at'] = datetime.now().isoformat()
    
    # Filter to only valid fields
    kwargs = {k: v.strip() if isinstance(v, str) else v for k, v in kwargs.items() if k in _all_fields and (v or v == 0)}
    
    # Generate embedding if needed
    resume_text = kwargs.get("resume_text")
    resume_vector = kwargs.get("resume_vector")
    
    # Ensure resume_vector is present for new candidates (no candidate_id)
    # For updates with candidate_id, let it fail if invalid and recover
    if not resume_vector and resume_text:
        # Generate embedding from resume_text
        kwargs["resume_vector"] = get_embedding(resume_text)
    
    # Insert if no candidate_id
    if not candidate_id:
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
        # Check if it's the "resume_vector missing" error (code 1100)
        error_code = exc.code
        error_message = exc.message
        
        if error_code == 1100 and "resume_vector" in error_message.lower():
            # This happens when partial_update=True but candidate_id is invalid
            # and resume_vector is missing. Try to find the actual record.
            logger.warning("Upsert failed with missing resume_vector, attempting to find existing record...")
            
            # Try to find existing record by chat_id or conversation_id
            search_identifiers = []
            if chat_id:
                search_identifiers.append(chat_id)
            if conversation_id:
                search_identifiers.append(conversation_id)
            name = kwargs.get("name")
            job_applied = kwargs.get("job_applied")
            
            if search_identifiers or name:
                existing = get_candidates(identifiers=search_identifiers, names=[name], job_applied=job_applied, limit=1, fields=_all_fields)
                
                if existing:
                    existing_record = existing[0]
                    existing_candidate_id = existing_record.get("candidate_id")
                    
                    if existing_candidate_id:
                        logger.info(f"Found existing record with candidate_id: {existing_candidate_id}")
                        
                        # Update kwargs with correct candidate_id and resume_vector
                        kwargs["candidate_id"] = existing_candidate_id
                        # Recursively call upsert_candidate with corrected kwargs
                        logger.info("Retrying upsert candidate with correct candidate_id...")
                        result = upsert_candidate(**kwargs)
                        # Return the existing candidate_id we found (not the result which might be a new ID)
                        return result
                    else:
                        logger.warning("Found existing record but no candidate_id")
                else:
                    logger.warning(f"No existing record found with identifiers: {search_identifiers}")
            else:
                logger.warning("No chat_id or conversation_id available to search for existing record")
        
        # If not code 1100 or retry failed, log and return None
        logger.exception("Failed to upsert candidate: %s", exc)
        raise exc


def search_candidates_by_resume(
    resume_text: str,
    limit: Optional[int] = None,
    similarity_threshold: float = 0.9,
) -> Optional[Dict[str, Any]]:
    """Search for similar candidates by resume text.
    
    Args:
        resume_text: Resume text to search for
        limit: Maximum number of results (defaults to settings.ZILLIZ_SIMILARITY_TOP_K)
        similarity_threshold: Minimum similarity score (default 0.9)
        
    Returns:
        Dict with candidate data if found, None otherwise
    """
    if not _client:
        return None
    
    limit = limit or settings.ZILLIZ_SIMILARITY_TOP_K
    
    resume_vector = get_embedding(resume_text)
    
    try:
        results = _client.search(
            collection_name=_collection_name,
            data=[resume_vector],
            filter="",
            limit=limit,
            output_fields=_readable_fields,
            search_params={"metric_type": "IP", "params": {}},
        )
        
        # Filter by similarity threshold
        if results and len(results) > 0:
            for result in results[0]:
                if result.get('distance', 0) > similarity_threshold:
                    return result
        
        return None
    except Exception as exc:
        logger.exception("Failed to search candidates: %s", exc)
        return None

def get_candidate_count() -> int:
    """Get the number of candidates in the collection."""
    return _client.count(collection_name=_collection_name)

__all__ = [
    "get_collection_schema",
    "get_embedding",
    "create_collection",
    "get_candidates",
    "upsert_candidate",
    "search_candidates_by_resume",
    "get_candidate_count",
]
