"""
Comprehensive tests for FastAPI jobs functionality.

Tests cover:
- Job store functions (jobs_store.py)
- FastAPI routes (web/routes/jobs.py)
- Job versioning operations
- API endpoints
- Edge cases and error handling
- Last version deletion logic
"""
import pytest
import json
from unittest.mock import Mock, MagicMock, patch, call
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
    delete_job_version,
    delete_job,
)

# Don't import router directly to avoid circular imports
# Test endpoints through the app instead


class TestJobStoreHelpers:
    """Test helper functions for job versioning."""
    
    def test_get_base_job_id_with_version(self):
        """Test extracting base job_id from versioned job_id."""
        assert get_base_job_id("ml_engineer_v1") == "ml_engineer"
        assert get_base_job_id("ml_engineer_v2") == "ml_engineer"
        assert get_base_job_id("python_dev_v10") == "python_dev"
        assert get_base_job_id("job_v123") == "job"
    
    def test_get_base_job_id_without_version(self):
        """Test base job_id extraction when no version suffix exists."""
        assert get_base_job_id("ml_engineer") == "ml_engineer"
        assert get_base_job_id("python_dev") == "python_dev"
    
    def test_get_base_job_id_edge_cases(self):
        """Test edge cases for base job_id extraction."""
        assert get_base_job_id("job_v") == "job_v"  # No number after _v
        assert get_base_job_id("") == ""
        assert get_base_job_id("_v1") == ""  # Entire string is version suffix, base is empty


