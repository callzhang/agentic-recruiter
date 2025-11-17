"""
Tests for job versioning functionality.

Tests cover:
- Job creation with versioning (v1, current=True)
- Job updates creating new versions
- Version retrieval and switching
- Base job_id extraction
- API endpoints for version management
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from fastapi.testclient import TestClient
from typing import Dict, Any, List

# Import the functions we need to test
from src.jobs_store import (
    get_base_job_id,
    insert_job,
    update_job,
    get_job_by_id,
    get_all_jobs,
    get_job_versions,
    switch_job_version,
    delete_job,
)


class TestJobVersioningHelpers:
    """Test helper functions for job versioning."""
    
    def test_get_base_job_id_with_version(self):
        """Test extracting base job_id from versioned job_id."""
        assert get_base_job_id("ml_engineer_v1") == "ml_engineer"
        assert get_base_job_id("ml_engineer_v2") == "ml_engineer"
        assert get_base_job_id("python_dev_v10") == "python_dev"
    
    def test_get_base_job_id_without_version(self):
        """Test base job_id extraction when no version suffix exists."""
        assert get_base_job_id("ml_engineer") == "ml_engineer"
        assert get_base_job_id("python_dev") == "python_dev"
    
    def test_get_base_job_id_edge_cases(self):
        """Test edge cases for base job_id extraction."""
        assert get_base_job_id("job_v") == "job_v"  # No number after _v
        assert get_base_job_id("job_v123") == "job"  # Multiple digits
        assert get_base_job_id("") == ""


class TestJobVersioningOperations:
    """Test job versioning operations with mocked Zilliz client."""
    
    @patch('src.jobs_store._client')
    def test_insert_job_creates_v1(self, mock_client):
        """Test that insert_job creates version v1 with current=True."""
        mock_client.query.return_value = []
        mock_client.insert.return_value = None
        
        job_data = {
            "id": "ml_engineer",
            "position": "Machine Learning Engineer",
            "description": "ML engineer position",
        }
        
        result = insert_job(**job_data)
        
        assert result is True
        # Verify insert was called
        assert mock_client.insert.called
        # Get the data that was inserted
        call_args = mock_client.insert.call_args
        inserted_data = call_args[1]['data'][0]
        
        assert inserted_data["job_id"] == "ml_engineer_v1"
        assert inserted_data["version"] == 1
        assert inserted_data["current"] is True
    
    @patch('src.jobs_store._client')
    def test_update_job_creates_new_version(self, mock_client):
        """Test that update_job creates a new version and sets old version to current=False."""
        # Mock current job
        current_job = {
            "job_id": "ml_engineer_v1",
            "version": 1,
            "current": True,
            "position": "ML Engineer",
            "description": "Old description",
            "created_at": "2024-01-01T00:00:00",
        }
        
        # Mock query for current job
        mock_client.query.return_value = [current_job]
        
        # Mock get_job_versions to return existing version
        with patch('src.jobs_store.get_job_versions', return_value=[current_job]):
            result = update_job(
                "ml_engineer",
                position="ML Engineer Updated",
                description="New description"
            )
            
            assert result is True
            # Verify upsert was called to set old version's current=False
            assert mock_client.upsert.called
            # Verify insert was called to create new version
            assert mock_client.insert.called
            
            # Check that new version was created
            insert_call = mock_client.insert.call_args
            new_version_data = insert_call[1]['data'][0]
            
            assert new_version_data["job_id"] == "ml_engineer_v2"
            assert new_version_data["version"] == 2
            assert new_version_data["current"] is True
    
    @patch('src.jobs_store._client')
    def test_get_job_by_id_returns_current_version(self, mock_client):
        """Test that get_job_by_id returns the current version."""
        current_job = {
            "job_id": "ml_engineer_v2",
            "version": 2,
            "current": True,
            "position": "ML Engineer",
        }
        
        mock_client.query.return_value = [current_job]
        
        result = get_job_by_id("ml_engineer")
        
        assert result is not None
        assert result["job_id"] == "ml_engineer_v2"
        assert result["current"] is True
    
    @patch('src.jobs_store._client')
    def test_get_all_jobs_returns_only_current_versions(self, mock_client):
        """Test that get_all_jobs only returns current versions."""
        # The function filters by 'current == true', so mock should return only current jobs
        current_jobs = [
            {"job_id": "ml_engineer_v2", "version": 2, "current": True, "position": "ML Engineer"},
            {"job_id": "python_dev_v1", "version": 1, "current": True, "position": "Python Dev"},
        ]
        
        # Mock query to return only current jobs (as the filter would do)
        mock_client.query.return_value = current_jobs
        
        result = get_all_jobs()
        
        # Should only return current versions
        assert len(result) == 2
        assert all(job.get("current") is True for job in result)
        # Should have base_job_id field
        assert all("base_job_id" in job for job in result)
    
    @patch('src.jobs_store._client')
    def test_get_job_versions_returns_all_versions(self, mock_client):
        """Test that get_job_versions returns all versions of a job."""
        versions = [
            {"job_id": "ml_engineer_v2", "version": 2, "current": True, "created_at": "2024-01-02"},
            {"job_id": "ml_engineer_v1", "version": 1, "current": False, "created_at": "2024-01-01"},
        ]
        
        mock_client.query.return_value = versions
        
        result = get_job_versions("ml_engineer")
        
        assert len(result) == 2
        # Should be sorted by created_at DESC (latest first)
        assert result[0]["version"] == 2
        assert result[1]["version"] == 1
    
    @patch('src.jobs_store._client')
    def test_switch_job_version(self, mock_client):
        """Test switching the current version of a job."""
        versions = [
            {"job_id": "ml_engineer_v2", "version": 2, "current": True},
            {"job_id": "ml_engineer_v1", "version": 1, "current": False},
        ]
        
        # Mock get_job_versions to return versions
        with patch('src.jobs_store.get_job_versions', return_value=versions):
            result = switch_job_version("ml_engineer", 1)
            
            assert result is True
            # Should call upsert: once for each version to set current=False (2 calls)
            # and once to set target version to current=True (1 call)
            # Total: 3 calls (2 versions + 1 target)
            assert mock_client.upsert.call_count == 3
    
    @patch('src.jobs_store._client')
    def test_delete_job_deletes_all_versions(self, mock_client):
        """Test that delete_job deletes all versions of a job."""
        versions = [
            {"job_id": "ml_engineer_v2", "version": 2},
            {"job_id": "ml_engineer_v1", "version": 1},
        ]
        
        with patch('src.jobs_store.get_job_versions', return_value=versions):
            result = delete_job("ml_engineer")
            
            assert result is True
            # Should delete all versions
            assert mock_client.delete.call_count == 2


class TestJobVersioningAPI:
    """Test job versioning API endpoints."""
    
    @pytest.fixture
    def client(self, monkeypatch: pytest.MonkeyPatch):
        """Create a test client with mocked dependencies."""
        # Mock Zilliz client
        mock_client = MagicMock()
        mock_client.query = MagicMock(return_value=[])
        mock_client.insert = MagicMock(return_value=None)
        mock_client.upsert = MagicMock(return_value=None)
        mock_client.delete = MagicMock(return_value=None)
        mock_client.has_collection = MagicMock(return_value=True)
        
        with patch('src.jobs_store._client', mock_client):
            from boss_service import app
            return TestClient(app)
    
    def test_get_job_versions_endpoint(self, client, monkeypatch):
        """Test GET /jobs/{job_id}/versions endpoint."""
        versions = [
            {"job_id": "ml_engineer_v2", "version": 2, "current": True, "created_at": "2024-01-02"},
            {"job_id": "ml_engineer_v1", "version": 1, "current": False, "created_at": "2024-01-01"},
        ]
        
        with patch('src.jobs_store.get_job_versions', return_value=versions):
            response = client.get("/jobs/ml_engineer/versions")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert len(data["data"]) == 2
    
    def test_switch_job_version_endpoint(self, client, monkeypatch):
        """Test POST /jobs/{job_id}/switch-version endpoint."""
        updated_job = {
            "job_id": "ml_engineer_v1",
            "version": 1,
            "current": True,
            "position": "ML Engineer",
        }
        
        with patch('src.jobs_store.switch_job_version', return_value=True), \
             patch('src.jobs_store.get_job_by_id', return_value=updated_job):
            response = client.post(
                "/jobs/ml_engineer/switch-version",
                json={"version": 1}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["version"] == 1
    
    def test_create_job_creates_v1(self, client, monkeypatch):
        """Test that creating a job creates version v1."""
        with patch('src.jobs_store.insert_job', return_value=True), \
             patch('src.jobs_store.get_job_by_id', return_value=None):
            response = client.post(
                "/jobs/create",
                json={
                    "job_id": "ml_engineer",
                    "position": "ML Engineer",
                    "description": "ML engineer position",
                }
            )
            
            # Should succeed (status depends on implementation)
            assert response.status_code in [200, 201]
    
    def test_update_job_creates_new_version(self, client, monkeypatch):
        """Test that updating a job creates a new version."""
        current_job = {
            "job_id": "ml_engineer_v1",
            "version": 1,
            "current": True,
            "position": "ML Engineer",
        }
        
        updated_job = {
            "job_id": "ml_engineer_v2",
            "version": 2,
            "current": True,
            "position": "ML Engineer Updated",
        }
        
        with patch('src.jobs_store.get_job_by_id', side_effect=[current_job, updated_job]), \
             patch('src.jobs_store.update_job', return_value=True):
            response = client.post(
                "/jobs/ml_engineer/update",
                json={
                    "job_id": "ml_engineer",
                    "position": "ML Engineer Updated",
                    "description": "Updated description",
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

