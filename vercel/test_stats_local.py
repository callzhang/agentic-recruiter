#!/usr/bin/env python3
"""Test script to run FastAPI stats service locally."""

import sys
import os

# Add parent directory to path to access config
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# Try to load environment variables from config/secrets.yaml if available
try:
    import yaml
    secrets_path = os.path.join(parent_dir, "config", "secrets.yaml")
    if os.path.exists(secrets_path):
        with open(secrets_path, 'r') as f:
            secrets = yaml.safe_load(f)
            zilliz_config = secrets.get("zilliz", {})
            # Set environment variables from config
            os.environ.setdefault("ZILLIZ_ENDPOINT", zilliz_config.get("endpoint", ""))
            os.environ.setdefault("ZILLIZ_USER", zilliz_config.get("user", ""))
            os.environ.setdefault("ZILLIZ_PASSWORD", zilliz_config.get("password", ""))
            os.environ.setdefault("ZILLIZ_CANDIDATE_COLLECTION_NAME", zilliz_config.get("candidate_collection_name", "CN_candidates"))
            os.environ.setdefault("ZILLIZ_JOB_COLLECTION_NAME", zilliz_config.get("job_collection_name", "CN_jobs"))
            os.environ.setdefault("ZILLIZ_EMBEDDING_DIM", str(zilliz_config.get("embedding_dim", 1536)))
            print("Loaded Zilliz config from config/secrets.yaml")
except Exception as e:
    print(f"Could not load config/secrets.yaml: {e}")
    print("Make sure environment variables are set manually or use a .env file")

# Add the api directory to the path
api_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, api_dir)

if __name__ == "__main__":
    import uvicorn
    print("Starting FastAPI server on http://localhost:8000")
    print("Test endpoint: http://localhost:8000/api/stats")
    print("API docs: http://localhost:8000/docs")
    # Use import string for reload to work
    uvicorn.run("api.stats:app", host="0.0.0.0", port=8000, log_level="info", reload=True)

