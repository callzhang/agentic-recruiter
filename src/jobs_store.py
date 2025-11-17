"""Zilliz/Milvus-backed job profile store integration."""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from pymilvus import DataType, FieldSchema, CollectionSchema
# Use the same client instance as candidate_store
from src.candidate_store import _client, truncate_field
from .global_logger import logger
from .config import get_zilliz_config, get_openai_config
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
    
    # Versioning fields
    FieldSchema(name="version", dtype=DataType.INT64),
    FieldSchema(name="current", dtype=DataType.BOOL),
    
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
# Helper Functions
# ------------------------------------------------------------------

def get_base_job_id(job_id: str) -> str:
    """Extract base job_id by removing version suffix.
    
    Args:
        job_id: Job ID with optional version suffix (e.g., "ml_engineer_v2")
        
    Returns:
        Base job_id without version suffix (e.g., "ml_engineer")
    """
    return re.sub(r'_v\d+$', '', job_id)


# ------------------------------------------------------------------
# Collection Management
# ------------------------------------------------------------------

def create_job_collection(collection_name: Optional[str] = None) -> bool:
    """Create the jobs collection with the defined schema and embedding function.
    
    The collection includes a built-in OpenAI embedding function that automatically
    generates vectors for job_embedding field from concatenated text fields.
    
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
        
        # Create CollectionSchema from FieldSchema list
        schema = CollectionSchema(
            fields=get_job_collection_schema(),
            description="Jobs collection with versioning support and automatic embeddings"
        )
        
        # Create OpenAI embedding function for automatic vector generation
        openai_config = get_openai_config()
        openai_api_key = openai_config.get("api_key")
        
        if not openai_api_key:
            logger.warning("OpenAI API key not found in config, creating collection without embedding function")
        else:
            try:
                # Add embedding function to schema - it will automatically generate embeddings
                # The function will generate vectors from concatenated text fields
                # Input fields: all text fields that should be embedded
                # Output field: job_embedding (the vector field)
                from pymilvus import Function, FunctionType
                
                # Create a function that combines multiple text fields and generates embeddings
                # Using FunctionType.TEXTEMBEDDING with OpenAI provider
                # Include API key in params if Milvus requires it
                # Note: Milvus requires exactly 1 input field for TEXTEMBEDDING functions
                # We need to use a combined text field instead of multiple fields
                # For now, this function creation will fail until we add job_text_combined field
                # See migration script for the correct implementation
                embedding_fn = Function(
                    name="job_embedding_fn",
                    function_type=FunctionType.TEXTEMBEDDING,
                    input_field_names=["job_text_combined"],  # Single input field required
                    output_field_names=["job_embedding"],
                    params={
                        "provider": "openai",
                        "model_name": "text-embedding-3-small",
                        "credential": openai_api_key,  # Use 'credential' per Milvus docs
                    }
                )
                
                schema.add_function(embedding_fn)
                logger.info("✅ Added OpenAI embedding function to schema (using API key from config)")
            except Exception as e:
                logger.warning(f"Failed to add embedding function: {e}")
                logger.warning("Creating collection without embedding function")
        
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
            schema=schema,
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
    """Get all jobs from the collection (only current versions).
    
    Returns jobs with base job_id extracted (version suffix removed) for display.
    Jobs are sorted by updated_at in descending order (most recently updated first).
    """
    # Query only current versions
    results = _client.query(
        collection_name=_collection_name,
        filter='current == true',
        output_fields=_readable_fields,
        limit=1000  # Reasonable limit
    )
    
    # Remove empty fields and extract base job_id for display
    jobs = []
    for job in results:
        job_dict = {k: v for k, v in job.items() if v or v == 0}
        # Extract base job_id for display (remove _vN suffix)
        if "job_id" in job_dict:
            job_dict["base_job_id"] = get_base_job_id(job_dict["job_id"])
        jobs.append(job_dict)
    
    # Sort by updated_at in descending order (most recent first)
    jobs.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    
    logger.debug("Retrieved %d current jobs from collection (sorted by updated_at)", len(jobs))
    return jobs
            

def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific job by ID (returns current version).
    
    If job_id has a version suffix, extracts base_job_id and returns current version.
    If job_id is base (no suffix), returns current version directly.
    
    Args:
        job_id: Job ID (can be base_job_id or versioned job_id)
        
    Returns:
        Current version of the job, or None if not found
    """
    # Extract base job_id (remove _vN suffix if present)
    base_job_id = get_base_job_id(job_id)
    
    # Query current version for this base job_id
    # We need to find the job where job_id starts with base_job_id_v and current=True
    results = _client.query(
        collection_name=_collection_name,
        filter=f'job_id >= "{base_job_id}_v" and job_id < "{base_job_id}_w" and current == true',
        output_fields=_readable_fields,
        limit=100
    )
    
    # Filter to exact matches and get the first one (should be only one current version)
    for job in results:
        job_dict = {k: v for k, v in job.items() if v or v == 0}
        job_id_value = job_dict.get("job_id", "")
        # Verify it matches the pattern
        if job_id_value.startswith(f"{base_job_id}_v") and re.match(rf'^{re.escape(base_job_id)}_v\d+$', job_id_value):
            return job_dict
    
    return None
            

