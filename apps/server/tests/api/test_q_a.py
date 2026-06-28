"""
Tests for Q&A API endpoints.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.models.dataset import Dataset, QASource

# The Q&A list now comes from Langfuse (keyed by dataset name), so those tests
# mock get_qa_view. The /q_a/id/{qa_id} endpoint still reads the local DB.


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


def test_get_qa_by_id(
    client: TestClient,
    test_db: Session,
    sample_dataset_data: dict,
    sample_qa_data: dict,
):
    """Test getting a specific Q&A by ID."""
    # Create dataset
    dataset = Dataset(
        name=sample_dataset_data["name"],
        description=sample_dataset_data["description"],
    )
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    # Create Q&A record
    qa = QASource.from_qa_generation(
        question=sample_qa_data["question"],
        answer=sample_qa_data["answer"],
        context=sample_qa_data["context"],
        confidence=sample_qa_data["confidence"],
        source_url=sample_qa_data["source_url"],
        dataset_id=str(dataset.id),
    )
    test_db.add(qa)
    test_db.commit()
    test_db.refresh(qa)

    response = client.get(f"/q_a/id/{qa.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == qa.id
    assert data["question"] == sample_qa_data["question"]
    assert data["answer"] == sample_qa_data["answer"]
    assert data["context"] == sample_qa_data["context"]
    assert data["confidence"] == sample_qa_data["confidence"]
    assert data["source_url"] == sample_qa_data["source_url"]
    assert data["dataset"]["id"] == dataset.id
    assert data["dataset"]["name"] == dataset.name


def test_get_qa_by_id_not_found(client: TestClient):
    """Test getting a non-existent Q&A."""
    response = client.get("/q_a/id/non-existent-id")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_qa_response_includes_metadata(
    client: TestClient,
    test_db: Session,
    sample_dataset_data: dict,
    sample_qa_data: dict,
):
    """Test that Q&A response includes metadata."""
    # Create dataset
    dataset = Dataset(
        name=sample_dataset_data["name"],
        description=sample_dataset_data["description"],
    )
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    # Create Q&A record
    qa = QASource.from_qa_generation(
        question=sample_qa_data["question"],
        answer=sample_qa_data["answer"],
        context=sample_qa_data["context"],
        confidence=sample_qa_data["confidence"],
        source_url=sample_qa_data["source_url"],
        dataset_id=str(dataset.id),
    )
    test_db.add(qa)
    test_db.commit()
    test_db.refresh(qa)

    response = client.get(f"/q_a/id/{qa.id}")
    assert response.status_code == 200
    data = response.json()
    assert "metadata" in data
    assert "created_at" in data
    assert "updated_at" in data
    metadata = data["metadata"]
    assert "context_length" in metadata
    assert "question_length" in metadata
    assert "answer_length" in metadata
