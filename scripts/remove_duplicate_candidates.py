#!/usr/bin/env python3
"""Remove duplicate candidates by name, keeping the latest one by updated_at.

This script:
1. Queries all candidates from CN_candidates collection
2. Groups candidates by name
3. For each duplicate group, keeps the candidate with the latest updated_at
4. Deletes all older duplicates
"""

import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from pymilvus import MilvusClient
from src.config import get_zilliz_config
from src.global_logger import logger


def parse_datetime(date_str: str) -> datetime:
    """Parse ISO format datetime string."""
    try:
        # Try ISO format with T separator
        if 'T' in date_str:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        # Try space-separated format
        return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
    except Exception as e:
        logger.warning(f"Failed to parse datetime '{date_str}': {e}")
        return datetime.min


def remove_duplicates(collection_name: str = "CN_candidates", dry_run: bool = True):
    """Remove duplicate candidates by name, keeping the latest by updated_at.
    
    Args:
        collection_name: Name of the collection to process
        dry_run: If True, only report what would be deleted without actually deleting
    """
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
    
    logger.info(f"Connecting to collection: {collection_name}")
    
    # Query all candidates with name and updated_at
    # Milvus has a limit of 16384 for query results
    logger.info("Querying all candidates...")
    try:
        all_candidates = client.query(
            collection_name=collection_name,
            filter='name != ""',
            output_fields=["candidate_id", "name", "updated_at"],
            limit=16384  # Maximum allowed by Milvus
        )
        logger.info(f"Queried {len(all_candidates)} candidates (max 16384 due to Milvus limit)")
        if len(all_candidates) == 16384:
            logger.warning("Query returned maximum limit. There may be more candidates. Consider running multiple times with additional filters.")
    except Exception as e:
        logger.error(f"Failed to query candidates: {e}")
        return
    
    logger.info(f"Found {len(all_candidates)} candidates with names")
    
    # Group by name (normalize by stripping whitespace)
    name_groups = defaultdict(list)
    for candidate in all_candidates:
        name = candidate.get("name")
        if name and name.strip():
            name_groups[name.strip()].append(candidate)
    
    # Find duplicates
    duplicates_to_delete = []
    kept_candidates = []
    
    for name, candidates in name_groups.items():
        if len(candidates) > 1:
            # Sort by updated_at (latest first), handle None/empty updated_at
            candidates.sort(
                key=lambda c: parse_datetime(c.get("updated_at") or "") if c.get("updated_at") else datetime.min,
                reverse=True
            )
            
            # Keep the latest one
            latest = candidates[0]
            kept_candidates.append(latest)
            
            # Mark others for deletion
            for candidate in candidates[1:]:
                duplicates_to_delete.append(candidate)
            
            logger.info(
                f"Name '{name}': {len(candidates)} duplicates found. "
                f"Keeping candidate_id={latest.get('candidate_id')} "
                f"(updated_at={latest.get('updated_at')}), "
                f"deleting {len(candidates) - 1} older ones"
            )
    
    logger.info(f"\nSummary:")
    logger.info(f"  Total candidates with names: {len(all_candidates)}")
    logger.info(f"  Unique names: {len(name_groups)}")
    logger.info(f"  Names with duplicates: {len([n for n, c in name_groups.items() if len(c) > 1])}")
    logger.info(f"  Candidates to keep: {len(kept_candidates)}")
    logger.info(f"  Candidates to delete: {len(duplicates_to_delete)}")
    
    if not duplicates_to_delete:
        logger.info("No duplicates found. Nothing to delete.")
        return
    
    if dry_run:
        logger.info("\n=== DRY RUN MODE ===")
        logger.info("The following candidates would be deleted:")
        for candidate in duplicates_to_delete[:10]:  # Show first 10
            logger.info(
                f"  candidate_id={candidate.get('candidate_id')}, "
                f"name={candidate.get('name')}, "
                f"updated_at={candidate.get('updated_at')}"
            )
        if len(duplicates_to_delete) > 10:
            logger.info(f"  ... and {len(duplicates_to_delete) - 10} more")
        logger.info("\nTo actually delete, run with --execute flag")
    else:
        # Delete duplicates
        logger.info("\n=== DELETING DUPLICATES ===")
        candidate_ids_to_delete = [c["candidate_id"] for c in duplicates_to_delete]
        
        # Delete in batches to avoid overwhelming the API
        batch_size = 100
        deleted_count = 0
        
        for i in range(0, len(candidate_ids_to_delete), batch_size):
            batch = candidate_ids_to_delete[i:i + batch_size]
            try:
                # Use delete with filter expression - Milvus uses 'in' operator
                quoted_ids = [f'"{cid}"' for cid in batch]
                filter_expr = f"candidate_id in [{', '.join(quoted_ids)}]"
                result = client.delete(
                    collection_name=collection_name,
                    filter=filter_expr
                )
                deleted_count += len(batch)
                logger.info(f"Deleted batch {i // batch_size + 1}: {len(batch)} candidates")
            except Exception as e:
                logger.error(f"Failed to delete batch {i // batch_size + 1}: {e}")
        
        logger.info(f"\nSuccessfully deleted {deleted_count} duplicate candidates")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Remove duplicate candidates by name, keeping the latest by updated_at"
    )
    parser.add_argument(
        "--collection",
        default="CN_candidates",
        help="Collection name (default: CN_candidates)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete duplicates (default is dry-run)"
    )
    
    args = parser.parse_args()
    
    remove_duplicates(
        collection_name=args.collection,
        dry_run=not args.execute
    )

