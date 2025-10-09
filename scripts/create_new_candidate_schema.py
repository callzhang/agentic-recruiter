#!/usr/bin/env python3
"""Create new candidate collection with updated schema."""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymilvus import MilvusClient, DataType, CollectionSchema, FieldSchema, Collection, connections
from src.config import settings
from src.global_logger import logger


def create_new_candidate_schema():
    """Create new collection with updated schema."""
    
    # Connect using connections first
    connections.connect(
        alias="default",
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    # Create MilvusClient
    client = MilvusClient(
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    collection_name = "CN_candidates_v3"
    
    try:
        # Check if collection already exists
        if client.has_collection(collection_name):
            logger.info(f"Collection {collection_name} already exists. Dropping it.")
            client.drop_collection(collection_name)
        
        logger.info(f"Creating new collection: {collection_name}")
        
        # Create collection schema with updated fields
        fields = [
            # Primary key - UUID generated, not used for UI
            FieldSchema(name="candidate_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
            FieldSchema(name="resume_vector", dtype=DataType.FLOAT_VECTOR, dim=settings.ZILLIZ_EMBEDDING_DIM),
            
            # UI chat_id - used for UI operations
            FieldSchema(name="chat_id", dtype=DataType.VARCHAR, max_length=100, nullable=True),
            
            # Basic candidate info
            FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=200, nullable=True),
            FieldSchema(name="job_applied", dtype=DataType.VARCHAR, max_length=128, nullable=True),
            FieldSchema(name="last_message", dtype=DataType.VARCHAR, max_length=2048, nullable=True),
            FieldSchema(name="resume_text", dtype=DataType.VARCHAR, max_length=25000, nullable=True),
            FieldSchema(name="metadata", dtype=DataType.JSON, nullable=True),
            FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64, nullable=True),
            
            # Analysis field (renamed from scores)
            FieldSchema(name="analysis", dtype=DataType.JSON, nullable=True),
            
            # Additional fields
            FieldSchema(name="stage", dtype=DataType.VARCHAR, max_length=20, nullable=True),
            FieldSchema(name="full_resume", dtype=DataType.VARCHAR, max_length=10000, nullable=True),
            FieldSchema(name="thread_id", dtype=DataType.VARCHAR, max_length=100, nullable=True),
        ]
        
        schema = CollectionSchema(fields, description="Candidate profiles with updated schema")
        
        # Create collection
        collection = Collection(name=collection_name, schema=schema)
        
        # Create index
        index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "IP",
            "params": {},
        }
        collection.create_index(field_name="resume_vector", index_params=index_params)
        
        # Load collection
        collection.load()
        
        logger.info(f"✅ Successfully created collection: {collection_name}")
        logger.info("📝 New collection schema:")
        for field in fields:
            nullable = getattr(field, 'nullable', False)
            logger.info(f"   - {field.name}: {field.dtype} (nullable: {nullable})")
        
        logger.info("📝 Key changes:")
        logger.info("   - candidate_id: Primary key with UUID (not used for UI)")
        logger.info("   - chat_id: New field for UI operations (nullable)")
        logger.info("   - analysis: Renamed from scores for analysis results")
        logger.info("   - resume_text: Increased to 25000 characters")
        
        logger.info("📝 Next steps:")
        logger.info(f"   1. Update config/secrets.yaml: collection_name: {collection_name}")
        logger.info("   2. Test the new collection")
        logger.info("   3. Delete old collection and rename this one")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to create collection: {e}")
        return False
    finally:
        connections.disconnect(alias="default")


if __name__ == "__main__":
    success = create_new_candidate_schema()
    if success:
        print("✅ Successfully created new collection with updated schema!")
        print("📝 Remember to update your config to use: CN_candidates_v3")
    else:
        print("❌ Failed to create new collection!")
        sys.exit(1)
