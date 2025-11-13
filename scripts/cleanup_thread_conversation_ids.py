#!/usr/bin/env python3
"""Clean up old conversation_id values that start with 'thread_'.

This script finds all candidates with conversation_id starting with 'thread_'
and sets them to null.
"""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymilvus import MilvusClient
from src.config import settings
from src.global_logger import logger
from src.candidate_store import _readable_fields

def cleanup_thread_conversation_ids():
    """Find and update all candidates with conversation_id starting with 'thread_'."""
    
    # Create MilvusClient
    token = getattr(settings, 'ZILLIZ_TOKEN', None)
    
    if token:
        client = MilvusClient(
            uri=settings.ZILLIZ_ENDPOINT,
            token=token,
            secure=settings.ZILLIZ_ENDPOINT.startswith("https://"),
        )
    else:
        client = MilvusClient(
            uri=settings.ZILLIZ_ENDPOINT,
            user=settings.ZILLIZ_USER,
            password=settings.ZILLIZ_PASSWORD,
            secure=settings.ZILLIZ_ENDPOINT.startswith("https://"),
        )
    
    collection_name = settings.ZILLIZ_COLLECTION_NAME
    
    try:
        # Check if collection exists
        if not client.has_collection(collection_name):
            logger.error(f"Collection {collection_name} does not exist")
            return False
        
        logger.info(f"Querying candidates with conversation_id starting with 'thread_'...")
        
        # Query all candidates where conversation_id starts with 'thread_'
        # Note: Milvus doesn't support LIKE queries directly, so we need to query all and filter
        # For better performance, we'll query in batches
        filter_expr = 'conversation_id != ""'
        
        # Query all candidates with non-empty conversation_id
        results = client.query(
            collection_name=collection_name,
            filter=filter_expr,
            output_fields=_readable_fields,
            limit=10000,  # Adjust if you have more records
        )
        
        # Filter for conversation_id starting with 'thread_'
        candidates_to_update = [
            r for r in results 
            if r.get('conversation_id') and str(r.get('conversation_id', '')).startswith('thread_')
        ]
        
        logger.info(f"Found {len(candidates_to_update)} candidates with conversation_id starting with 'thread_'")
        
        if not candidates_to_update:
            logger.info("No candidates to update")
            return True
        
        # Update each candidate
        updated_count = 0
        for candidate in candidates_to_update:
            candidate_id = candidate.get('candidate_id')
            if not candidate_id:
                logger.warning(f"Skipping candidate without candidate_id: {candidate}")
                continue
            
            # Prepare update data - set conversation_id to None
            update_data = {
                'candidate_id': candidate_id,
                'conversation_id': None,
            }
            
            try:
                # Use upsert with partial_update=True to update only conversation_id
                client.upsert(
                    collection_name=collection_name,
                    data=[update_data],
                    partial_update=True,
                )
                updated_count += 1
                logger.debug(f"Updated candidate {candidate_id}: {candidate.get('name', 'unknown')}")
            except Exception as exc:
                logger.error(f"Failed to update candidate {candidate_id}: {exc}")
        
        # Flush to ensure changes are persisted
        client.flush(collection_name=collection_name)
        
        logger.info(f"✅ Successfully updated {updated_count} candidates")
        logger.info(f"Set conversation_id to null for {updated_count} records")
        
        return True
        
    except Exception as exc:
        logger.exception(f"Failed to cleanup conversation_ids: {exc}")
        return False

if __name__ == "__main__":
    success = cleanup_thread_conversation_ids()
    sys.exit(0 if success else 1)

