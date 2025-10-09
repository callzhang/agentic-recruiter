#!/usr/bin/env python3
"""Migrate data from CN_candidates to CN_candidates_v2."""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymilvus import MilvusClient, connections
from src.config import settings
from src.global_logger import logger


def migrate_candidates_data():
    """Migrate data from old collection to new collection."""
    
    # Create MilvusClient
    client = MilvusClient(
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    old_collection = "CN_candidates"
    new_collection = "CN_candidates_v2"
    
    try:
        # Check if both collections exist
        if not client.has_collection(old_collection):
            logger.error(f"Source collection {old_collection} does not exist")
            return False
            
        if not client.has_collection(new_collection):
            logger.error(f"Target collection {new_collection} does not exist")
            return False
        
        logger.info(f"Found both collections: {old_collection} -> {new_collection}")
        
        # Get collection info
        old_info = client.describe_collection(old_collection)
        new_info = client.describe_collection(new_collection)
        
        old_fields = {field.get('name'): field for field in old_info.get('fields', [])}
        new_fields = {field.get('name'): field for field in new_info.get('fields', [])}
        
        logger.info(f"Old collection fields: {list(old_fields.keys())}")
        logger.info(f"New collection fields: {list(new_fields.keys())}")
        
        # Query all data from old collection
        logger.info("Querying all data from old collection...")
        
        # Get total count first
        count_result = client.query(
            collection_name=old_collection,
            filter="",  # Empty filter to get all
            output_fields=["candidate_id"],
            limit=1
        )
        
        # Query all data (Milvus has a limit, so we'll do it in batches)
        batch_size = 1000
        offset = 0
        total_migrated = 0
        
        while True:
            logger.info(f"Querying batch starting at offset {offset}...")
            
            # Query batch of data
            results = client.query(
                collection_name=old_collection,
                filter="",  # Empty filter to get all
                output_fields=["*"],  # Get all fields
                limit=batch_size,
                offset=offset
            )
            
            if not results:
                logger.info("No more data to migrate")
                break
            
            logger.info(f"Retrieved {len(results)} records in this batch")
            
            # Transform data for new collection
            migrated_data = []
            for record in results:
                # Create new record with only fields that exist in new collection
                new_record = {}
                
                for field_name, field_info in new_fields.items():
                    if field_name in record:
                        # Field exists in old collection, copy it
                        new_record[field_name] = record[field_name]
                    elif field_name in ["stage", "full_resume", "thread_id"]:
                        # New fields, set to empty string
                        new_record[field_name] = ""
                    else:
                        # Other fields, set to None or appropriate default
                        if field_info.get('type') == 21:  # VARCHAR
                            new_record[field_name] = ""
                        elif field_info.get('type') == 10:  # FLOAT
                            new_record[field_name] = 0.0
                        else:
                            new_record[field_name] = None
                
                migrated_data.append(new_record)
            
            # Insert batch into new collection
            if migrated_data:
                logger.info(f"Inserting {len(migrated_data)} records into new collection...")
                
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
        old_count = client.query(
            collection_name=old_collection,
            filter="",
            output_fields=["candidate_id"],
            limit=1
        )
        
        new_count = client.query(
            collection_name=new_collection,
            filter="",
            output_fields=["candidate_id"],
            limit=1
        )
        
        logger.info(f"Old collection records: {len(old_count) if old_count else 0}")
        logger.info(f"New collection records: {len(new_count) if new_count else 0}")
        
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False


if __name__ == "__main__":
    success = migrate_candidates_data()
    if success:
        print("✅ Successfully migrated data from CN_candidates to CN_candidates_v2!")
        print("📝 You can now update your config to use CN_candidates_v2")
        print("📝 Remember to test the new collection before switching")
    else:
        print("❌ Migration failed!")
        sys.exit(1)
