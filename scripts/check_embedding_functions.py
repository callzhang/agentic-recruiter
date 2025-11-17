#!/usr/bin/env python3
"""Check if collections have built-in embedding functions enabled on the server."""
import sys
from pathlib import Path
import json

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymilvus import MilvusClient, Collection, connections
from src.config import get_zilliz_config
from src.global_logger import logger

def check_collection_detailed(collection_name: str):
    """Check collection schema and functions in detail."""
    zilliz_config = get_zilliz_config()
    
    endpoint = zilliz_config["endpoint"]
    client = MilvusClient(
        uri=endpoint,
        token=zilliz_config.get("token", ''),
        user=zilliz_config["user"],
        password=zilliz_config["password"],
        secure=endpoint.startswith("https://"),
    )
    
    has_functions = False
    
    try:
        if not client.has_collection(collection_name=collection_name):
            logger.warning(f"❌ Collection '{collection_name}' does not exist")
            return False
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Collection: {collection_name}")
        logger.info(f"{'='*60}")
        
        # Get full collection description
        desc = client.describe_collection(collection_name=collection_name)
        logger.info(f"\nCollection description keys: {list(desc.keys())}")
        
        # Check functions directly from describe_collection
        if 'functions' in desc:
            functions = desc['functions']
            logger.info(f"\nFunctions from describe_collection: {len(functions) if functions else 0}")
            if functions:
                for func in functions:
                    logger.info(f"  ✅ Function found: {func}")
                    logger.info(f"     Type: {func.get('function_type', 'unknown')}")
                    logger.info(f"     Name: {func.get('name', 'unknown')}")
                    if 'input_field_names' in func:
                        logger.info(f"     Input fields: {func['input_field_names']}")
                    if 'output_field_names' in func:
                        logger.info(f"     Output fields: {func['output_field_names']}")
                    if 'params' in func:
                        logger.info(f"     Params: {func['params']}")
                    has_functions = True
            else:
                logger.info("  ❌ No functions in describe_collection response")
        
        # Try to get collection object (if using pymilvus Collection API)
        try:
            # Connect using connections API
            endpoint = zilliz_config["endpoint"]
            connections.connect(
                alias="default",
                uri=endpoint,
                token=zilliz_config.get("token", ''),
                user=zilliz_config["user"],
                password=zilliz_config["password"],
                secure=endpoint.startswith("https://"),
            )
            collection = Collection(collection_name)
            schema = collection.schema
            
            logger.info(f"\nSchema fields: {len(schema.fields)}")
            for field in schema.fields:
                logger.info(f"  - {field.name}: {field.dtype}")
            
            # Check if schema has functions
            if hasattr(schema, 'functions') and schema.functions:
                logger.info(f"\n✅ Found {len(schema.functions)} function(s) in schema:")
                for func in schema.functions:
                    logger.info(f"    Function: {func}")
                    if hasattr(func, 'function_type'):
                        logger.info(f"      Type: {func.function_type}")
                    if hasattr(func, 'input_field_names'):
                        logger.info(f"      Input fields: {func.input_field_names}")
                    if hasattr(func, 'output_field_names'):
                        logger.info(f"      Output fields: {func.output_field_names}")
                    has_functions = True
            else:
                logger.info(f"\n❌ No functions found in schema")
                logger.info(f"   Schema attributes: {dir(schema)}")
                
        except Exception as e:
            logger.warning(f"Could not use Collection API: {e}")
            logger.info("Trying MilvusClient describe_collection...")
            
            # Try to get more details from describe_collection
            desc_str = json.dumps(desc, indent=2, default=str)
            logger.info(f"\nFull description:\n{desc_str}")
            
            # Check if functions are mentioned in the description
            if 'functions' in desc_str.lower() or 'function' in desc_str.lower():
                logger.info("⚠️  'function' mentioned in description, but couldn't parse")
                logger.info("   This might indicate functions exist but API access differs")
        
        return has_functions
        
    except Exception as e:
        logger.exception(f"Error checking {collection_name}: {e}")
        return False
    finally:
        try:
            client.close()
            connections.disconnect("default")
        except:
            pass

def main():
    """Check both collections."""
    zilliz_config = get_zilliz_config()
    
    collections = [
        (zilliz_config.get("candidate_collection_name", "CN_candidates_v3"), "Candidates"),
        (zilliz_config.get("job_collection_name", "CN_jobs"), "Jobs")
    ]
    
    results = {}
    for collection_name, display_name in collections:
        logger.info(f"\n{'#'*60}")
        logger.info(f"Checking {display_name} Collection: {collection_name}")
        logger.info(f"{'#'*60}")
        results[collection_name] = check_collection_detailed(collection_name)
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    for (collection_name, display_name), has_functions in zip(collections, results.values()):
        status = "✅ HAS embedding functions" if has_functions else "❌ NO embedding functions"
        logger.info(f"{display_name} ({collection_name}): {status}")
    
    return results

if __name__ == "__main__":
    main()

