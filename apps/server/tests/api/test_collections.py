"""Tests for the /collections API endpoints (Langfuse-backed)."""

from unittest.mock import patch

import pytest

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


def test_push_to_qdrant_returns_503_when_langfuse_unavailable(client):
    """Qdrant may be up while the dataset's source of truth is not."""
    with patch(
        "server.api.collections.sync_dataset_to_qdrant",
        side_effect=LangfuseUnavailableError("Langfuse is not configured."),
    ):
        response = client.post("/collections/Gamma/qdrant")

    assert response.status_code == 503


def test_search_returns_matching_pairs(client):
    fake = {
        "dataset_name": "Gamma",
        "collection_name": "dataset_gamma",
        "query": "what is python",
        "count": 1,
        "results": [
            {
                "qa_id": "qa-1",
                "question": "What is Python?",
                "answer": "A language.",
                "context": "Python is a language.",
                "source_url": "https://example.com",
                "confidence": 0.9,
                "score": 0.83,
            }
        ],
    }
    with patch("server.api.collections.search_collection", return_value=fake) as search:
        response = client.post(
            "/collections/Gamma/search",
            json={"query": "what is python", "limit": 5, "score_threshold": 0.5},
        )

    assert response.status_code == 200
    assert response.json() == fake
    # The body's tuning knobs must reach the service, not be silently dropped.
    search.assert_called_once_with(
        "Gamma", query="what is python", limit=5, score_threshold=0.5
    )


def test_search_applies_schema_defaults_for_optional_knobs(client):
    with patch("server.api.collections.search_collection") as search:
        search.return_value = {
            "dataset_name": "Gamma",
            "collection_name": "dataset_gamma",
            "query": "q",
            "count": 0,
            "results": [],
        }
        response = client.post("/collections/Gamma/search", json={"query": "q"})

    assert response.status_code == 200
    search.assert_called_once_with("Gamma", query="q", limit=10, score_threshold=None)


def test_search_rejects_an_empty_query(client):
    """`min_length=1` — an empty query would embed to noise and match anything."""
    response = client.post("/collections/Gamma/search", json={"query": ""})

    assert response.status_code == 422


def test_search_returns_503_when_qdrant_unconfigured(client):
    from server.services.qdrant import QdrantNotConfiguredError

    with patch(
        "server.api.collections.search_collection",
        side_effect=QdrantNotConfiguredError("Qdrant is not configured."),
    ):
        response = client.post("/collections/Gamma/search", json={"query": "q"})

    assert response.status_code == 503


def test_search_returns_404_for_an_unsynced_collection(client):
    with patch(
        "server.api.collections.search_collection",
        side_effect=ValueError("Collection 'dataset_gamma' does not exist"),
    ):
        response = client.post("/collections/Gamma/search", json={"query": "q"})

    assert response.status_code == 404


@pytest.mark.parametrize(
    "view,call",
    [
        ("list_collections", lambda c: c.get("/collections")),
        ("sync_dataset_to_qdrant", lambda c: c.post("/collections/Gamma/qdrant")),
        (
            "search_collection",
            lambda c: c.post("/collections/Gamma/search", json={"query": "q"}),
        ),
    ],
    ids=["list", "qdrant_sync", "search"],
)
def test_unexpected_service_error_returns_500(client, view, call):
    """The catch-all branch: an unmapped error is logged and reported as 500."""
    with patch(f"server.api.collections.{view}", side_effect=RuntimeError("boom")):
        response = call(client)

    assert response.status_code == 500
    assert "boom" in response.json()["detail"]
