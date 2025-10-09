#!/usr/bin/env python3
"""Zilliz collection management utility."""
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
from pymilvus import MilvusClient, DataType, CollectionSchema, FieldSchema, Collection, connections
from src.config import settings
from src.global_logger import logger


def check_milvus_version():
    """Check Milvus server version."""
    client = MilvusClient(
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    try:
        version_info = client.get_server_version()
        logger.info(f"Milvus server version: {version_info}")
        
        # Check if add_collection_field is available
        if hasattr(client, 'add_collection_field'):
            logger.info("✅ add_collection_field method is available in client")
        else:
            logger.error("❌ add_collection_field method is NOT available in client")
        
        return version_info
    except Exception as e:
        logger.error(f"Failed to get version info: {e}")
        return None


def alter_collection_fields(collection_name: str):
    """Alter collection fields using MilvusClient."""
    client = MilvusClient(
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    try:
        if not client.has_collection(collection_name):
            logger.error(f"Collection {collection_name} does not exist")
            return False
        
        logger.info(f"Found collection: {collection_name}")
        
        # Fields that can be altered (VarChar fields)
        varchar_fields = [
            "name",
            "job_applied", 
            "last_message",
            "resume_text",
            "updated_at"
        ]
        
        logger.info(f"Attempting to alter VarChar fields: {varchar_fields}")
        
        # Alter each VarChar field to increase max_length
        for field_name in varchar_fields:
            try:
                client.alter_collection_field(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_params={
                        "max_length": 10000  # Increase to 10k characters
                    }
                )
                logger.info(f"✅ Altered field '{field_name}' max_length to 10000")
            except Exception as e:
                logger.error(f"❌ Failed to alter field '{field_name}': {e}")
        
        logger.info("✅ Field alterations completed!")
        return True
        
    except Exception as e:
        logger.error(f"Failed to alter collection: {e}")
        return False


def create_collection_with_all_fields(collection_name: str):
    """Create collection with all possible fields."""
    # Connect using connections first
    connections.connect(
        alias="default",
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    client = MilvusClient(
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    try:
        if client.has_collection(collection_name):
            logger.info(f"Collection {collection_name} already exists")
            return True
        
        logger.info(f"Creating collection: {collection_name}")
        
        # Create collection schema with ALL possible fields
        fields = [
            # Core fields
            FieldSchema(name="candidate_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
            FieldSchema(name="resume_vector", dtype=DataType.FLOAT_VECTOR, dim=settings.ZILLIZ_EMBEDDING_DIM),
            
            # Basic candidate info
            FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=200, nullable=True),
            FieldSchema(name="job_applied", dtype=DataType.VARCHAR, max_length=128, nullable=True),
            FieldSchema(name="last_message", dtype=DataType.VARCHAR, max_length=2048, nullable=True),
            FieldSchema(name="resume_text", dtype=DataType.VARCHAR, max_length=8192, nullable=True),
            FieldSchema(name="scores", dtype=DataType.JSON, nullable=True),
            FieldSchema(name="metadata", dtype=DataType.JSON, nullable=True),
            FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64, nullable=True),
            
            # Your requested fields
            FieldSchema(name="stage", dtype=DataType.VARCHAR, max_length=20, nullable=True),
            FieldSchema(name="full_resume", dtype=DataType.VARCHAR, max_length=10000, nullable=True),
            FieldSchema(name="thread_id", dtype=DataType.VARCHAR, max_length=100, nullable=True),
            
            # Additional useful fields
            FieldSchema(name="candidate_status", dtype=DataType.VARCHAR, max_length=50, nullable=True),
            FieldSchema(name="interview_stage", dtype=DataType.VARCHAR, max_length=30, nullable=True),
            FieldSchema(name="contact_info", dtype=DataType.VARCHAR, max_length=500, nullable=True),
            FieldSchema(name="notes", dtype=DataType.VARCHAR, max_length=2000, nullable=True),
            FieldSchema(name="priority_score", dtype=DataType.FLOAT, nullable=True),
            FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=100, nullable=True),
            FieldSchema(name="tags", dtype=DataType.VARCHAR, max_length=500, nullable=True),
        ]
        
        schema = CollectionSchema(fields, description="Complete candidate profiles with all fields")
        
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
        return True
        
    except Exception as e:
        logger.error(f"Failed to create collection: {e}")
        return False


def list_collections():
    """List all collections."""
    client = MilvusClient(
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    try:
        collections = client.list_collections()
        logger.info(f"Available collections: {collections}")
        
        for collection_name in collections:
            info = client.describe_collection(collection_name)
            fields = [field.get('name') for field in info.get('fields', [])]
            logger.info(f"  - {collection_name}: {fields}")
        
        return collections
    except Exception as e:
        logger.error(f"Failed to list collections: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Zilliz collection management utility")
    parser.add_argument("action", choices=[
        "version", "list", "alter", "create", "migrate"
    ], help="Action to perform")
    parser.add_argument("--collection", default=settings.ZILLIZ_COLLECTION_NAME, 
                       help="Collection name")
    parser.add_argument("--new-collection", help="New collection name for create/migrate")
    
    args = parser.parse_args()
    
    if args.action == "version":
        check_milvus_version()
    elif args.action == "list":
        list_collections()
    elif args.action == "alter":
        alter_collection_fields(args.collection)
    elif args.action == "create":
        collection_name = args.new_collection or f"{args.collection}_v2"
        create_collection_with_all_fields(collection_name)
    elif args.action == "migrate":
        if not args.new_collection:
            logger.error("--new-collection is required for migrate action")
            return
        # Import and run migration
        from migrate_candidates_data import migrate_candidates_data
        migrate_candidates_data()


if __name__ == "__main__":
    main()