def insert_job(**job_data) -> bool:
    """Insert a new job.
    
    Creates the first version (v1) with current=True.
    
    Args:
        **job_data: Job data including id, position, background, etc.
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Extract base job_id (remove any existing _vN suffix if present)
    base_job_id = get_base_job_id(job_data["id"])
    versioned_job_id = f"{base_job_id}_v1"
    
    now = datetime.now().isoformat()
    drill_down_questions = job_data.get("drill_down_questions", "")
    drill_down_questions = truncate_field(drill_down_questions, 30000)
    insert_data = {
        "job_id": versioned_job_id,
        "position": job_data["position"],
        "background": job_data.get("background", ""),
        "description": job_data.get("description", ""),
        "responsibilities": job_data.get("responsibilities", ""),
        "requirements": job_data.get("requirements", ""),
        "target_profile": job_data.get("target_profile", ""),
        "keywords": job_data.get("keywords", {"positive": [], "negative": []}),
        "drill_down_questions": drill_down_questions,
        "candidate_filters": job_data.get("candidate_filters"),
        "job_embedding": [0.0] * _job_store_config["embedding_dim"],  # Empty embedding for now
        "version": 1,
        "current": True,
        "created_at": now,
        "updated_at": now,
    }
    
    # Filter to only valid fields
    insert_data = {k: v for k, v in insert_data.items() if k in _all_fields and (v or v == 0)}
        
    # Insert data
    _client.insert(collection_name=_collection_name, data=[insert_data])
        
    logger.debug("Successfully inserted job: %s (version 1)", versioned_job_id)
    return True
            
    
    
def update_job(job_id: str, **job_data) -> bool:
    """Update an existing job.
    
    Creates a new version by:
    1. Getting the current version (where current=True)
    2. Setting current=False on the old version
    3. Creating a new version with current=True and incremented version number
    
    Args:
        job_id: Job ID to update (can be base_job_id or versioned job_id)
        **job_data: Job data to update
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Extract base job_id
    base_job_id = get_base_job_id(job_id)
    
    # Get current job (where current=True)
    current_job = get_job_by_id(base_job_id)
    if not current_job:
        logger.warning("Job %s not found for update", base_job_id)
        return False
            
    # Get all versions to determine next version number
    all_versions = get_job_versions(base_job_id)
    max_version = max([v.get("version", 0) for v in all_versions], default=0)
    next_version = max_version + 1
    new_versioned_job_id = f"{base_job_id}_v{next_version}"
    
    # Set current job's current=False
    old_job_id = current_job.get("job_id")
    if old_job_id:
        _client.upsert(
            collection_name=_collection_name,
            data=[{"job_id": old_job_id, "current": False}],
            partial_update=True,
        )
    
    # Create new version with updated data
    now = datetime.now().isoformat()
    drill_down_questions = job_data.get("drill_down_questions", current_job.get("drill_down_questions", ""))
    drill_down_questions = truncate_field(str(drill_down_questions), 30000)
    new_version_data = {
        "job_id": new_versioned_job_id,
        "position": job_data.get("position", current_job.get("position", "")),
        "background": job_data.get("background", current_job.get("background", "")),
        "description": job_data.get("description", current_job.get("description", "")),
        "responsibilities": job_data.get("responsibilities", current_job.get("responsibilities", "")),
        "requirements": job_data.get("requirements", current_job.get("requirements", "")),
        "target_profile": job_data.get("target_profile", current_job.get("target_profile", "")),
        "keywords": job_data.get("keywords", current_job.get("keywords", {"positive": [], "negative": []})),
        "drill_down_questions": drill_down_questions,
        "candidate_filters": job_data.get("candidate_filters", current_job.get("candidate_filters")),
        "job_embedding": [0.0] * _job_store_config["embedding_dim"],  # Keep empty for now
        "version": next_version,
        "current": True,
        "created_at": current_job.get("created_at", now),  # Keep original creation time
        "updated_at": now,
    }

    # Filter to only valid fields
    new_version_data = {k: v for k, v in new_version_data.items() if k in _all_fields and (v or v == 0)}
        
    # Insert new version
    _client.insert(collection_name=_collection_name, data=[new_version_data])
    
    logger.debug("Successfully updated job: %s (created version %d)", new_versioned_job_id, next_version)
    return True
            
