"""
Tests for Langfuse API endpoints.
"""

from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.models.dataset import Dataset, QASource


def test_preview_dataset_not_found(client: TestClient, test_db: Session):
    """Test preview endpoint when dataset doesn't exist."""
    response = client.get("/langfuse/preview?dataset_name=nonexistent")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_preview_dataset_no_qa_data(client: TestClient, test_db: Session):
    """Test preview endpoint when dataset exists but has no QA data."""
    # Create a dataset without QA records
    dataset = Dataset(name="empty-dataset", description="Empty dataset")
    test_db.add(dataset)
    test_db.commit()

    response = client.get("/langfuse/preview?dataset_name=empty-dataset")
    assert response.status_code == 404
    assert "No QA data found" in response.json()["detail"]


def test_preview_dataset_success(client: TestClient, test_db: Session):
    """Test preview endpoint with valid dataset and QA data."""
    # Create a dataset with QA records
    dataset = Dataset(name="test-dataset", description="Test dataset")
    test_db.add(dataset)
    test_db.commit()

    # Add QA records
    qa = QASource.from_qa_generation(
        question="What is Python?",
        answer="A programming language",
        context="Python is a high-level programming language",
        source_url="https://example.com",
        dataset_id=str(dataset.id),
    )
    test_db.add(qa)
    test_db.commit()

    response = client.get("/langfuse/preview?dataset_name=test-dataset")
    assert response.status_code == 200
    data = response.json()
    assert "sample_items" in data
    assert "total_items" in data
    assert data["total_items"] == 1


def test_preview_dataset_multiple_items(client: TestClient, test_db: Session):
    """Test preview endpoint returns max 3 items."""
    dataset = Dataset(name="multi-dataset", description="Multi item dataset")
    test_db.add(dataset)
    test_db.commit()

    # Add 5 QA records
    for i in range(5):
        qa = QASource.from_qa_generation(
            question=f"Question {i}?",
            answer=f"Answer {i}",
            context=f"Context {i}",
            source_url=f"https://example.com/{i}",
            dataset_id=str(dataset.id),
        )
        test_db.add(qa)
    test_db.commit()

    response = client.get("/langfuse/preview?dataset_name=multi-dataset")
    assert response.status_code == 200
    data = response.json()
    assert len(data["sample_items"]) == 3
    assert data["total_items"] == 5


def test_export_dataset_not_found(client: TestClient, test_db: Session):
    """Test export endpoint when dataset doesn't exist."""
    response = client.post("/langfuse/export?dataset_name=nonexistent")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_export_dataset_no_qa_data(client: TestClient, test_db: Session):
    """Test export endpoint when dataset exists but has no QA data."""
    dataset = Dataset(name="empty-export", description="Empty dataset")
    test_db.add(dataset)
    test_db.commit()

    response = client.post("/langfuse/export?dataset_name=empty-export")
    assert response.status_code == 404
    assert "No QA data found" in response.json()["detail"]


def test_export_dataset_success(client: TestClient, test_db: Session):
    """Test export endpoint with valid dataset."""
    dataset = Dataset(name="export-test", description="Export test dataset")
    test_db.add(dataset)
    test_db.commit()

    qa = QASource.from_qa_generation(
        question="Test question?",
        answer="Test answer",
        context="Test context",
        source_url="https://example.com",
        dataset_id=str(dataset.id),
    )
    test_db.add(qa)
    test_db.commit()

    with patch("server.api.langfuse.create_langfuse_dataset_with_items") as mock_create:
        mock_create.return_value = {
            "dataset_id": "test-id",
            "dataset_name": "export-test",
            "total_items": 1,
            "created_items": ["item1"],
            "created_count": 1,
            "failed_items": [],
            "failed_count": 0,
        }

        response = client.post("/langfuse/export?dataset_name=export-test")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Dataset exported successfully"
        assert data["dataset_name"] == "export-test"


def test_export_dataset_with_custom_name(client: TestClient, test_db: Session):
    """Test export endpoint with custom Langfuse dataset name."""
    dataset = Dataset(name="original-name", description="Test dataset")
    test_db.add(dataset)
    test_db.commit()

    qa = QASource.from_qa_generation(
        question="Test question?",
        answer="Test answer",
        context="Test context",
        source_url="https://example.com",
        dataset_id=str(dataset.id),
    )
    test_db.add(qa)
    test_db.commit()

    with patch("server.api.langfuse.create_langfuse_dataset_with_items") as mock_create:
        mock_create.return_value = {
            "dataset_id": "custom-id",
            "dataset_name": "custom-langfuse-name",
            "total_items": 1,
            "created_items": ["item1"],
            "created_count": 1,
            "failed_items": [],
            "failed_count": 0,
        }

        response = client.post(
            "/langfuse/export?dataset_name=original-name&langfuse_dataset_name=custom-langfuse-name"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["langfuse_dataset_name"] == "custom-langfuse-name"


def test_export_dataset_langfuse_error(client: TestClient, test_db: Session):
    """Test export endpoint when Langfuse API fails."""
    dataset = Dataset(name="error-test", description="Error test dataset")
    test_db.add(dataset)
    test_db.commit()

    qa = QASource.from_qa_generation(
        question="Test question?",
        answer="Test answer",
        context="Test context",
        source_url="https://example.com",
        dataset_id=str(dataset.id),
    )
    test_db.add(qa)
    test_db.commit()

    with patch("server.api.langfuse.create_langfuse_dataset_with_items") as mock_create:
        mock_create.side_effect = Exception("Langfuse API error")

        response = client.post("/langfuse/export?dataset_name=error-test")
        assert response.status_code == 500
        assert "Error exporting to Langfuse" in response.json()["detail"]


def test_list_dataset_versions_success(client: TestClient):
    """Versions endpoint returns the run history from Langfuse."""
    versions = [
        {"run_name": "v2", "version": 2, "item_count": 8},
        {"run_name": "v1", "version": 1, "item_count": 5},
    ]
    with (
        patch("server.api.langfuse.is_langfuse_configured", return_value=True),
        patch(
            "server.api.langfuse.list_dataset_runs", return_value=versions
        ) as mock_list,
    ):
        response = client.get("/langfuse/versions/my-dataset")

    assert response.status_code == 200
    data = response.json()
    assert data["dataset_name"] == "my-dataset"
    assert data["total"] == 2
    assert data["versions"][0]["run_name"] == "v2"
    mock_list.assert_called_once_with("my-dataset")


def test_list_dataset_versions_not_configured(client: TestClient):
    """Versions endpoint returns 503 when Langfuse is not configured."""
    with patch("server.api.langfuse.is_langfuse_configured", return_value=False):
        response = client.get("/langfuse/versions/my-dataset")
    assert response.status_code == 503


def test_list_dataset_versions_upstream_error(client: TestClient):
    """A Langfuse failure surfaces as a 502."""
    with (
        patch("server.api.langfuse.is_langfuse_configured", return_value=True),
        patch(
            "server.api.langfuse.list_dataset_runs",
            side_effect=Exception("boom"),
        ),
    ):
        response = client.get("/langfuse/versions/my-dataset")
    assert response.status_code == 502
