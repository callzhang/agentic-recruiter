#!/usr/bin/env python3
"""Unified migration script for collections.

This script can migrate either candidates or jobs collections to match
the current schema definitions in candidate_store.py and jobs_store.py.

Usage:
    python scripts/migrate_collection.py candidates [new_collection_name]
    python scripts/migrate_collection.py jobs [new_collection_name]
"""

import sys
import argparse
import uuid
from datetime import datetime
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymilvus import MilvusClient, Collection, CollectionSchema, DataType, connections
from src.config import get_zilliz_config
from src.global_logger import logger
from src.candidate_store import get_collection_schema as get_candidate_schema
from src.jobs_store import get_job_collection_schema


def get_index_config(collection_type: str, zilliz_config: dict):
    """Get index configuration for a collection type.
    
    Args:
        collection_type: 'candidates' or 'jobs'
        zilliz_config: Zilliz configuration dict
        
    Returns:
        dict: Index configuration with field names and params
    """
    if collection_type == 'candidates':
        return {
            'resume_vector': {
                "index_type": "AUTOINDEX",
                "metric_type": "IP",
                "params": {},
            },
            'conversation_id': {},
            'chat_id': {},
            'stage': {},
        }
    elif collection_type == 'jobs':
        return {
            'job_embedding': {
                "metric_type": "L2",
                "index_type": "AUTOINDEX",
            },
            'version': {},
            'current': {},
        }
    else:
        return {}


