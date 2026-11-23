"""
Tests for main application endpoints (health, root).
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _docs_on(monkeypatch):
    """The interactive docs exist in development only (core/config.py
    ``docs_enabled``): these tests read them, so the app is built with them on."""
    from server.core.config import config

    monkeypatch.setattr(config, "docs_enabled", True)


def test_health_endpoint(client: TestClient):
    """Test the /health endpoint returns OK status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_redirects_to_docs(client: TestClient):
    """Test the root endpoint redirects to /docs."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/docs"


def test_docs_endpoint_accessible(client: TestClient):
    """Test that the /docs endpoint is accessible."""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower() or "openapi" in response.text.lower()


def test_openapi_json_endpoint(client: TestClient):
    """Test that the OpenAPI JSON schema is accessible."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert "info" in data
    assert data["info"]["title"] == "Datasets Generator API"
