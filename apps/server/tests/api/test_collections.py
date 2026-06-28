"""Tests for the /collections API endpoints (Langfuse-backed)."""

from unittest.mock import patch

from server.services.qdrant import LangfuseUnavailableError


def test_get_collections_lists_langfuse_datasets(client):
    fake = {
        "qdrant_configured": False,
        "total": 1,
        "collections": [
            {
                "id": "lf-1",
                "name": "Gamma",
                "description": "d",
                "target_language": None,
                "qa_sources_count": 2,
                "created_at": "2026-01-01",
                "collection_name": "dataset_gamma",
                "in_qdrant": None,
                "points_count": None,
            }
        ],
    }
    with patch("server.api.collections.list_collections", return_value=fake):
        response = client.get("/collections")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["collections"][0]["name"] == "Gamma"
    assert body["collections"][0]["collection_name"] == "dataset_gamma"


def test_get_collections_503_when_langfuse_unavailable(client):
    with patch(
        "server.api.collections.list_collections",
        side_effect=LangfuseUnavailableError("Langfuse is not configured."),
    ):
        response = client.get("/collections")
    assert response.status_code == 503


def test_push_to_qdrant_returns_503_when_qdrant_unconfigured(client):
    from server.services.qdrant import QdrantNotConfiguredError

    with patch(
        "server.api.collections.sync_dataset_to_qdrant",
        side_effect=QdrantNotConfiguredError("Qdrant is not configured."),
    ):
        response = client.post("/collections/Gamma/qdrant")
    assert response.status_code == 503


def test_push_to_qdrant_returns_404_for_empty_dataset(client):
    with patch(
        "server.api.collections.sync_dataset_to_qdrant",
        side_effect=ValueError("Dataset 'Gamma' has no Q/A pairs to sync"),
    ):
        response = client.post("/collections/Gamma/qdrant")
    assert response.status_code == 404


def test_push_to_qdrant_success(client):
    fake_result = {
        "dataset_name": "Gamma",
        "collection_name": "dataset_gamma",
        "points_upserted": 2,
        "vector_size": 1536,
    }
    with patch(
        "server.api.collections.sync_dataset_to_qdrant", return_value=fake_result
    ):
        response = client.post("/collections/Gamma/qdrant")

    assert response.status_code == 200
    assert response.json() == fake_result
