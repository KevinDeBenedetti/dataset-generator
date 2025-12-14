"""
Tests for dataset API endpoints.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.models.dataset import Dataset, QASource


def test_create_dataset_success(client: TestClient, sample_dataset_data: dict):
    """Test successful dataset creation."""
    response = client.post(
        "/dataset",
        params={
            "name": sample_dataset_data["name"],
            "description": sample_dataset_data["description"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == sample_dataset_data["name"]
    assert data["description"] == sample_dataset_data["description"]
    assert "id" in data
    assert data["message"] == "Dataset created successfully"


def test_create_dataset_without_description(client: TestClient):
    """Test dataset creation without description."""
    response = client.post("/dataset", params={"name": "test_no_desc"})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_no_desc"
    assert data["description"] is None


def test_create_dataset_duplicate_name(
    client: TestClient, test_db: Session, sample_dataset_data: dict
):
    """Test that creating a dataset with duplicate name fails."""
    # Create first dataset
    dataset = Dataset(
        name=sample_dataset_data["name"],
        description=sample_dataset_data["description"],
    )
    test_db.add(dataset)
    test_db.commit()

    # Try to create duplicate
    response = client.post(
        "/dataset",
        params={
            "name": sample_dataset_data["name"],
            "description": "Another description",
        },
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_get_all_datasets_empty(client: TestClient):
    """Test getting all datasets when none exist."""
    response = client.get("/dataset")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_get_all_datasets(client: TestClient, test_db: Session):
    """Test getting all datasets."""
    # Create some datasets
    datasets = [
        Dataset(name="dataset1", description="First dataset"),
        Dataset(name="dataset2", description="Second dataset"),
        Dataset(name="dataset3", description="Third dataset"),
    ]
    for ds in datasets:
        test_db.add(ds)
    test_db.commit()

    response = client.get("/dataset")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3
    assert all("id" in item for item in data)
    assert all("name" in item for item in data)


def test_get_dataset_by_id(
    client: TestClient, test_db: Session, sample_dataset_data: dict
):
    """Test getting a specific dataset by ID."""
    dataset = Dataset(
        name=sample_dataset_data["name"],
        description=sample_dataset_data["description"],
    )
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    response = client.get("/dataset", params={"dataset_id": dataset.id})
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == dataset.id
    assert data["name"] == sample_dataset_data["name"]


def test_get_dataset_by_id_not_found(client: TestClient):
    """Test getting a non-existent dataset."""
    response = client.get("/dataset", params={"dataset_id": "non-existent-id"})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_delete_dataset(
    client: TestClient, test_db: Session, sample_dataset_data: dict
):
    """Test deleting a dataset."""
    dataset = Dataset(
        name=sample_dataset_data["name"],
        description=sample_dataset_data["description"],
    )
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    response = client.delete(f"/dataset/{dataset.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_id"] == dataset.id
    assert "deleted successfully" in data["message"]

    # Verify dataset is deleted
    deleted = test_db.query(Dataset).filter(Dataset.id == dataset.id).first()
    assert deleted is None


def test_delete_dataset_not_found(client: TestClient):
    """Test deleting a non-existent dataset."""
    response = client.delete("/dataset/non-existent-id")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_delete_dataset_with_qa_records(
    client: TestClient,
    test_db: Session,
    sample_dataset_data: dict,
    sample_qa_data: dict,
):
    """Test deleting a dataset that has associated Q&A records."""
    # Create dataset
    dataset = Dataset(
        name=sample_dataset_data["name"],
        description=sample_dataset_data["description"],
    )
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    # Create Q&A records
    qa_record = QASource.from_qa_generation(
        question=sample_qa_data["question"],
        answer=sample_qa_data["answer"],
        context=sample_qa_data["context"],
        confidence=sample_qa_data["confidence"],
        source_url=sample_qa_data["source_url"],
        dataset_id=dataset.id,
    )
    test_db.add(qa_record)
    test_db.commit()

    # Delete dataset
    response = client.delete(f"/dataset/{dataset.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["records_deleted"] >= 1

    # Verify both dataset and records are deleted
    deleted_dataset = test_db.query(Dataset).filter(Dataset.id == dataset.id).first()
    assert deleted_dataset is None
    deleted_qa = test_db.query(QASource).filter(QASource.dataset_id == dataset.id).all()
    assert len(deleted_qa) == 0


def test_analyze_similarities_dataset_not_found(client: TestClient):
    """Test analyze similarities with non-existent dataset."""
    response = client.get("/dataset/non-existent-id/analyze-similarities")
    assert response.status_code == 404


def test_clean_similarities_dataset_not_found(client: TestClient):
    """Test clean similarities with non-existent dataset."""
    response = client.post("/dataset/non-existent-id/clean-similarities")
    assert response.status_code == 404
