"""Restore jobs from backup JSON file and migrate them to versioned format."""

import sys
import json
from pathlib import Path
from pymilvus import DataType

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.jobs_store import _client, _collection_name, _job_store_config
from src.global_logger import logger


def restore_and_migrate_jobs(backup_file: str):
    """Restore jobs from backup and migrate to versioned format."""
    if not _client:
        logger.error("Zilliz client not available")
        return False
    
    # Load backup
    backup_path = Path(__file__).parent.parent / backup_file
    if not backup_path.exists():
        logger.error(f"Backup file not found: {backup_path}")
        return False
    
    with open(backup_path, 'r', encoding='utf-8') as f:
        jobs = json.load(f)
    
    logger.info(f"Loaded {len(jobs)} jobs from backup")
    
    # Ensure fields exist
    try:
        _client.add_collection_field(
            collection_name=_collection_name,
            field_name="version",
            data_type=DataType.INT64,
            nullable=True
        )
        logger.info("Added 'version' field")
    except Exception as e:
        if "duplicate" not in str(e).lower():
            logger.warning(f"Could not add 'version' field: {e}")
    
    try:
        _client.add_collection_field(
            collection_name=_collection_name,
            field_name="current",
            data_type=DataType.BOOL,
            nullable=True
        )
        logger.info("Added 'current' field")
    except Exception as e:
        if "duplicate" not in str(e).lower():
            logger.warning(f"Could not add 'current' field: {e}")
    
    # Migrate each job
    migrated_count = 0
    embedding_dim = _job_store_config.get("embedding_dim", 1536)
    
    for job in jobs:
        job_id = job.get("job_id", "")
        if not job_id:
            continue
        
        # Create versioned job_id
        base_job_id = job_id.replace("_v1", "").replace("_v2", "").replace("_v3", "")
        if "_v" in job_id:
            # Already versioned, use as-is
            new_job_id = job_id
            version = int(job_id.split("_v")[-1]) if job_id.split("_v")[-1].isdigit() else 1
        else:
            # Not versioned, add _v1
            new_job_id = f"{base_job_id}_v1"
            version = 1
        
        # Prepare job data
        job_data = {k: v for k, v in job.items() if v or v == 0}
        job_data["job_id"] = new_job_id
        job_data["version"] = version
        job_data["current"] = True
        
        # Ensure job_embedding is included
        if "job_embedding" not in job_data:
            job_data["job_embedding"] = [0.0] * embedding_dim
        
        try:
            _client.insert(
                collection_name=_collection_name,
                data=[job_data]
            )
            logger.info(f"Restored job: {job_id} -> {new_job_id}")
            migrated_count += 1
        except Exception as e:
            logger.error(f"Failed to restore job {job_id}: {e}")
    
    logger.info(f"✅ Restored {migrated_count} jobs")
    return True


if __name__ == "__main__":
    backup_file = "data/jobs_backup_20251114_161133.json"
    logger.info(f"Restoring jobs from {backup_file}...")
    
    success = restore_and_migrate_jobs(backup_file)
    if success:
        logger.info("✅ Restoration completed successfully")
        sys.exit(0)
    else:
        logger.error("❌ Restoration failed")
        sys.exit(1)

