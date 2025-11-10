#!/usr/bin/env python3
"""Migrate data from CN_candidates to CN_candidates_v3 (removing thread_id, using conversation_id)."""

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
    """Migrate data from old collection to new collection, replacing thread_id with conversation_id."""
    
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
            FieldSchema(name="full_resume", dtype=DataType.VARCHAR, max_length=10000, nullable=True),
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
        
        batch_size = 1000
        offset = 0
        total_migrated = 0
        
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
                logger.info("No more data to migrate")
                break
            
            logger.info(f"Retrieved {len(results)} records in this batch")
            
            # Transform data: copy thread_id to conversation_id, remove thread_id
            migrated_data = []
            for record in results:
                new_record = {}
                
                # Copy all fields except thread_id
                for key, value in record.items():
                    if key != "thread_id":
                        new_record[key] = value
                
                # Copy thread_id value to conversation_id if it exists
                if "thread_id" in record and record["thread_id"]:
                    new_record["conversation_id"] = record["thread_id"]
                elif "conversation_id" not in new_record:
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
            
            # Insert batch into new collection
            if migrated_data:
                logger.info(f"Inserting {len(migrated_data)} records into new collection...")
                
                # Remove candidate_id from data since it's auto-generated
                for record in migrated_data:
                    if "candidate_id" in record:
                        del record["candidate_id"]
                
                insert_result = client.insert(
                    collection_name=new_collection,
                    data=migrated_data
                )
                
                logger.info(f"✅ Inserted batch: {insert_result}")
                total_migrated += len(migrated_data)
            
            # Check if we got fewer results than batch_size (end of data)
            if len(results) < batch_size:
                logger.info("Reached end of data")
                break
            
            offset += batch_size
        
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
            logger.info("✅ Migration verified! All migrated records are in the new collection.")
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
