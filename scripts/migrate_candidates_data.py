#!/usr/bin/env python3
"""Migrate data from CN_candidates to CN_candidates_v3.
    
This script:
1. Removes thread_id field and replaces it with conversation_id
2. Deduplicates records by name (case-insensitive)
3. For duplicates, keeps the record with:
   - Most recent updated_at timestamp, or
   - Most complete data (most non-null fields), or
   - First encountered if equal
"""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent  # Go up one level to project root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymilvus import MilvusClient, Collection, CollectionSchema, FieldSchema, DataType, connections
from src.config import settings
from src.global_logger import logger


def migrate_candidates_data():
    """Migrate data from old collection to new collection.
    
    Replaces thread_id with conversation_id and deduplicates by name.
    Returns True if successful, False otherwise.
    """
    
    # Create MilvusClient
    client = MilvusClient(
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    old_collection = settings.ZILLIZ_COLLECTION_NAME  # Use current collection from config
    new_collection = "CN_candidates_v3"
    
    try:
        # Check if old collection exists
        if not client.has_collection(old_collection):
            logger.error(f"Source collection {old_collection} does not exist")
            return False
        
        logger.info(f"Found source collection: {old_collection}")
        
        # Connect for Collection API
        connections.connect(
            alias="default",
            uri=settings.ZILLIZ_ENDPOINT,
            user=settings.ZILLIZ_USER,
            password=settings.ZILLIZ_PASSWORD,
            secure=True
        )
        
        # Create new collection schema WITHOUT thread_id, WITH conversation_id
        logger.info(f"Creating new collection: {new_collection}")
        
        # Define new schema
        new_fields = [
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
            FieldSchema(name="full_resume", dtype=DataType.VARCHAR, max_length=30000, nullable=True),
            # NEW: conversation_id instead of thread_id
            FieldSchema(name="conversation_id", dtype=DataType.VARCHAR, max_length=100, nullable=True),
        ]
        
        schema = CollectionSchema(
            new_fields,
            description="Candidates collection without thread_id (using conversation_id only)"
        )
        
        # Drop new collection if exists
        if client.has_collection(new_collection):
            logger.info(f"Collection {new_collection} already exists. Dropping it.")
            client.drop_collection(new_collection)
        
        # Create new collection
        new_col = Collection(new_collection, schema)
        
        # Create indexes
        index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "IP",
            "params": {},
        }
        new_col.create_index(field_name="resume_vector", index_params=index_params)
        new_col.create_index(field_name="conversation_id")
        new_col.create_index(field_name="chat_id")
        new_col.create_index(field_name="stage")
        logger.info("Created indexes on resume_vector, conversation_id, chat_id, and stage")
        
        # Query all data from old collection
        logger.info("Querying all data from old collection...")
        
        # Use smaller batch size to avoid gRPC message size limits
        # Vector fields are large, so we reduce batch size significantly
        batch_size = 100
        offset = 0
        all_records = []
        
        # First pass: collect all records
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
                logger.info("No more data to query")
                break
            
            logger.info(f"Retrieved {len(results)} records in this batch")
            all_records.extend(results)
            
            # Check if we got fewer results than batch_size (end of data)
            if len(results) < batch_size:
                logger.info("Reached end of data")
                break
            
            offset += batch_size
        
        logger.info(f"Total records retrieved: {len(all_records)}")
        
        # Second pass: deduplicate by name
        logger.info("Deduplicating records by name...")
        
        # Dictionary to store best record for each name
        # Key: name (normalized), Value: best record
        name_to_record = {}
        duplicates_removed = 0
        
        def count_non_null_fields(record):
            """Count non-null, non-empty fields in a record."""
            count = 0
            for key, value in record.items():
                if key == "candidate_id":  # Skip auto-generated ID
                    continue
                if value is not None and value != "":
                    if isinstance(value, (dict, list)):
                        if value:  # Non-empty dict/list
                            count += 1
                    else:
                        count += 1
            return count
        
        def compare_records(record1, record2):
            """Compare two records and return the better one.
            Prefer: 1) Most recent updated_at, 2) More complete data, 3) First encountered.
            """
            # Compare by updated_at timestamp
            updated_at1 = record1.get("updated_at")
            updated_at2 = record2.get("updated_at")
            
            if updated_at1 and updated_at2:
                try:
                    from datetime import datetime
                    dt1 = datetime.fromisoformat(updated_at1.replace('Z', '+00:00'))
                    dt2 = datetime.fromisoformat(updated_at2.replace('Z', '+00:00'))
                    if dt1 > dt2:
                        return record1
                    elif dt2 > dt1:
                        return record2
                except Exception:
                    pass  # Fall through to next comparison
            
            # Compare by completeness (number of non-null fields)
            count1 = count_non_null_fields(record1)
            count2 = count_non_null_fields(record2)
            
            if count1 > count2:
                return record1
            elif count2 > count1:
                return record2
            
            # If equal, prefer first one (record1)
            return record1
        
        for record in all_records:
            name = record.get("name")
            
            # Normalize name: strip whitespace and handle None/empty
            if name:
                name_normalized = name.strip().lower()
            else:
                # Use a special key for records without names
                name_normalized = "__NO_NAME__"
            
            if name_normalized in name_to_record:
                # Duplicate found - compare and keep the better one
                existing_record = name_to_record[name_normalized]
                better_record = compare_records(existing_record, record)
                
                if better_record != existing_record:
                    # Replace with better record (existing record is removed)
                    name_to_record[name_normalized] = better_record
                    duplicates_removed += 1
                    logger.debug(f"Replaced duplicate for name '{name}' with better record (removed existing)")
                else:
                    # Keep existing record (current record is removed)
                    duplicates_removed += 1
                    logger.debug(f"Kept existing record for name '{name}', discarded duplicate")
            else:
                # First occurrence of this name
                name_to_record[name_normalized] = record
        
        expected_unique_count = len(name_to_record)
        expected_duplicates = len(all_records) - expected_unique_count
        
        logger.info(f"✅ Deduplication complete: {len(all_records)} records → {expected_unique_count} unique names")
        logger.info(f"   Removed {duplicates_removed} duplicate records")
        
        if duplicates_removed != expected_duplicates:
            logger.warning(f"⚠️ Duplicate count mismatch: expected {expected_duplicates}, counted {duplicates_removed}")
        else:
            logger.info(f"   ✓ Duplicate count verified: {duplicates_removed} = {len(all_records)} - {expected_unique_count}")
        
        # Third pass: transform and prepare for migration
        logger.info("Transforming records for migration...")
        
        migrated_data = []
        for record in name_to_record.values():
            new_record = {}
            
            # Copy all fields except thread_id and internal Milvus fields
            for key, value in record.items():
                # Skip thread_id and internal Milvus fields (start with $)
                if key != "thread_id" and not key.startswith("$"):
                    new_record[key] = value
            
            # Handle conversation_id: preserve existing, or use thread_id as fallback
            if "conversation_id" in record and record.get("conversation_id"):
                # conversation_id already exists, keep it
                new_record["conversation_id"] = record["conversation_id"]
            elif "thread_id" in record and record.get("thread_id"):
                # Use thread_id as fallback if conversation_id doesn't exist
                new_record["conversation_id"] = record["thread_id"]
            else:
                # Neither exists, set to None
                new_record["conversation_id"] = None
            
            # Ensure all required fields exist
            for field in new_fields:
                if field.name not in new_record:
                    if field.nullable:
                        new_record[field.name] = None
                    elif field.dtype == DataType.VARCHAR:
                        new_record[field.name] = ""
                    elif field.dtype == DataType.FLOAT:
                        new_record[field.name] = 0.0
                    else:
                        new_record[field.name] = None
            
            migrated_data.append(new_record)
        
        # Insert all deduplicated records into new collection
        logger.info(f"Inserting {len(migrated_data)} deduplicated records into new collection...")
        
        # Remove candidate_id from data since it's auto-generated
        for record in migrated_data:
            if "candidate_id" in record:
                del record["candidate_id"]
        
        # Insert in batches to avoid memory issues
        insert_batch_size = 1000
        total_migrated = 0
        
        for i in range(0, len(migrated_data), insert_batch_size):
            batch = migrated_data[i:i + insert_batch_size]
            logger.info(f"Inserting batch {i//insert_batch_size + 1} ({len(batch)} records)...")
            
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
        logger.info(f"Records migrated (after deduplication): {total_migrated}")
        logger.info(f"Duplicates removed: {duplicates_removed}")
        
        if new_count == total_migrated:
            logger.info("✅ Migration verified! All deduplicated records are in the new collection.")
            logger.info(f"   Original: {old_count} → Deduplicated: {new_count} (removed {old_count - new_count} duplicates)")
        elif new_count < total_migrated:
            logger.warning(f"⚠️ Some records may not have been persisted: {new_count} vs {total_migrated} migrated")
        else:
            logger.warning(f"⚠️ Unexpected: new collection has more records than migrated")
        
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = migrate_candidates_data()
    if success:
        print("✅ Successfully migrated data!")
        print("📝 Next steps:")
        print("   1. Update config to use CN_candidates_v3")
        print("   2. Update src/candidate_store.py to remove thread_id from schema")
        print("   3. Update all code references from thread_id to conversation_id")
        print("   4. Test the new collection")
    else:
        print("❌ Migration failed!")
        sys.exit(1)
