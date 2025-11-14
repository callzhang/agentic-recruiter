"""Zilliz/Milvus-backed job profile store integration."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pymilvus import DataType, FieldSchema
# Use the same client instance as candidate_store
from src.candidate_store import _client
from .global_logger import logger
from .config import get_zilliz_config
_job_store_config = get_zilliz_config()
# ------------------------------------------------------------------
# Schema Definition
# ------------------------------------------------------------------

def get_job_collection_schema() -> list[FieldSchema]:
    """Get the job collection schema definition.
    
    Returns the schema as a list of FieldSchema objects.
    """
    fields: list[FieldSchema] = [
        # Primary key
        FieldSchema(name="job_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
        
        # Job content fields
        FieldSchema(name="position", dtype=DataType.VARCHAR, max_length=200),
        FieldSchema(name="background", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
        FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
        FieldSchema(name="responsibilities", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
        FieldSchema(name="requirements", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
        FieldSchema(name="target_profile", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
        FieldSchema(name="keywords", dtype=DataType.JSON, nullable=True),
        FieldSchema(name="drill_down_questions", dtype=DataType.VARCHAR, max_length=65000, nullable=True),
        
        # Candidate search filters (stored as JSON)
        FieldSchema(name="candidate_filters", dtype=DataType.JSON, nullable=True),
        
        # Vector field for future semantic search
        FieldSchema(name="job_embedding", dtype=DataType.FLOAT_VECTOR, dim=_job_store_config["embedding_dim"]),
        
        # Timestamps
        FieldSchema(name="created_at", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64),
    ]
    return fields

# Define field names for the collection
_all_fields = [f.name for f in get_job_collection_schema()]
_readable_fields = [f.name for f in get_job_collection_schema() if f.dtype != DataType.FLOAT_VECTOR]
_collection_name = _job_store_config["job_collection_name"]


# ------------------------------------------------------------------
# Collection Management
# ------------------------------------------------------------------

def create_job_collection(collection_name: Optional[str] = None) -> bool:
    """Create the jobs collection with the defined schema.
    
    Args:
        collection_name: Name of collection to create (defaults to "CN_jobs")
        
    Returns:
        bool: True if successful, False otherwise
    """
    collection_name = collection_name or _collection_name
    
    if not _client:
        logger.error("Zilliz client not available")
        return False
    
    try:
        # Check if collection already exists
        if _client.has_collection(collection_name=collection_name):
            logger.warning(f"Collection {collection_name} already exists")
            return False
        
        logger.info(f"Creating collection {collection_name}...")
        
        # Create collection with schema
        _client.create_collection(
            collection_name=collection_name,
            dimension=_job_store_config["embedding_dim"],
            primary_field_name="job_id",
            vector_field_name="job_embedding",
            id_type="string",
            auto_id=False,  # job_id is provided, not auto-generated
            max_length=64,
            metric_type="IP",
            schema=get_job_collection_schema(),
        )
        
        # Create scalar field indexes for faster queries
        logger.info("Creating scalar indexes...")
        _client.create_index(collection_name=collection_name, field_name="job_id", index_type="INVERTED")
        _client.create_index(collection_name=collection_name, field_name="position", index_type="INVERTED")
        
        logger.info(f"✅ Collection {collection_name} created successfully")
        return True
        
    except Exception as exc:
        logger.exception(f"Failed to create collection {collection_name}: %s", exc)
        return False

# ------------------------------------------------------------------
# Job Operations
# ------------------------------------------------------------------

def get_all_jobs() -> List[Dict[str, Any]]:
    """Get all jobs from the collection."""
    if not _client:
        logger.warning("Zilliz client not available")
        return []
    
    try:
        # Query all records (empty filter means get all)
        results = _client.query(
            collection_name=_collection_name,
            filter="",
            output_fields=_readable_fields,
            limit=1000  # Reasonable limit
        )
        
        # Remove empty fields
        jobs = [{k: v for k, v in job.items() if v or v == 0} for job in results]
        
        logger.debug("Retrieved %d jobs from collection", len(jobs))
        return jobs
        
    except Exception as exc:
        logger.exception("Failed to get all jobs: %s", exc)
        return []


def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific job by ID."""
    if not _client:
        logger.warning("Zilliz client not available")
        return None
    
    try:
        results = _client.query(
            collection_name=_collection_name,
            filter=f'job_id == "{job_id}"',
            output_fields=_readable_fields,
            limit=1
        )
        
        if results:
            # Remove empty fields
            job = {k: v for k, v in results[0].items() if v or v == 0}
            return job
        
        return None
        
    except Exception as exc:
        logger.exception("Failed to get job by ID %s: %s", job_id, exc)
        return None


