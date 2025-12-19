"""
Tests for Q&A API endpoints.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.models.dataset import Dataset, QASource


def test_get_qa_by_dataset_not_found(client: TestClient):
    """Test getting Q&A for non-existent dataset."""
    response = client.get("/q_a/non-existent-id")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_qa_by_dataset_empty(
    client: TestClient, test_db: Session, sample_dataset_data: dict
):
    """Test getting Q&A for dataset with no records."""
    dataset = Dataset(
        name=sample_dataset_data["name"],
        description=sample_dataset_data["description"],
    )
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    response = client.get(f"/q_a/{dataset.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_id"] == dataset.id
    assert data["dataset_name"] == sample_dataset_data["name"]
    assert data["total_count"] == 0
    assert data["returned_count"] == 0
    assert len(data["qa_data"]) == 0


def test_get_qa_by_dataset(
    client: TestClient,
    test_db: Session,
    sample_dataset_data: dict,
    sample_qa_data: dict,
):
    """Test getting Q&A records for a dataset."""
    # Create dataset
    dataset = Dataset(
        name=sample_dataset_data["name"],
        description=sample_dataset_data["description"],
    )
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    # Create multiple Q&A records
    qa_records = []
    for i in range(3):
        qa = QASource.from_qa_generation(
            question=f"Question {i}",
            answer=f"Answer {i}",
            context=f"Context {i}",
            confidence=0.9,
            source_url=f"https://example.com/{i}",
            dataset_id=str(dataset.id),
            index=i,
        )
        test_db.add(qa)
        qa_records.append(qa)
    test_db.commit()

    response = client.get(f"/q_a/{dataset.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_id"] == dataset.id
    assert data["total_count"] == 3
    assert data["returned_count"] == 3
    assert len(data["qa_data"]) == 3


def test_get_qa_by_dataset_with_pagination(
    client: TestClient, test_db: Session, sample_dataset_data: dict
):
    """Test Q&A pagination."""
    # Create dataset
    dataset = Dataset(
        name=sample_dataset_data["name"],
        description=sample_dataset_data["description"],
    )
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    # Create 15 Q&A records
    for i in range(15):
        qa = QASource.from_qa_generation(
            question=f"Question {i}",
            answer=f"Answer {i}",
            context=f"Context {i}",
            confidence=0.9,
            source_url=f"https://example.com/{i}",
            dataset_id=str(dataset.id),
            index=i,
        )
        test_db.add(qa)
    test_db.commit()

    # Test first page
    response = client.get(f"/q_a/{dataset.id}", params={"limit": 5, "offset": 0})
    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 15
    assert data["returned_count"] == 5
    assert data["offset"] == 0
    assert data["limit"] == 5

    # Test second page
    response = client.get(f"/q_a/{dataset.id}", params={"limit": 5, "offset": 5})
    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 15
    assert data["returned_count"] == 5
    assert data["offset"] == 5

    # Test last page
    response = client.get(f"/q_a/{dataset.id}", params={"limit": 5, "offset": 10})
    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 15
    assert data["returned_count"] == 5


def test_get_qa_by_dataset_limit_validation(
    client: TestClient, test_db: Session, sample_dataset_data: dict
):
    """Test Q&A endpoint with invalid limit values."""
    dataset = Dataset(
        name=sample_dataset_data["name"],
        description=sample_dataset_data["description"],
    )
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    # Test with limit too high (should be capped or rejected)
    response = client.get(f"/q_a/{dataset.id}", params={"limit": 2000})
    assert response.status_code == 422  # Validation error

    # Test with negative limit
    response = client.get(f"/q_a/{dataset.id}", params={"limit": -1})
    assert response.status_code == 422


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
