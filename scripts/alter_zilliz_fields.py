#!/usr/bin/env python3
"""Script to alter Zilliz collection fields using the correct Milvus API."""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymilvus import MilvusClient
from src.config import settings
from src.global_logger import logger


def alter_collection_fields():
    """Alter collection fields using MilvusClient."""
    
    # Create MilvusClient with your Zilliz credentials
    client = MilvusClient(
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    collection_name = settings.ZILLIZ_COLLECTION_NAME
    
    try:
        # Check if collection exists
        if not client.has_collection(collection_name):
            logger.error(f"Collection {collection_name} does not exist")
            return False
        
        logger.info(f"Found collection: {collection_name}")
        
        # Get collection info
        collection_info = client.describe_collection(collection_name)
        logger.info(f"Collection fields:")
        for field in collection_info.get('fields', []):
            logger.info(f"  - {field.get('name')}: {field.get('type')}")
        
        # Fields that can be altered (VarChar fields)
        varchar_fields = [
            "name",
            "job_applied", 
            "last_message",
            "resume_text",
            "updated_at"
        ]
        
        logger.info(f"Attempting to alter VarChar fields: {varchar_fields}")
        
        # Alter each VarChar field to increase max_length (this is the only thing we can alter)
        for field_name in varchar_fields:
            try:
                # Increase max_length to a larger value
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
                # Continue with other fields even if one fails
        
        logger.info("✅ Field alterations completed!")
        
        # Show updated collection info
        updated_info = client.describe_collection(collection_name)
        logger.info(f"Updated collection fields:")
        for field in updated_info.get('fields', []):
            field_name = field.get('name')
            field_type = field.get('type')
            max_length = field.get('params', {}).get('max_length', 'N/A')
            logger.info(f"  - {field_name}: {field_type} (max_length: {max_length})")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to alter collection: {e}")
        return False


if __name__ == "__main__":
    success = alter_collection_fields()
    if success:
        print("✅ Successfully altered collection fields!")
        print("📝 Note: Only max_length can be altered for VarChar fields")
        print("📝 Nullable property cannot be changed after collection creation")
    else:
        print("❌ Failed to alter collection fields!")
        sys.exit(1)