def insert_job(**job_data) -> bool:
    """Insert a new job.
    
    Args:
        **job_data: Job data including id, position, background, etc.
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not _client:
        logger.warning("Zilliz client not available")
        return False
    
    try:
        # Prepare data for insertion
        now = datetime.now().isoformat()
        drill_down = str(job_data.get("drill_down_questions", ""))[:30000]
        
        insert_data = {
            "job_id": job_data["id"],
            "position": job_data["position"],
            "background": job_data.get("background", ""),
            "description": job_data.get("description", ""),
            "responsibilities": job_data.get("responsibilities", ""),
            "requirements": job_data.get("requirements", ""),
            "target_profile": job_data.get("target_profile", ""),
            "keywords": job_data.get("keywords", {"positive": [], "negative": []}),
            "drill_down_questions": drill_down,
            "candidate_filters": job_data.get("candidate_filters"),
            "job_embedding": [0.0] * _job_store_config["embedding_dim"],  # Empty embedding for now
            "created_at": now,
            "updated_at": now,
        }
        
        # Filter to only valid fields
        insert_data = {k: v for k, v in insert_data.items() if k in _all_fields and (v or v == 0)}
        
        # Insert data
        _client.insert(collection_name=_collection_name, data=[insert_data])
        
        logger.debug("Successfully inserted job: %s", job_data["id"])
        return True
        
    except Exception as exc:
        logger.exception("Failed to insert job %s: %s", job_data.get("id"), exc)
        return False


def update_job(job_id: str, **job_data) -> bool:
    """Update an existing job.
    
    Args:
        job_id: Job ID to update
        **job_data: Job data to update
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not _client:
        logger.warning("Zilliz client not available")
        return False
    
    try:
        # Check if job exists
        existing = get_job_by_id(job_id)
        if not existing:
            logger.warning("Job %s not found for update", job_id)
            return False
        
        # Prepare update data
        now = datetime.now().isoformat()
        
        update_data = {
            "job_id": job_id,
            "position": job_data.get("position", existing.get("position", "")),
            "background": job_data.get("background", existing.get("background", "")),
            "description": job_data.get("description", existing.get("description", "")),
            "responsibilities": job_data.get("responsibilities", existing.get("responsibilities", "")),
            "requirements": job_data.get("requirements", existing.get("requirements", "")),
            "target_profile": job_data.get("target_profile", existing.get("target_profile", "")),
            "keywords": job_data.get("keywords", existing.get("keywords", {"positive": [], "negative": []})),
            "drill_down_questions": str(job_data.get("drill_down_questions", existing.get("drill_down_questions", "")))[:30000],
            "candidate_filters": job_data.get("candidate_filters", existing.get("candidate_filters")),
            "job_embedding": [0.0] * _job_store_config["embedding_dim"],  # Keep empty for now
            "created_at": existing.get("created_at", now),  # Keep original creation time
            "updated_at": now,
        }
        
        # Filter to only valid fields
        update_data = {k: v for k, v in update_data.items() if k in _all_fields and (v or v == 0)}
        
        # Use upsert to update
        _client.upsert(
            collection_name=_collection_name,
            data=[update_data],
            partial_update=bool(job_id),  # Partial update if job_id exists
        )
        
        logger.debug("Successfully updated job: %s", job_id)
        return True
        
    except Exception as exc:
        logger.exception("Failed to update job %s: %s", job_id, exc)
        return False


def delete_job(job_id: str) -> bool:
    """Delete a job by ID.
    
    Args:
        job_id: Job ID to delete
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not _client:
        logger.warning("Zilliz client not available")
        return False
    
    try:
        # Delete by primary key
        _client.delete(
            collection_name=_collection_name,
            filter=f'job_id == "{job_id}"'
        )
        
        logger.debug("Successfully deleted job: %s", job_id)
        return True
        
    except Exception as exc:
        logger.exception("Failed to delete job %s: %s", job_id, exc)
        return False


__all__ = [
    "get_job_collection_schema",
    "create_job_collection",
    "get_all_jobs",
    "get_job_by_id",
    "insert_job",
    "update_job",
    "delete_job",
]
