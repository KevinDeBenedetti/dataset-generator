"""Tests for generate API endpoints"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from fastapi.testclient import TestClient

from server.main import app
from server.models.user import User, UserRole
from server.api.deps import get_credentials
from server.services.auth import get_current_user
from server.tests.creds import FULL, make_creds

client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated():
    """The feature routers are auth-protected on the real app; these tests cover
    generation behaviour, not auth, so resolve a fake user for every request."""
    app.dependency_overrides[get_current_user] = lambda: User(
        id="test-user", email="tester@example.com", role=UserRole.USER
    )
    app.dependency_overrides[get_credentials] = lambda: FULL
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_credentials, None)


@pytest.fixture(autouse=True)
def env_model_defaults():
    """Role defaults from the env only — these tests have no database."""
    from server.services.model_defaults import env_defaults

    with patch(
        "server.services.model_defaults.get_model_defaults",
        side_effect=lambda user_id=None: env_defaults(),
    ):
        yield


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
def mock_url_pipeline():
    """Mock DatasetPipeline.process_url for the URL endpoint."""
    with patch("server.api.generate.DatasetPipeline") as mock:
        instance = Mock()
        instance.process_url = AsyncMock()
        mock.return_value = instance
        yield instance


class TestGenerateDatasetFromUrl:
    """Tests for POST /dataset/generate/url (single web page)."""

    def _pipeline_result(self):
        return {
            "qa_pairs": [{"question": "What is it?", "answer": "A guide."}],
            "total": 1,
            "dataset_id": "web-ds",
            "pages_crawled": 1,
            "steps": [],
        }

    def test_create_dataset_from_url_success(self, mock_url_pipeline):
        mock_url_pipeline.process_url.return_value = self._pipeline_result()

        response = client.post(
            "/dataset/generate/url",
            json={"url": "https://docs.example.com/guide", "dataset_name": "web-ds"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "web-ds" and data["total_questions"] == 1
        kwargs = mock_url_pipeline.process_url.call_args.kwargs
        assert kwargs["url"] == "https://docs.example.com/guide"
        # Role defaults, normalized to provider references.
        assert kwargs["model_cleaning"] == "openai:gpt-4o-mini"
        assert kwargs["model_qa"] == "openai:gpt-4o-mini"

    def test_explicit_models_are_forwarded(self, mock_url_pipeline, monkeypatch):
        mock_url_pipeline.process_url.return_value = self._pipeline_result()

        response = client.post(
            "/dataset/generate/url",
            json={
                "url": "https://docs.example.com",
                "dataset_name": "x",
                "model_qa": "claude:claude-sonnet-5",
            },
        )

        assert response.status_code == 201
        kwargs = mock_url_pipeline.process_url.call_args.kwargs
        assert kwargs["model_qa"] == "claude:claude-sonnet-5"

    def test_refused_url_returns_400(self, mock_url_pipeline):
        from server.services.web import WebFetchError

        mock_url_pipeline.process_url = AsyncMock(
            side_effect=WebFetchError("localhost resolves to a non-public address")
        )
        response = client.post(
            "/dataset/generate/url",
            json={"url": "http://localhost:8000", "dataset_name": "x"},
        )
        assert response.status_code == 400
        assert "non-public" in response.json()["detail"]

    def test_unknown_model_returns_400(self, mock_url_pipeline):
        response = client.post(
            "/dataset/generate/url",
            json={
                "url": "https://docs.example.com",
                "dataset_name": "x",
                "model_qa": "openai:not-configured",
            },
        )
        assert response.status_code == 400
        assert "Unknown model" in response.json()["detail"]
        mock_url_pipeline.process_url.assert_not_called()

    def test_unconfigured_provider_returns_400(self, mock_url_pipeline):
        # A user who never added a Claude token.
        app.dependency_overrides[get_credentials] = lambda: make_creds(
            openai_api_key="sk-user-0000000000000000", base_url_trusted=True
        )
        response = client.post(
            "/dataset/generate/url",
            json={
                "url": "https://docs.example.com",
                "dataset_name": "x",
                "model_qa": "claude:claude-sonnet-5",
            },
        )
        assert response.status_code == 400
        assert "Claude token" in response.json()["detail"]
        assert "Settings" in response.json()["detail"]
