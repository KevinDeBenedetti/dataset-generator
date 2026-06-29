"""
Tests for Q&A API endpoints.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

# The Q&A list now comes from Langfuse (keyed by dataset name), so these tests
# mock get_qa_view.


def _qa_view_fn(total=15):
    """A get_qa_view stand-in that paginates `total` synthetic items."""
    items = [
        {
            "id": f"h{i}",
            "question": f"Question {i}",
            "answer": f"Answer {i}",
            "context": f"Context {i}",
            "source_url": f"https://example.com/{i}",
            "confidence": 0.9,
            "created_at": "2026-01-01T00:00:00",
            "metadata": {},
        }
        for i in range(total)
    ]

    def _view(dataset_name, limit=10, offset=0):
        page = items[offset : (offset + limit) if limit else None]
        return {
            "dataset_name": dataset_name,
            "dataset_id": dataset_name,
            "total_count": total,
            "returned_count": len(page),
            "offset": offset,
            "limit": limit,
            "qa_data": page,
        }

    return _view


def test_get_qa_by_dataset_not_found(client: TestClient):
    """Test getting Q&A for non-existent dataset."""
    with patch(
        "server.api.q_a.get_qa_view", side_effect=ValueError("Dataset 'x' not found")
    ):
        response = client.get("/q_a/nope")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_qa_by_dataset_empty(client: TestClient):
    """Test getting Q&A for a dataset with no records."""
    with patch("server.api.q_a.get_qa_view", side_effect=_qa_view_fn(total=0)):
        response = client.get("/q_a/my_dataset")
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_name"] == "my_dataset"
    assert data["total_count"] == 0
    assert data["returned_count"] == 0


def test_get_qa_by_dataset(client: TestClient):
    """Test getting Q&A records for a dataset."""
    with patch("server.api.q_a.get_qa_view", side_effect=_qa_view_fn(total=3)):
        response = client.get("/q_a/my_dataset", params={"limit": 10})
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_name"] == "my_dataset"
    assert data["total_count"] == 3
    assert len(data["qa_data"]) == 3


def test_get_qa_by_dataset_with_pagination(client: TestClient):
    """Test Q&A pagination is passed through to the view."""
    with patch("server.api.q_a.get_qa_view", side_effect=_qa_view_fn(total=15)):
        page1 = client.get("/q_a/my_dataset", params={"limit": 5, "offset": 0}).json()
        page2 = client.get("/q_a/my_dataset", params={"limit": 5, "offset": 5}).json()

    assert page1["total_count"] == 15
    assert page1["returned_count"] == 5
    assert page1["offset"] == 0
    assert page2["offset"] == 5
    assert page1["qa_data"][0]["id"] != page2["qa_data"][0]["id"]


def test_get_qa_by_dataset_limit_validation(client: TestClient):
    """Test Q&A endpoint with invalid limit values (rejected before the handler)."""
    assert client.get("/q_a/my_dataset", params={"limit": 2000}).status_code == 422
    assert client.get("/q_a/my_dataset", params={"limit": -1}).status_code == 422
