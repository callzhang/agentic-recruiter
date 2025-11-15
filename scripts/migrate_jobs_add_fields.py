"""Migration script to add version and current fields to existing jobs.

⚠️  MIGRATION COMPLETED - This script is kept for reference only.

This script:
1. Adds 'version' (INT64) and 'current' (BOOL) fields to the collection
2. Migrates all existing jobs to versioned format (ml_engineer -> ml_engineer_v1)
3. Sets version=1 and current=True for all migrated jobs

Status: ✅ Completed - Jobs collection now uses versioning.
"""

import sys
from pathlib import Path
from datetime import datetime
from pymilvus import DataType

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.jobs_store import _client, _collection_name, get_base_job_id, _job_store_config
from src.global_logger import logger


def migrate_jobs_add_fields():
    """Add version and current fields to existing jobs."""
    if not _client:
        logger.error("Zilliz client not available")
        return False
    
    # Check if collection exists
    if not _client.has_collection(collection_name=_collection_name):
        logger.error(f"Collection {_collection_name} does not exist")
        return False
    
    # Step 1: Add version field to collection
    logger.info("Step 1: Adding 'version' field to collection...")
    try:
        _client.add_collection_field(
            collection_name=_collection_name,
            field_name="version",
            data_type=DataType.INT64,
            nullable=True  # Must be nullable for existing entities
        )
        logger.info("✅ Added 'version' field")
    except Exception as e:
        error_msg = str(e)
        if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
            logger.info("'version' field already exists, skipping")
        else:
            logger.error(f"Failed to add 'version' field: {e}")
            return False
    
    # Step 2: Add current field to collection
    logger.info("Step 2: Adding 'current' field to collection...")
    try:
        _client.add_collection_field(
            collection_name=_collection_name,
            field_name="current",
            data_type=DataType.BOOL,
            nullable=True  # Must be nullable for existing entities
        )
        logger.info("✅ Added 'current' field")
    except Exception as e:
        error_msg = str(e)
        if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
            logger.info("'current' field already exists, skipping")
        else:
            logger.error(f"Failed to add 'current' field: {e}")
            return False
    
    # Step 3: Get all existing jobs (now including version and current fields)
    logger.info("Step 3: Querying existing jobs...")
    existing_fields = [
        "job_id", "position", "background", "description", "responsibilities",
        "requirements", "target_profile", "keywords", "drill_down_questions",
        "candidate_filters", "created_at", "updated_at", "version", "current"
    ]
    
    try:
        old_jobs = _client.query(
            collection_name=_collection_name,
            filter="",
            output_fields=existing_fields,
            limit=1000
        )
        logger.info(f"Found {len(old_jobs)} jobs to migrate")
    except Exception as e:
        logger.error(f"Failed to query existing jobs: {e}")
        return False
    
    if not old_jobs:
        logger.info("No jobs to migrate")
        return True
    
    migrated_count = 0
    skipped_count = 0
    
    for job in old_jobs:
        job_id = job.get("job_id", "")
        if not job_id:
            continue
        
        # Check if already in versioned format
        if "_v" in job_id and job_id.split("_v")[-1].isdigit():
            logger.debug(f"Job {job_id} already in versioned format, skipping")
            skipped_count += 1
            continue
        
        # Extract base job_id and create versioned job_id
        base_job_id = get_base_job_id(job_id)
        new_job_id = f"{base_job_id}_v1"
        
        # Check if v1 already exists
        try:
            existing_v1 = _client.query(
                collection_name=_collection_name,
                filter=f'job_id == "{new_job_id}"',
                output_fields=["job_id"],
                limit=1
            )
            if existing_v1:
                logger.warning(f"Version v1 already exists for {base_job_id}, skipping")
                skipped_count += 1
                continue
        except Exception as e:
            logger.debug(f"Could not check for existing v1 (field may not exist yet): {e}")
        
        # Prepare job data with new fields
        job_data = {k: v for k, v in job.items() if v or v == 0}
        job_data["job_id"] = new_job_id
        job_data["version"] = 1
        job_data["current"] = True
        
        # Ensure job_embedding is included (required field)
        if "job_embedding" not in job_data:
            # Create empty embedding vector if missing
            embedding_dim = _job_store_config.get("embedding_dim", 1536)
            job_data["job_embedding"] = [0.0] * embedding_dim
        
        try:
            # First, delete the old record
            _client.delete(
                collection_name=_collection_name,
                filter=f'job_id == "{job_id}"'
            )
            
            # Insert with new fields (now that they've been added to the schema)
            _client.insert(
                collection_name=_collection_name,
                data=[job_data]
            )
            
            logger.info(f"Migrated job: {job_id} -> {new_job_id}")
            migrated_count += 1
            
        except Exception as e:
            logger.error(f"Failed to migrate job {job_id}: {e}")
            skipped_count += 1
            continue
    
    logger.info(f"✅ Migration complete: {migrated_count} jobs migrated, {skipped_count} skipped")
    return True


if __name__ == "__main__":
    logger.info("Starting job versioning migration (adding fields to existing collection)...")
    
    success = migrate_jobs_add_fields()
    if success:
        logger.info("✅ Migration completed successfully")
        sys.exit(0)
    else:
        logger.error("❌ Migration failed")
        sys.exit(1)