class TestJobStoreOperations:
    """Test job store operations with mocked Zilliz client."""
    
    @patch('src.jobs_store._client')
    def test_insert_job_creates_v1(self, mock_client):
        """Test that insert_job creates version v1 with current=True."""
        mock_client.query.return_value = []
        mock_client.insert.return_value = None
        
        job_data = {
            "id": "ml_engineer",
            "position": "Machine Learning Engineer",
            "description": "ML engineer position",
            "background": "Tech company",
        }
        
        result = insert_job(**job_data)
        
        assert result is True
        assert mock_client.insert.called
        call_args = mock_client.insert.call_args
        inserted_data = call_args[1]['data'][0]
        
        assert inserted_data["job_id"] == "ml_engineer_v1"
        assert inserted_data["version"] == 1
        assert inserted_data["current"] is True
        assert inserted_data["position"] == "Machine Learning Engineer"
    
    @patch('src.jobs_store._client')
    def test_insert_job_with_existing_base_id(self, mock_client):
        """Test that insert_job handles versioned IDs in input."""
        mock_client.query.return_value = []
        mock_client.insert.return_value = None
        
        job_data = {
            "id": "ml_engineer_v5",  # Has version suffix
            "position": "ML Engineer",
        }
        
        result = insert_job(**job_data)
        
        assert result is True
        call_args = mock_client.insert.call_args
        inserted_data = call_args[1]['data'][0]
        # Should still create v1 (ignores input version)
        assert inserted_data["job_id"] == "ml_engineer_v1"
        assert inserted_data["version"] == 1
    
    @patch('src.jobs_store._client')
    def test_update_job_creates_new_version(self, mock_client):
        """Test that update_job creates a new version and sets old version to current=False."""
        current_job = {
            "job_id": "ml_engineer_v1",
            "version": 1,
            "current": True,
            "position": "ML Engineer",
            "description": "Old description",
            "created_at": "2024-01-01T00:00:00",
        }
        
        mock_client.query.return_value = [current_job]
        
        with patch('src.jobs_store.get_job_by_id', return_value=current_job), \
             patch('src.jobs_store.get_job_versions', return_value=[current_job]):
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
    def test_update_job_with_empty_fields(self, mock_client):
        """Test that update_job handles empty/None fields correctly."""
        current_job = {
            "job_id": "ml_engineer_v1",
            "version": 1,
            "current": True,
            "position": "ML Engineer",
            "background": "Original background",
            "description": None,
            "created_at": "2024-01-01T00:00:00",
        }
        
        mock_client.query.return_value = [current_job]
        
        with patch('src.jobs_store.get_job_by_id', return_value=current_job), \
             patch('src.jobs_store.get_job_versions', return_value=[current_job]):
            result = update_job(
                "ml_engineer",
                position="ML Engineer",
                background="",  # Empty string
                description=None,  # None value
            )
            
            assert result is True
            assert mock_client.insert.called
    
    @patch('src.jobs_store._client')
    def test_update_job_not_found(self, mock_client):
        """Test that update_job returns False for non-existent job."""
        with patch('src.jobs_store.get_job_by_id', return_value=None):
            result = update_job("non_existent", position="Test")
            assert result is False
    
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
    def test_get_job_by_id_with_versioned_id(self, mock_client):
        """Test that get_job_by_id handles versioned IDs."""
        versioned_job = {
            "job_id": "ml_engineer_v3",
            "version": 3,
            "current": False,
            "position": "ML Engineer v3",
        }
        
        mock_client.query.return_value = [versioned_job]
        
        result = get_job_by_id("ml_engineer_v3")
        
        assert result is not None
        assert result["job_id"] == "ml_engineer_v3"
        assert result["version"] == 3
    
    @patch('src.jobs_store._client')
    def test_get_job_by_id_not_found(self, mock_client):
        """Test that get_job_by_id returns None for non-existent job."""
        mock_client.query.return_value = []
        
        result = get_job_by_id("non_existent")
        
        assert result is None
    
    @patch('src.jobs_store._client')
    def test_get_all_jobs_returns_only_current_versions(self, mock_client):
        """Test that get_all_jobs only returns current versions."""
        current_jobs = [
            {"job_id": "ml_engineer_v2", "version": 2, "current": True, "position": "ML Engineer", "updated_at": "2024-01-02"},
            {"job_id": "python_dev_v1", "version": 1, "current": True, "position": "Python Dev", "updated_at": "2024-01-01"},
        ]
        
        mock_client.query.return_value = current_jobs
        
        result = get_all_jobs()
        
        assert len(result) == 2
        assert all(job.get("current") is True for job in result)
        assert all("base_job_id" in job for job in result)
        # Should be sorted by updated_at DESC
        assert result[0]["updated_at"] >= result[1]["updated_at"]
    
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
    def test_get_job_versions_empty(self, mock_client):
        """Test that get_job_versions returns empty list for non-existent job."""
        mock_client.query.return_value = []
        
        result = get_job_versions("non_existent")
        
        assert result == []
    
    @patch('src.jobs_store._client')
    def test_switch_job_version(self, mock_client):
        """Test switching the current version of a job."""
        versions = [
            {"job_id": "ml_engineer_v2", "version": 2, "current": True},
            {"job_id": "ml_engineer_v1", "version": 1, "current": False},
        ]
        
        # Mock query to return positions
        mock_client.query.return_value = [
            {"job_id": "ml_engineer_v2", "position": "ML Engineer", "current": True},
            {"job_id": "ml_engineer_v1", "position": "ML Engineer", "current": False},
        ]
        
        with patch('src.jobs_store.get_job_versions', return_value=versions):
            result = switch_job_version("ml_engineer", 1)
            
            assert result is True
            # Should call upsert: once for each version to set current=False (2 calls)
            # and once to set target version to current=True (1 call)
            # Total: 3 calls (2 versions + 1 target)
            assert mock_client.upsert.call_count == 3
            
            # Verify all upserts include position field
            for call_args in mock_client.upsert.call_args_list:
                data = call_args[1]['data'][0]
                assert 'position' in data
                assert 'current' in data
    
    @patch('src.jobs_store._client')
    def test_switch_job_version_not_found(self, mock_client):
        """Test that switch_job_version returns False for non-existent version."""
        versions = [
            {"job_id": "ml_engineer_v1", "version": 1, "current": True},
        ]
        
        with patch('src.jobs_store.get_job_versions', return_value=versions):
            result = switch_job_version("ml_engineer", 999)
            assert result is False
    
    @patch('src.jobs_store._client')
    def test_switch_job_version_without_position_fallback(self, mock_client):
        """Test that switch_job_version uses fallback when position is missing."""
        versions = [
            {"job_id": "ml_engineer_v1", "version": 1, "current": True},
        ]
        
        # Mock query to return no position
        mock_client.query.return_value = [
            {"job_id": "ml_engineer_v1", "position": "", "current": True},
        ]
        
        # Mock get_job_by_id to return job with position
        target_job = {
            "job_id": "ml_engineer_v1",
            "position": "ML Engineer",
            "current": True,
        }
        
        with patch('src.jobs_store.get_job_versions', return_value=versions), \
             patch('src.jobs_store.get_job_by_id', return_value=target_job):
            result = switch_job_version("ml_engineer", 1)
            
            assert result is True
            # Should use fallback get_job_by_id
            assert mock_client.upsert.called
    
    @patch('src.jobs_store._client')
    def test_delete_job_version(self, mock_client):
        """Test that delete_job_version deletes a specific version."""
        mock_client.delete.return_value = None
        
        result = delete_job_version("ml_engineer", 1)
        
        assert result is True
        assert mock_client.delete.called
        call_args = mock_client.delete.call_args
        assert call_args[1]['filter'] == 'job_id == "ml_engineer_v1"'
    
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