def rename_collection(client: MilvusClient, zilliz_config: dict, old_name: str, new_name: str) -> bool:
    """Rename a collection by copying data to a new collection and dropping the old one.
    
    Since Milvus doesn't support renaming, this function:
    1. Creates a new collection with the target name
    2. Copies all data from the source collection
    3. Drops the source collection
    
    Args:
        client: MilvusClient instance
        zilliz_config: Zilliz configuration dict
        old_name: Current collection name
        new_name: Target collection name
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not client.has_collection(old_name):
        logger.error(f"Source collection {old_name} does not exist")
        return False
    
    if client.has_collection(new_name):
        logger.error(f"Target collection {new_name} already exists")
        return False
    
    try:
        # Connect for Collection API
        connections.connect(
            alias="default",
            uri=zilliz_config["endpoint"],
            user=zilliz_config["user"],
            password=zilliz_config["password"],
            token=zilliz_config.get("token", ""),
            secure=zilliz_config["endpoint"].startswith("https://")
        )
        
        old_col = Collection(old_name)
        old_col.load()
        
        # Get schema from existing collection
        schema = old_col.schema
        
        # Check if the collection has auto_id enabled
        primary_field = next((f for f in schema.fields if f.is_primary), None)
        has_auto_id = primary_field and getattr(primary_field, 'auto_id', False)
        
        # Create new collection with same schema
        new_col = Collection(name=new_name, schema=schema)
        
        # Copy all data
        logger.info(f"Copying data from {old_name} to {new_name}...")
        batch_size = 100
        offset = 0
        total_copied = 0
        
        # Get valid field names from schema (exclude primary key if auto_id)
        valid_field_names = {field.name for field in schema.fields}
        if has_auto_id and primary_field:
            # Remove primary key from data since it's auto-generated
            valid_field_names.discard(primary_field.name)
            logger.debug(f"Excluding auto-generated primary field: {primary_field.name}")
        
        logger.debug(f"Will include {len(valid_field_names)} fields: {valid_field_names}")
        
        while True:
            results = client.query(
                collection_name=old_name,
                filter="",
                output_fields=["*"],
                limit=batch_size,
                offset=offset
            )
            
            if not results:
                break
            
            # Filter data to only include fields in schema (exclude internal Milvus fields and auto_id fields)
            filtered_results = []
            for record in results:
                filtered_record = {
                    k: v for k, v in record.items() 
                    if not k.startswith("$") and k in valid_field_names
                }
                filtered_results.append(filtered_record)
            
            # Insert into new collection
            if filtered_results:
                client.insert(collection_name=new_name, data=filtered_results)
                total_copied += len(filtered_results)
            offset += batch_size
            
            if len(results) < batch_size:
                break
        
        # Flush before creating indexes
        new_col.flush()
        
        # Create indexes on new collection (copy from old)
        logger.info(f"Copying indexes...")
        for field in schema.fields:
            try:
                if field.dtype == DataType.FLOAT_VECTOR:
                    # Vector index
                    index_params = {
                        "metric_type": "L2",
                        "index_type": "AUTOINDEX",
                    }
                    new_col.create_index(field_name=field.name, index_params=index_params)
                elif field.name in ['version', 'current', 'conversation_id', 'chat_id', 'stage']:
                    # Scalar indexes
                    new_col.create_index(field_name=field.name, index_params={})
            except Exception as e:
                # Index might already exist, log and continue
                logger.debug(f"Index creation for {field.name} skipped: {e}")
        
        # Load and verify
        new_col.load()
        new_count = new_col.num_entities
        old_count = old_col.num_entities
        
        if new_count == old_count:
            # Drop old collection
            logger.info(f"Dropping old collection {old_name}...")
            client.drop_collection(old_name)
            logger.info(f"✅ Successfully renamed {old_name} to {new_name}")
            return True
        else:
            logger.error(f"Record count mismatch: {old_count} vs {new_count}")
            # Drop the new collection since it's incomplete
            client.drop_collection(new_name)
            return False
            
    except Exception as e:
        logger.error(f"Failed to rename collection: {e}", exc_info=True)
        return False


def transform_record(record: dict, schema_fields: list, collection_type: str) -> dict:
    """Transform a record to match the new schema.
    
    Args:
        record: Original record from old collection
        schema_fields: List of FieldSchema objects for new schema
        collection_type: 'candidates' or 'jobs'
        
    Returns:
        dict: Transformed record with only fields in the schema
    """
    # Get list of valid field names from schema
    valid_field_names = {field.name for field in schema_fields}
    
    new_record = {}
    
    # Only copy fields that are in the schema (except internal Milvus fields)
    for key, value in record.items():
        if not key.startswith("$") and key in valid_field_names:
            new_record[key] = value
    
    # Collection-specific transformations
    if collection_type == 'candidates':
        # Handle conversation_id: preserve existing, or use thread_id as fallback
        if "conversation_id" in record and record.get("conversation_id"):
            new_record["conversation_id"] = record["conversation_id"]
        elif "thread_id" in record and record.get("thread_id"):
            new_record["conversation_id"] = record["thread_id"]
        else:
            new_record["conversation_id"] = None
        
        # Initialize notified field if not present
        if "notified" not in new_record or new_record["notified"] is None:
            new_record["notified"] = False
        
        # Generate candidate_id if not present (since auto_id is now False)
        # Preserve existing candidate_id if it exists, otherwise generate a new UUID
        if "candidate_id" not in new_record or not new_record.get("candidate_id"):
            new_record["candidate_id"] = str(uuid.uuid4())
            logger.debug(f"Generated new candidate_id: {new_record['candidate_id']}")
            
    elif collection_type == 'jobs':
        # Initialize notification field if not present
        if "notification" not in new_record or new_record["notification"] is None:
            new_record["notification"] = {}
    
    # Ensure all required fields exist with appropriate defaults
    for field in schema_fields:
        if field.name not in new_record:
            if field.nullable:
                if field.dtype == DataType.BOOL:
                    new_record[field.name] = False
                elif field.dtype == DataType.JSON:
                    new_record[field.name] = {}
                else:
                    new_record[field.name] = None
            elif field.dtype == DataType.VARCHAR:
                new_record[field.name] = ""
            elif field.dtype == DataType.INT64:
                new_record[field.name] = 0
            elif field.dtype == DataType.FLOAT:
                new_record[field.name] = 0.0
            else:
                new_record[field.name] = None
    
    return new_record


def migrate_collection(collection_type: str, new_collection_name: str = None):
    """Migrate a collection to match current schema.
    
    Args:
        collection_type: 'candidates' or 'jobs'
        new_collection_name: Optional name for new collection (defaults to {old_name}_v2)
        
    Returns:
        bool: True if successful, False otherwise
    """
    if collection_type not in ['candidates', 'jobs']:
        logger.error(f"Invalid collection type: {collection_type}. Must be 'candidates' or 'jobs'")
        return False
    
    # Get Zilliz config
    zilliz_config = get_zilliz_config()
    
    # Create MilvusClient
    client = MilvusClient(
        uri=zilliz_config["endpoint"],
        user=zilliz_config["user"],
        password=zilliz_config["password"],
        token=zilliz_config.get("token", ""),
        secure=zilliz_config["endpoint"].startswith("https://")
    )
    
    # Get collection names
    if collection_type == 'candidates':
        old_collection = zilliz_config["candidate_collection_name"]
        new_collection = new_collection_name or f"{old_collection}_v2"
        schema_fields = get_candidate_schema()
        description = "Candidates collection with current schema"
    else:  # jobs
        old_collection = zilliz_config["job_collection_name"]
        new_collection = new_collection_name or f"{old_collection}_v2"
        schema_fields = get_job_collection_schema()
        description = "Jobs collection with notification field"
    
    try:
        # Check if old collection exists
        if not client.has_collection(old_collection):
            logger.error(f"Source collection {old_collection} does not exist")
            return False
        
        logger.info(f"Found source collection: {old_collection}")
        
        # Check if new collection already exists
        if client.has_collection(new_collection):
            logger.warning(f"Target collection {new_collection} already exists. Please drop it first if you want to re-run migration.")
            response = input(f"Drop existing collection {new_collection} and continue? (yes/no): ")
            if response.lower() != 'yes':
                logger.info("Migration cancelled")
                return False
            logger.info(f"Dropping existing collection {new_collection}...")
            client.drop_collection(new_collection)
        
        # Connect for Collection API
        connections.connect(
            alias="default",
            uri=zilliz_config["endpoint"],
            user=zilliz_config["user"],
            password=zilliz_config["password"],
            token=zilliz_config.get("token", ""),
            secure=zilliz_config["endpoint"].startswith("https://")
        )
        
        # Create new collection schema
        logger.info(f"Creating new collection: {new_collection}")
        logger.debug(f"Schema fields: {[f.name for f in schema_fields]}")
        
        # Create CollectionSchema from fields
        schema = CollectionSchema(
            fields=schema_fields,
            description=description
        )
        
        # Create new collection with auto_id=False for candidates (since we're generating IDs manually)
        if collection_type == 'candidates':
            # Create collection using MilvusClient to set auto_id=False
            client.create_collection(
                collection_name=new_collection,
                dimension=zilliz_config["embedding_dim"],
                primary_field_name="candidate_id",
                vector_field_name="resume_vector",
                id_type="string",
                auto_id=False,
                max_length=64,
                metric_type="IP",
                schema=schema,
            )
            # Get the collection object for further operations
            new_col = Collection(new_collection)
        else:
            # For jobs, use the standard Collection creation
            new_col = Collection(name=new_collection, schema=schema)
        
        # Create indexes
        logger.info("Creating indexes...")
        index_config = get_index_config(collection_type, zilliz_config)
        
        for field_name, index_params in index_config.items():
            if field_name in [f.name for f in schema_fields]:
                if index_params:
                    new_col.create_index(field_name=field_name, index_params=index_params)
                else:
                    new_col.create_index(field_name=field_name, index_params={})
                logger.info(f"Created index on {field_name}")
        
        # Query all data from old collection
        logger.info("Querying all data from old collection...")
        
        batch_size = 100
        offset = 0
        all_records = []
        
        while True:
            logger.info(f"Querying batch starting at offset {offset}...")
            
            results = client.query(
                collection_name=old_collection,
                filter="",
                output_fields=["*"],
                limit=batch_size,
                offset=offset
            )
            
            if not results:
                logger.info("Reached end of data")
                break
            
            logger.info(f"Retrieved {len(results)} records in this batch")
            all_records.extend(results)
            offset += batch_size
            
            if len(results) < batch_size:
                break
        
        logger.info(f"Total records retrieved: {len(all_records)}")
        
        # Transform records for migration
        logger.info("Transforming records for migration...")
        migrated_data = []
        for record in all_records:
            transformed = transform_record(record, schema_fields, collection_type)
            migrated_data.append(transformed)
        
        # Insert into new collection
        logger.info(f"Inserting {len(migrated_data)} records into new collection...")
        
        # Insert in batches
        insert_batch_size = 100
        total_migrated = 0
        
        for i in range(0, len(migrated_data), insert_batch_size):
            batch = migrated_data[i:i + insert_batch_size]
            logger.info(f"Inserting batch {i // insert_batch_size + 1} ({len(batch)} records)...")
            
            insert_result = client.insert(
                collection_name=new_collection,
                data=batch
            )
            
            logger.info(f"✅ Inserted batch: {insert_result}")
            total_migrated += len(batch)
        
        logger.info(f"✅ Migration completed! Total records migrated: {total_migrated}")
        
        # Verify migration
        logger.info("Verifying migration...")
        
        # Flush to ensure all inserts are persisted
        new_col.flush()
        
        # Load collections to get accurate counts
        old_col = Collection(old_collection)
        old_col.load()
        old_count = old_col.num_entities
        
        new_col.load()
        new_count = new_col.num_entities
        
        logger.info(f"Old collection records: {old_count}")
        logger.info(f"New collection records: {new_count}")
        logger.info(f"Records migrated: {total_migrated}")
        
        if new_count == total_migrated:
            logger.info("✅ Migration verified! All records are in the new collection.")
            
            # Rename collections: old -> NAME_timestamp, new -> NAME
            logger.info("Renaming collections...")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            old_backup_name = f"{old_collection}_{timestamp}"
            final_name = old_collection  # The original name
            
            # Step 1: Rename old collection to NAME_timestamp (backup)
            # Skip if it fails - the new collection is already ready
            logger.info(f"Backing up old collection {old_collection} to {old_backup_name}...")
            backup_success = rename_collection(client, zilliz_config, old_collection, old_backup_name)
            if backup_success:
                logger.info(f"✅ Backed up {old_collection} to {old_backup_name}")
            else:
                logger.warning(f"⚠️ Failed to backup {old_collection}, but new collection is ready. You can manually drop the old collection later.")
            
            # Step 2: Rename new collection (NAME_v2) to NAME
            logger.info(f"Renaming {new_collection} to {final_name}...")
            if rename_collection(client, zilliz_config, new_collection, final_name):
                logger.info(f"✅ Renamed {new_collection} to {final_name}")
                logger.info(f"✅ Migration complete! Collection is now at {final_name}")
                if backup_success:
                    logger.info(f"   Old collection backed up as {old_backup_name}")
                else:
                    logger.info(f"   Old collection {old_collection} still exists - you may want to drop it manually")
                return True
            else:
                logger.error(f"❌ Failed to rename {new_collection} to {final_name}")
                logger.warning(f"⚠️ New collection is available at {new_collection} - you may need to update config or rename manually")
                return False
        else:
            logger.warning(f"⚠️ Record count mismatch: expected {total_migrated}, got {new_count}")
            return False
            
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False
    finally:
        connections.disconnect("default")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate collections to match current schema definitions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/migrate_collection.py candidates
  python scripts/migrate_collection.py jobs
  python scripts/migrate_collection.py candidates CN_candidates_v3
  python scripts/migrate_collection.py jobs CN_jobs_v2
        """
    )
    parser.add_argument(
        'collection_type',
        choices=['candidates', 'jobs'],
        help='Type of collection to migrate'
    )
    parser.add_argument(
        'new_collection_name',
        nargs='?',
        help='Optional name for new collection (defaults to {old_name}_v2)'
    )
    
    args = parser.parse_args()
    
    success = migrate_collection(args.collection_type, args.new_collection_name)
    if success:
        print("✅ Successfully migrated collection!")
        sys.exit(0)
    else:
        print("❌ Migration failed. Check logs for details.")
        sys.exit(1)

