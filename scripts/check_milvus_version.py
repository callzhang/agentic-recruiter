#!/usr/bin/env python3
"""Check Milvus server version."""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymilvus import MilvusClient, connections
from src.config import settings
from src.global_logger import logger


def check_milvus_version():
    """Check Milvus server version."""
    
    # Create MilvusClient
    client = MilvusClient(
        uri=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        secure=True
    )
    
    try:
        # Get server version
        version_info = client.get_server_version()
        logger.info(f"Milvus server version: {version_info}")
        
        # Also try to get build info
        try:
            build_info = client.get_build_info()
            logger.info(f"Milvus build info: {build_info}")
        except Exception as e:
            logger.warning(f"Could not get build info: {e}")
        
        # Check if add_collection_field is available
        try:
            # Try to call the method to see if it exists
            import inspect
            if hasattr(client, 'add_collection_field'):
                logger.info("✅ add_collection_field method is available in client")
            else:
                logger.error("❌ add_collection_field method is NOT available in client")
        except Exception as e:
            logger.error(f"Error checking method availability: {e}")
        
        return version_info
        
    except Exception as e:
        logger.error(f"Failed to get version info: {e}")
        return None


if __name__ == "__main__":
    version = check_milvus_version()
    if version:
        print(f"✅ Milvus server version: {version}")
        print("📝 This should help determine if add_collection_field is supported")
    else:
        print("❌ Could not get Milvus version")
        sys.exit(1)