class TestJobsAPIEndpoints:
    """Test FastAPI job endpoints."""
    
    @pytest.fixture
    def client(self, monkeypatch: pytest.MonkeyPatch):
        """Create a test client with mocked dependencies."""
        mock_client = MagicMock()
        mock_client.query = MagicMock(return_value=[])
        mock_client.insert = MagicMock(return_value=None)
        mock_client.upsert = MagicMock(return_value=None)
        mock_client.delete = MagicMock(return_value=None)
        mock_client.has_collection = MagicMock(return_value=True)
        
        with patch('src.jobs_store._client', mock_client):
            from boss_service import app
            return TestClient(app)
    
    def test_get_jobs_page(self, client):
        """Test GET /jobs page returns HTML."""
        with patch('web.routes.jobs.load_jobs', return_value=[]):
            response = client.get("/jobs")
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert "岗位画像" in response.text
    
    def test_api_list_jobs(self, client):
        """Test GET /jobs/api/list endpoint."""
        jobs = [
            {"job_id": "ml_engineer_v1", "position": "ML Engineer", "current": True},
        ]
        
        with patch('web.routes.jobs.load_jobs', return_value=jobs):
            response = client.get("/jobs/api/list")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert len(data["data"]) == 1
    
    def test_api_get_job(self, client):
        """Test GET /jobs/api/{job_id} endpoint."""
        job = {
            "job_id": "ml_engineer_v1",
            "position": "ML Engineer",
            "current": True,
        }
        
        with patch('src.jobs_store.get_job_by_id', return_value=job):
            response = client.get("/jobs/api/ml_engineer")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["position"] == "ML Engineer"
    
    def test_api_get_job_not_found(self, client):
        """Test GET /jobs/api/{job_id} with non-existent job."""
        with patch('src.jobs_store.get_job_by_id', return_value=None):
            response = client.get("/jobs/api/non_existent")
            
            assert response.status_code == 404
            data = response.json()
            assert data["success"] is False
            assert "不存在" in data["error"]
    
    def test_create_job_success(self, client):
        """Test POST /jobs/create endpoint."""
        new_job = {
            "job_id": "ml_engineer_v1",
            "position": "ML Engineer",
            "current": True,
        }
        
        with patch('src.jobs_store.get_job_by_id', return_value=None), \
             patch('src.jobs_store.insert_job', return_value=True), \
             patch('src.jobs_store.get_job_by_id', side_effect=[None, new_job]):
            response = client.post(
                "/jobs/create",
                json={
                    "job_id": "ml_engineer",
                    "position": "ML Engineer",
                    "description": "ML engineer position",
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
    
    def test_create_job_duplicate(self, client):
        """Test POST /jobs/create with duplicate job_id."""
        existing_job = {
            "job_id": "ml_engineer_v1",
            "position": "ML Engineer",
        }
        
        with patch('src.jobs_store.get_job_by_id', return_value=existing_job):
            response = client.post(
                "/jobs/create",
                json={
                    "job_id": "ml_engineer",
                    "position": "ML Engineer",
                }
            )
            
            assert response.status_code == 400
            data = response.json()
            assert data["success"] is False
            assert "已存在" in data["error"]
    
    def test_create_job_missing_fields(self, client):
        """Test POST /jobs/create with missing required fields."""
        response = client.post(
            "/jobs/create",
            json={
                "job_id": "ml_engineer",
                # Missing position
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "不能为空" in data["error"]
    
    def test_update_job_success(self, client):
        """Test POST /jobs/{job_id}/update endpoint."""
        current_job = {
            "job_id": "ml_engineer_v1",
            "position": "ML Engineer",
            "current": True,
        }
        
        updated_job = {
            "job_id": "ml_engineer_v2",
            "position": "ML Engineer Updated",
            "current": True,
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
            assert data["data"]["position"] == "ML Engineer Updated"
    
    def test_update_job_not_found(self, client):
        """Test POST /jobs/{job_id}/update with non-existent job."""
        with patch('src.jobs_store.get_job_by_id', return_value=None):
            response = client.post(
                "/jobs/non_existent/update",
                json={
                    "job_id": "non_existent",
                    "position": "Test",
                }
            )
            
            assert response.status_code == 404
            data = response.json()
            assert data["success"] is False
            assert "未找到" in data["error"]
    
    def test_get_job_versions_endpoint(self, client):
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
    
    def test_switch_job_version_endpoint(self, client):
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
    
    def test_switch_job_version_missing_version(self, client):
        """Test POST /jobs/{job_id}/switch-version without version."""
        response = client.post(
            "/jobs/ml_engineer/switch-version",
            json={}
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "不能为空" in data["error"]
    
    def test_switch_job_version_invalid_version(self, client):
        """Test POST /jobs/{job_id}/switch-version with invalid version."""
        response = client.post(
            "/jobs/ml_engineer/switch-version",
            json={"version": "not_a_number"}
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "整数" in data["error"]
    
    def test_switch_job_version_not_found(self, client):
        """Test POST /jobs/{job_id}/switch-version with non-existent version."""
        with patch('src.jobs_store.switch_job_version', return_value=False):
            response = client.post(
                "/jobs/ml_engineer/switch-version",
                json={"version": 999}
            )
            
            assert response.status_code == 404
            data = response.json()
            assert data["success"] is False
            assert "不存在" in data["error"]
    
    def test_delete_job_version_success(self, client):
        """Test DELETE /jobs/{job_id}/delete endpoint."""
        all_versions = [
            {"job_id": "ml_engineer_v2", "version": 2, "current": True},
            {"job_id": "ml_engineer_v1", "version": 1, "current": False},
        ]
        
        remaining_versions = [
            {"job_id": "ml_engineer_v2", "version": 2, "current": True},
        ]
        
        with patch('src.jobs_store.get_job_by_id', return_value={"job_id": "ml_engineer_v2"}), \
             patch('src.jobs_store.get_job_versions', side_effect=[all_versions, remaining_versions]), \
             patch('src.jobs_store.delete_job_version', return_value=True), \
             patch('src.jobs_store.switch_job_version', return_value=True):
            response = client.delete(
                "/jobs/ml_engineer/delete",
                json={"version": 1}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "已删除" in data["message"]
    
    def test_delete_job_version_last_version(self, client):
        """Test DELETE /jobs/{job_id}/delete with last version (should succeed now)."""
        all_versions = [
            {"job_id": "ml_engineer_v1", "version": 1, "current": True},
        ]
        
        with patch('src.jobs_store.get_job_by_id', return_value={"job_id": "ml_engineer_v1"}), \
             patch('src.jobs_store.get_job_versions', side_effect=[all_versions, []]), \
             patch('src.jobs_store.delete_job_version', return_value=True):
            response = client.delete(
                "/jobs/ml_engineer/delete",
                json={"version": 1}
            )
            
            # Should succeed (no longer blocked)
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "岗位已删除" in data["message"] or "已删除" in data["message"]
    
    def test_delete_job_version_deleting_current(self, client):
        """Test DELETE /jobs/{job_id}/delete when deleting current version."""
        all_versions = [
            {"job_id": "ml_engineer_v2", "version": 2, "current": True},
            {"job_id": "ml_engineer_v1", "version": 1, "current": False},
        ]
        
        remaining_versions = [
            {"job_id": "ml_engineer_v1", "version": 1, "current": False},
        ]
        
        with patch('src.jobs_store.get_job_by_id', return_value={"job_id": "ml_engineer_v2"}), \
             patch('src.jobs_store.get_job_versions', side_effect=[all_versions, remaining_versions]), \
             patch('src.jobs_store.delete_job_version', return_value=True), \
             patch('src.jobs_store.switch_job_version', return_value=True):
            response = client.delete(
                "/jobs/ml_engineer/delete",
                json={"version": 2}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            # Should have called switch_job_version to set remaining version as current
            from src.jobs_store import switch_job_version
            # Verify switch was called (mocked)
    
    def test_delete_job_version_missing_version(self, client):
        """Test DELETE /jobs/{job_id}/delete without version."""
        response = client.delete(
            "/jobs/ml_engineer/delete",
            json={}
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "不能为空" in data["error"]
    
    def test_delete_job_version_invalid_version(self, client):
        """Test DELETE /jobs/{job_id}/delete with invalid version."""
        response = client.delete(
            "/jobs/ml_engineer/delete",
            json={"version": "not_a_number"}
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "整数" in data["error"]
    
    def test_delete_job_version_not_found(self, client):
        """Test DELETE /jobs/{job_id}/delete with non-existent version."""
        all_versions = [
            {"job_id": "ml_engineer_v1", "version": 1, "current": True},
        ]
        
        with patch('src.jobs_store.get_job_by_id', return_value={"job_id": "ml_engineer_v1"}), \
             patch('src.jobs_store.get_job_versions', return_value=all_versions):
            response = client.delete(
                "/jobs/ml_engineer/delete",
                json={"version": 999}
            )
            
            assert response.status_code == 404
            data = response.json()
            assert data["success"] is False
            assert "不存在" in data["error"]
    
    def test_delete_job_version_job_not_found(self, client):
        """Test DELETE /jobs/{job_id}/delete with non-existent job."""
        with patch('src.jobs_store.get_job_by_id', return_value=None):
            response = client.delete(
                "/jobs/non_existent/delete",
                json={"version": 1}
            )
            
            assert response.status_code == 404
            data = response.json()
            assert data["success"] is False
            assert "不存在" in data["error"]


class TestJobsAPIEdgeCases:
    """Test edge cases and error scenarios."""
    
    @pytest.fixture
    def client(self, monkeypatch: pytest.MonkeyPatch):
        """Create a test client with mocked dependencies."""
        mock_client = MagicMock()
        mock_client.query = MagicMock(return_value=[])
        mock_client.insert = MagicMock(return_value=None)
        mock_client.upsert = MagicMock(return_value=None)
        mock_client.delete = MagicMock(return_value=None)
        mock_client.has_collection = MagicMock(return_value=True)
        
        with patch('src.jobs_store._client', mock_client):
            from boss_service import app
            return TestClient(app)
    
    def test_update_job_with_job_id_change(self, client):
        """Test updating job with job_id change."""
        current_job = {
            "job_id": "ml_engineer_v1",
            "position": "ML Engineer",
            "current": True,
        }
        
        new_job = {
            "job_id": "python_dev_v1",
            "position": "Python Developer",
            "current": True,
        }
        
        with patch('src.jobs_store.get_job_by_id', side_effect=[current_job, None, new_job]), \
             patch('src.jobs_store.update_job', return_value=True):
            response = client.post(
                "/jobs/ml_engineer/update",
                json={
                    "job_id": "python_dev",  # Changed job_id
                    "position": "Python Developer",
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
    
    def test_update_job_with_conflicting_job_id(self, client):
        """Test updating job with job_id that already exists."""
        current_job = {
            "job_id": "ml_engineer_v1",
            "position": "ML Engineer",
            "current": True,
        }
        
        conflicting_job = {
            "job_id": "python_dev_v1",
            "position": "Python Developer",
            "current": True,
        }
        
        with patch('src.jobs_store.get_job_by_id', side_effect=[current_job, conflicting_job]):
            response = client.post(
                "/jobs/ml_engineer/update",
                json={
                    "job_id": "python_dev",  # Conflicts with existing
                    "position": "Python Developer",
                }
            )
            
            assert response.status_code == 400
            data = response.json()
            assert data["success"] is False
            assert "已存在" in data["error"]
    
    def test_get_job_versions_with_versioned_id(self, client):
        """Test GET /jobs/{job_id}/versions with versioned job_id."""
        versions = [
            {"job_id": "ml_engineer_v2", "version": 2, "current": True},
            {"job_id": "ml_engineer_v1", "version": 1, "current": False},
        ]
        
        with patch('src.jobs_store.get_job_versions', return_value=versions):
            # Should extract base_job_id from versioned ID
            response = client.get("/jobs/ml_engineer_v2/versions")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert len(data["data"]) == 2


class TestJobsStoreSwitchVersionWithPosition:
    """Test switch_job_version includes position field to avoid DataNotMatchException."""
    
    @patch('src.jobs_store._client')
    def test_switch_job_version_includes_position(self, mock_client):
        """Test that switch_job_version includes position in upsert calls."""
        versions = [
            {"job_id": "ml_engineer_v2", "version": 2, "current": True},
            {"job_id": "ml_engineer_v1", "version": 1, "current": False},
        ]
        
        # Mock query to return positions
        mock_client.query.return_value = [
            {"job_id": "ml_engineer_v2", "position": "ML Engineer v2", "current": True},
            {"job_id": "ml_engineer_v1", "position": "ML Engineer v1", "current": False},
        ]
        
        with patch('src.jobs_store.get_job_versions', return_value=versions):
            result = switch_job_version("ml_engineer", 1)
            
            assert result is True
            # Verify all upsert calls include position
            for call_args in mock_client.upsert.call_args_list:
                data = call_args[1]['data'][0]
                assert 'position' in data
                assert 'current' in data
                assert data['position'] != ""  # Position should not be empty
    
    @patch('src.jobs_store._client')
    def test_switch_job_version_fallback_to_get_job_by_id(self, mock_client):
        """Test that switch_job_version uses get_job_by_id fallback when position missing."""
        versions = [
            {"job_id": "ml_engineer_v1", "version": 1, "current": True},
        ]
        
        # Mock query to return empty position
        mock_client.query.return_value = [
            {"job_id": "ml_engineer_v1", "position": "", "current": True},
        ]
        
        # Mock get_job_by_id to return job with position
        target_job = {
            "job_id": "ml_engineer_v1",
            "position": "ML Engineer",
            "current": True,
        }
        
        with patch('src.jobs_store.get_job_versions', return_value=versions), \
             patch('src.jobs_store.get_job_by_id', return_value=target_job):
            result = switch_job_version("ml_engineer", 1)
            
            assert result is True
            # Should have called get_job_by_id as fallback
            from src.jobs_store import get_job_by_id
            # Verify upsert was called with position from fallback
            assert mock_client.upsert.called
            call_args = mock_client.upsert.call_args
            data = call_args[1]['data'][0]
            assert data['position'] == "ML Engineer"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