def get_job_versions(base_job_id: str) -> List[Dict[str, Any]]:
    """Get all versions of a job.
    
    Args:
        base_job_id: Base job ID without version suffix
        
    Returns:
        List of all versions sorted by created_at DESC (latest first)
    """
    # Query all records where job_id starts with base_job_id_v
    results = _client.query(
        collection_name=_collection_name,
        filter=f'job_id >= "{base_job_id}_v" and job_id < "{base_job_id}_w"',  # String range query
        output_fields=_readable_fields,
        limit=1000
    )
    
    # Filter to only exact matches (job_id starts with base_job_id_v followed by digits)
    versions = [
        {k: v for k, v in job.items() if v or v == 0}
        for job in results
        if job.get("job_id", "").startswith(f"{base_job_id}_v") and re.match(rf'^{re.escape(base_job_id)}_v\d+$', job.get("job_id", ""))
    ]
    
    # Sort by created_at DESC (latest first)
    versions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    logger.debug("Retrieved %d versions for job %s", len(versions), base_job_id)
    return versions


def switch_job_version(base_job_id: str, version: int) -> bool:
    """Switch the current version of a job.
    
    Sets all versions' current=False, then sets the selected version's current=True.
    Includes position field in upsert to avoid DataNotMatchException.
    
    Args:
        base_job_id: Base job ID without version suffix
        version: Version number to make current
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Get all versions
    all_versions = get_job_versions(base_job_id)
    
    # Find the target version
    target_job_id = f"{base_job_id}_v{version}"
    target_version = next((v for v in all_versions if v.get("job_id") == target_job_id), None)
    
    if not target_version:
        logger.warning("Version %d not found for job %s", version, base_job_id)
        return False

    # Query all versions to get position fields
    results = _client.query(
        collection_name=_collection_name,
        filter=f'job_id >= "{base_job_id}_v" and job_id < "{base_job_id}_w"',
        output_fields=['job_id', 'position', 'current'],
        limit=1000
    )
    
    # Create a map of job_id to position for quick lookup
    job_positions = {job.get("job_id"): job.get("position", "") for job in results if job.get("job_id")}

    # Set all versions' current=False (include position to avoid DataNotMatchException)
    for v in all_versions:
        job_id = v.get("job_id")
        if job_id:
            job_position = job_positions.get(job_id, "")
            if job_position:  # Only update if we have the position
                _client.upsert(
                    collection_name=_collection_name,
                    data=[{"job_id": job_id, "position": job_position, "current": False}],
                    partial_update=True,
                )
    
    # Set target version's current=True (include position to avoid DataNotMatchException)
    target_position = job_positions.get(target_job_id, "")
    if target_position:
        _client.upsert(
            collection_name=_collection_name,
            data=[{"job_id": target_job_id, "position": target_position, "current": True}],
            partial_update=True,
        )
    else:
        # Fallback: query the specific job to get its position
        target_job = get_job_by_id(target_job_id)
        if target_job and target_job.get("position"):
            _client.upsert(
                collection_name=_collection_name,
                data=[{"job_id": target_job_id, "position": target_job["position"], "current": True}],
                partial_update=True,
            )
        else:
            logger.warning("Could not find position for job %s", target_job_id)
            return False
    
    logger.debug("Switched job %s to version %d", base_job_id, version)
    return True


def delete_job_version(base_job_id: str, version: int) -> bool:
    """Delete a specific version of a job.
    
    Args:
        base_job_id: Base job ID without version suffix
        version: Version number to delete
        
    Returns:
        bool: True if successful, False otherwise
    """
    versioned_job_id = f"{base_job_id}_v{version}"
    _client.delete(collection_name=_collection_name, filter=f'job_id == "{versioned_job_id}"')
    
    logger.debug("Successfully deleted job version: %s", versioned_job_id)
    return True


def delete_job(job_id: str) -> bool:
    """Delete a job by ID (deletes all versions).
    
    Args:
        job_id: Job ID to delete (can be base_job_id or versioned job_id)
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Extract base job_id
    base_job_id = get_base_job_id(job_id)
    
    # Delete all versions
    all_versions = get_job_versions(base_job_id)
    for v in all_versions:
        versioned_job_id = v.get("job_id")
        if versioned_job_id:
            _client.delete(collection_name=_collection_name, filter=f'job_id == "{versioned_job_id}"')
    
    logger.debug("Successfully deleted job: %s (all versions)", base_job_id)
    return True

