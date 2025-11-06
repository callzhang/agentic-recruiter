"""Zilliz/Milvus-backed job profile store integration."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from .global_logger import logger
from .config import settings

# Job schema fields
fields = [
    # Primary key
    FieldSchema(name="job_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
    
    # Job content fields
    FieldSchema(name="position", dtype=DataType.VARCHAR, max_length=200),
    FieldSchema(name="background", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
    FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
    FieldSchema(name="responsibilities", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
    FieldSchema(name="requirements", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
    FieldSchema(name="target_profile", dtype=DataType.VARCHAR, max_length=5000, nullable=True),
    FieldSchema(name="keywords", dtype=DataType.JSON, nullable=True),
    FieldSchema(name="drill_down_questions", dtype=DataType.VARCHAR, max_length=65000, nullable=True),
    
    # Candidate search filters (stored as JSON)
    FieldSchema(name="candidate_filters", dtype=DataType.JSON, nullable=True),
    
    # Vector field for future semantic search
    FieldSchema(name="job_embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.ZILLIZ_EMBEDDING_DIM),
    
    # Timestamps
    FieldSchema(name="created_at", dtype=DataType.VARCHAR, max_length=64),
    FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64),
]

# List of all field names except "job_embedding"
_all_fields = [f.name for f in fields if f.name != "job_embedding"]


class JobsStore:
    """Zilliz/Milvus-backed job profile store."""
    
    def __init__(self, endpoint: str, user: str, password: str, collection_name: str = "CN_jobs"):
        self.endpoint = endpoint
        self.user = user
        self.password = password
        self.collection_name = collection_name
        self.collection: Optional[Collection] = None
        self.enabled = bool(endpoint and user and password)
        
        if self.enabled:
            try:
                self._connect()
                self._ensure_collection()
                logger.info("Jobs store initialized successfully")
            except Exception as exc:
                logger.exception("Failed to initialize jobs store: %s", exc)
                self.enabled = False
        else:
            logger.warning("No Zilliz endpoint configured, jobs store will be disabled")
    
    def _connect(self):
        """Connect to Zilliz Cloud."""
        try:
            logger.info("Connecting to Zilliz endpoint %s", self.endpoint)
            connect_args = {
                "alias": "default",
                "uri": self.endpoint,
                "user": self.user,
                "password": self.password,
                "secure": True,
            }
            connections.connect(**connect_args)
            logger.info("Connected to Zilliz successfully")
        except Exception as exc:
            logger.exception("Failed to connect to Zilliz: %s", exc)
            raise
    
    def _ensure_collection(self):
        """Create collection if it doesn't exist."""
        try:
            if utility.has_collection(self.collection_name):
                logger.info("Collection %s already exists, loading it", self.collection_name)
                self.collection = Collection(self.collection_name)
            else:
                logger.info("Creating collection %s", self.collection_name)
                schema = CollectionSchema(fields, description="Job profiles for Boss直聘 automation")
                self.collection = Collection(self.collection_name, schema)
                logger.info("Collection %s created successfully", self.collection_name)
                
                # Create indexes
                index_params = {
                    "index_type": "AUTOINDEX",
                    "metric_type": "IP",
                    "params": {},
                }
                self.collection.create_index(field_name="job_embedding", index_params=index_params)
                self.collection.create_index(field_name="job_id")
                self.collection.create_index(field_name="position")
                logger.info("Indexes created successfully")
            
            # Load collection into memory
            self.collection.load()
            logger.info("Collection %s loaded into memory", self.collection_name)
            
        except Exception as exc:
            logger.exception("Failed to ensure collection: %s", exc)
            raise
    
    def get_all_jobs(self) -> List[Dict[str, Any]]:
        """Get all jobs from the collection."""
        if not self.enabled or not self.collection:
            logger.warning("Jobs store not enabled or collection not available")
            return []
        
        try:
            # Query all records
            results = self.collection.query(
                expr="",  # Empty expression means get all
                output_fields=_all_fields,
                limit=1000  # Reasonable limit
            )
            
            # Convert to list of dicts
            jobs = []
            for result in results:
                job = dict(result)
                # Keywords are already JSON objects from Zilliz
                jobs.append(job)
            
            logger.info("Retrieved %d jobs from collection", len(jobs))
            return jobs
            
        except Exception as exc:
            logger.exception("Failed to get all jobs: %s", exc)
            return []
    
    def get_job_by_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific job by ID."""
        if not self.enabled or not self.collection:
            logger.warning("Jobs store not enabled or collection not available")
            return None
        
        try:
            results = self.collection.query(
                expr=f'job_id == "{job_id}"',
                output_fields=_all_fields,
                limit=1
            )
            
            if results:
                job = dict(results[0])
                # Keywords are already JSON objects from Zilliz
                return job
            
            return None
            
        except Exception as exc:
            logger.exception("Failed to get job by ID %s: %s", job_id, exc)
            return None
    
    def insert_job(self, **job_data) -> bool:
        """Insert a new job."""
        if not self.enabled or not self.collection:
            logger.warning("Jobs store not enabled or collection not available")
            return False
        
        try:
            # Prepare data for insertion
            now = datetime.now().isoformat()
            drill_down = str(job_data.get("drill_down_questions", ""))[:30000]
            
            insert_data = {
                "job_id": job_data["id"],
                "position": job_data["position"],
                "background": job_data.get("background", ""),
                "description": job_data.get("description", ""),
                "responsibilities": job_data.get("responsibilities", ""),
                "requirements": job_data.get("requirements", ""),
                "target_profile": job_data.get("target_profile", ""),
                "keywords": job_data.get("keywords", {"positive": [], "negative": []}),
                "drill_down_questions": drill_down,
                "candidate_filters": job_data.get("candidate_filters"),  # Store candidate search filters
                "job_embedding": [0.0] * settings.ZILLIZ_EMBEDDING_DIM,  # Empty embedding for now
                "created_at": now,
                "updated_at": now,
            }
            
            # Insert data
            self.collection.insert([insert_data])
            self.collection.flush()
            
            logger.info("Successfully inserted job: %s", job_data["id"])
            return True
            
        except Exception as exc:
            logger.exception("Failed to insert job %s: %s", job_data.get("id"), exc)
            return False
    
    def update_job(self, job_id: str, **job_data) -> bool:
        """Update an existing job."""
        if not self.enabled or not self.collection:
            logger.warning("Jobs store not enabled or collection not available")
            return False
        
        try:
            # Check if job exists
            existing = self.get_job_by_id(job_id)
            if not existing:
                logger.warning("Job %s not found for update", job_id)
                return False
            
            # Prepare update data
            now = datetime.now().isoformat()
            
            update_data = {
                "job_id": job_id,
                "position": job_data.get("position", existing["position"]),
                "background": job_data.get("background", existing["background"]),
                "description": job_data.get("description", existing["description"]),
                "responsibilities": job_data.get("responsibilities", existing["responsibilities"]),
                "requirements": job_data.get("requirements", existing["requirements"]),
                "target_profile": job_data.get("target_profile", existing["target_profile"]),
                "keywords": job_data.get("keywords", existing["keywords"]),
                "drill_down_questions": str(job_data.get("drill_down_questions", existing["drill_down_questions"]))[:30000],
                "candidate_filters": job_data.get("candidate_filters", existing.get("candidate_filters")),  # Update candidate filters
                "job_embedding": [0.0] * settings.ZILLIZ_EMBEDDING_DIM,  # Keep empty for now
                "created_at": existing["created_at"],  # Keep original creation time
                "updated_at": now,
            }
            
            # Use upsert to update
            self.collection.upsert([update_data])
            self.collection.flush()
            
            logger.info("Successfully updated job: %s", job_id)
            return True
            
        except Exception as exc:
            logger.exception("Failed to update job %s: %s", job_id, exc)
            return False
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job by ID."""
        if not self.enabled or not self.collection:
            logger.warning("Jobs store not enabled or collection not available")
            return False
        
        try:
            # Delete by primary key
            self.collection.delete(f'job_id == "{job_id}"')
            self.collection.flush()
            
            logger.info("Successfully deleted job: %s", job_id)
            return True
            
        except Exception as exc:
            logger.exception("Failed to delete job %s: %s", job_id, exc)
            return False


def _create_jobs_store() -> JobsStore:
    """Create jobs store instance using configuration."""
    if not settings.ZILLIZ_ENDPOINT:
        logger.warning("No Zilliz endpoint configured, jobs store will be disabled")
        return JobsStore("", "", "")
    
    return JobsStore(
        endpoint=settings.ZILLIZ_ENDPOINT,
        user=settings.ZILLIZ_USER,
        password=settings.ZILLIZ_PASSWORD,
        collection_name="CN_jobs"
    )


# Global instance
default_store = _create_jobs_store()
jobs_store = default_store

__all__ = ["jobs_store", "JobsStore"]
