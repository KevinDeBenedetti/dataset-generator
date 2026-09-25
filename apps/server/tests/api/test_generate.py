"""Tests for generate API endpoints"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from fastapi.testclient import TestClient

from server.main import app
from server.models.user import User, UserRole
from server.services.auth import get_current_user

client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated():
    """The feature routers are auth-protected on the real app; these tests cover
    generation behaviour, not auth, so resolve a fake user for every request."""
    app.dependency_overrides[get_current_user] = lambda: User(
        id="test-user", email="tester@example.com", role=UserRole.USER
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def mock_file_pipeline():
    """Mock DatasetPipeline.process_file for the file-upload endpoint."""
    with patch("server.api.generate.DatasetPipeline") as mock:
        instance = Mock()
        instance.process_file = AsyncMock()
        mock.return_value = instance
        yield instance


class TestGenerateDatasetFromFile:
    """Tests for POST /dataset/generate/file (PDF/image upload)."""

    def _pipeline_result(self):
        return {
            "qa_pairs": [],
            "total": 1,
            "exact_duplicates": 0,
            "similar_duplicates": 0,
            "dataset_id": "file-ds-1",
            "dataset_name": "from_file",
            "pages_crawled": 2,
            "steps": [],
        }

    def test_create_dataset_from_pdf_success(self, mock_file_pipeline):
        mock_file_pipeline.process_file.return_value = self._pipeline_result()

        response = client.post(
            "/dataset/generate/file",
            data={"dataset_name": "from_file", "target_language": "en"},
            files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "file-ds-1"
        assert data["pages_crawled"] == 2
        # The uploaded bytes + filename are forwarded to the pipeline.
        kwargs = mock_file_pipeline.process_file.call_args.kwargs
        assert kwargs["filename"] == "doc.pdf"
        assert kwargs["content"] == b"%PDF-1.4 fake"

    def test_unsupported_file_returns_400(self, mock_file_pipeline):
        mock_file_pipeline.process_file = AsyncMock(
            side_effect=ValueError("Unsupported file type 'text/plain'")
        )

        response = client.post(
            "/dataset/generate/file",
            data={"dataset_name": "x"},
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

        assert response.status_code == 400
        assert "unsupported" in response.json()["detail"].lower()

    def test_empty_file_returns_400(self, mock_file_pipeline):
        response = client.post(
            "/dataset/generate/file",
            data={"dataset_name": "x"},
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_missing_vlm_model_returns_400(self, mock_file_pipeline, monkeypatch):
        from server.core.config import config

        monkeypatch.setattr(config, "openai_vlm_model", "")

        response = client.post(
            "/dataset/generate/file",
            data={"dataset_name": "x"},
            files={"file": ("doc.pdf", b"%PDF fake", "application/pdf")},
        )

        assert response.status_code == 400
        assert "vision model" in response.json()["detail"].lower()


@pytest.fixture
def mock_github_pipeline():
    """Mock DatasetPipeline.process_github for the GitHub endpoint."""
    with patch("server.api.generate.DatasetPipeline") as mock:
        instance = Mock()
        instance.process_github = AsyncMock()
        mock.return_value = instance
        yield instance


class TestGenerateDatasetFromGitHub:
    """Tests for POST /dataset/generate/github."""

    def _pipeline_result(self):
        return {
            "qa_pairs": [],
            "total": 3,
            "exact_duplicates": 0,
            "similar_duplicates": 0,
            "dataset_id": "gh-ds-1",
            "dataset_name": "gh_ds",
            "pages_crawled": 3,
            "steps": [],
        }

    def test_create_dataset_from_github_success(self, mock_github_pipeline):
        mock_github_pipeline.process_github.return_value = self._pipeline_result()

        response = client.post(
            "/dataset/generate/github",
            json={"github_username": "octocat", "dataset_name": "gh_ds"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "gh-ds-1"
        assert data["pages_crawled"] == 3
        kwargs = mock_github_pipeline.process_github.call_args.kwargs
        assert kwargs["username"] == "octocat"

    def test_unknown_user_returns_400(self, mock_github_pipeline):
        mock_github_pipeline.process_github = AsyncMock(
            side_effect=ValueError("GitHub user 'ghost' not found")
        )

        response = client.post(
            "/dataset/generate/github",
            json={"github_username": "ghost", "dataset_name": "x"},
        )

        assert response.status_code == 400
        assert "not found" in response.json()["detail"]

    def test_invalid_model_returns_400(self, mock_github_pipeline):
        response = client.post(
            "/dataset/generate/github",
            json={
                "github_username": "octocat",
                "dataset_name": "x",
                "model_qa": "does-not-exist",
            },
        )

        assert response.status_code == 400
