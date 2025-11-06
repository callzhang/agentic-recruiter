#!/usr/bin/env python3
"""Migrate data from CN_jobs to CN_jobs_2 collection."""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymilvus import (
    MilvusClient,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    connections,
    utility,
)
from src.config import settings
from src.global_logger import logger


def migrate_jobs_to_cn_jobs_2():
    """Migrate data from CN_jobs to CN_jobs_2 collection.
    
    This script:
    1. Creates a new collection CN_jobs_2 with the same schema (including candidate_filters)
    2. Migrates all existing data from CN_jobs to CN_jobs_2
    3. Sets candidate_filters to None for existing records if not present
    """
    
    # Create MilvusClient
    client = MilvusClient(
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    old_collection_name = "CN_jobs"
    new_collection_name = "CN_jobs_2"
    
    try:
        # Check if old collection exists
        if not client.has_collection(old_collection_name):
            logger.error(f"Source collection {old_collection_name} does not exist")
            return False
        
        logger.info(f"Found source collection: {old_collection_name}")
        
        # Get old collection info
        old_info = client.describe_collection(old_collection_name)
        old_fields = {field.get('name'): field for field in old_info.get('fields', [])}
        
        logger.info(f"Old collection fields: {list(old_fields.keys())}")
        
        # Check if new collection already exists
        if client.has_collection(new_collection_name):
            logger.warning(f"Target collection {new_collection_name} already exists")
            logger.info(f"Dropping existing collection {new_collection_name}...")
            client.drop_collection(new_collection_name)
        
        # Create new collection with the same schema (including candidate_filters)
        logger.info(f"Creating new collection {new_collection_name}...")
        
        # Define schema with candidate_filters field
        new_fields = [
            FieldSchema(name="job_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
            FieldSchema(name="position", dtype=DataType.VARCHAR, max_length=200),
            FieldSchema(name="background", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
            FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
            FieldSchema(name="responsibilities", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
            FieldSchema(name="requirements", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
            FieldSchema(name="target_profile", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
            FieldSchema(name="keywords", dtype=DataType.JSON, nullable=True),
            FieldSchema(name="drill_down_questions", dtype=DataType.VARCHAR, max_length=65000, nullable=True),
            # Candidate search filters field
            FieldSchema(name="candidate_filters", dtype=DataType.JSON, nullable=True),
            FieldSchema(name="job_embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.ZILLIZ_EMBEDDING_DIM),
            FieldSchema(name="created_at", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64),
        ]
        
        schema = CollectionSchema(
            new_fields,
            description="Job profiles for Boss直聘 automation (CN_jobs_2)"
        )
        
        # Create collection using Collection API
        connections.connect(
            alias="default",
            uri=settings.ZILLIZ_ENDPOINT,
            user=settings.ZILLIZ_USER,
            password=settings.ZILLIZ_PASSWORD,
            secure=True
        )
        
        new_collection = Collection(new_collection_name, schema)
        
        # Create indexes
        index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "IP",
            "params": {},
        }
        new_collection.create_index(field_name="job_embedding", index_params=index_params)
        new_collection.create_index(field_name="job_id")
        new_collection.create_index(field_name="position")
        
        logger.info(f"✅ Created new collection {new_collection_name}")
        
        # Query all data from old collection
        logger.info("Querying all data from old collection...")
        
        batch_size = 1000
        offset = 0
        total_migrated = 0
        
        while True:
            logger.info(f"Querying batch starting at offset {offset}...")
            
            # Query batch of data
            results = client.query(
                collection_name=old_collection_name,
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
                new_record = {}
                
                # Copy all existing fields
                for field_name in old_fields.keys():
                    if field_name in record:
                        new_record[field_name] = record[field_name]
                
                # Add candidate_filters field if it doesn't exist in old collection
                if "candidate_filters" not in new_record:
                    new_record["candidate_filters"] = None
                
                migrated_data.append(new_record)
            
            # Insert batch into new collection
            if migrated_data:
                logger.info(f"Inserting {len(migrated_data)} records into new collection...")
                
                # Load collection before inserting
                new_collection.load()
                
                new_collection.insert(migrated_data)
                new_collection.flush()
                
                logger.info(f"✅ Inserted batch: {len(migrated_data)} records")
                total_migrated += len(migrated_data)
            
            # Check if we got fewer results than batch_size (end of data)
            if len(results) < batch_size:
                logger.info("Reached end of data")
                break
            
            offset += batch_size
        
        logger.info(f"✅ Migration completed! Total records migrated: {total_migrated}")
        
        # Verify migration
        logger.info("Verifying migration...")
        old_count = len(client.query(
            collection_name=old_collection_name,
            filter="",
            output_fields=["job_id"],
            limit=10000  # Get count by querying all
        ))
        
        new_count = len(client.query(
            collection_name=new_collection_name,
            filter="",
            output_fields=["job_id"],
            limit=10000
        ))
        
        logger.info(f"Old collection ({old_collection_name}) records: {old_count}")
        logger.info(f"New collection ({new_collection_name}) records: {new_count}")
        
        if old_count == new_count:
            logger.info("✅ Migration verified successfully! Record counts match.")
        else:
            logger.warning(f"⚠️ Record count mismatch: {old_count} vs {new_count}")
        
        return True
        
    except Exception as e:
        logger.exception(f"Migration failed: {e}")
        return False
    finally:
        # Disconnect
        try:
            connections.disconnect("default")
        except:
            pass


if __name__ == "__main__":
    success = migrate_jobs_to_cn_jobs_2()
    if success:
        print(f"\n✅ Successfully migrated CN_jobs to CN_jobs_2!")
        print(f"\n📝 Next steps:")
        print(f"1. Update src/jobs_store.py to use CN_jobs_2 as collection name (line 282)")
        print(f"2. Test the new collection before switching")
        print(f"3. Once verified, you can optionally drop the old CN_jobs collection")
    else:
        print("❌ Migration failed!")
        sys.exit(1)

