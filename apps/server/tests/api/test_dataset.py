"""
Tests for dataset API endpoints.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

# Datasets are now created/read/deleted in Langfuse (the source of truth), so
# these tests mock the Langfuse-backed view functions.


def test_create_dataset_success(client: TestClient):
    """Test successful dataset creation."""
    created = {
        "id": "test_dataset",
        "name": "test_dataset",
        "description": "A test dataset",
        "message": "Dataset created successfully",
    }
    with patch("server.api.dataset.create_dataset_view", return_value=created):
        response = client.post(
            "/dataset",
            params={"name": "test_dataset", "description": "A test dataset"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_dataset"
    assert data["message"] == "Dataset created successfully"


def test_create_dataset_without_description(client: TestClient):
    """Test dataset creation without description."""
    created = {
        "id": "test_no_desc",
        "name": "test_no_desc",
        "description": None,
        "message": "Dataset created successfully",
    }
    with patch("server.api.dataset.create_dataset_view", return_value=created):
        response = client.post("/dataset", params={"name": "test_no_desc"})
    assert response.status_code == 200
    assert response.json()["name"] == "test_no_desc"


def test_create_dataset_duplicate_name(client: TestClient):
    """Test that creating a dataset with duplicate name fails."""
    with patch(
        "server.api.dataset.create_dataset_view",
        side_effect=ValueError("Dataset 'x' already exists"),
    ):
        response = client.post("/dataset", params={"name": "x"})
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def _ds_view(name, **extra):
    return {
        "id": f"lf-{name}",
        "name": name,
        "description": "d",
        "target_language": None,
        "qa_sources_count": extra.get("qa_sources_count", 0),
        "created_at": None,
    }


def test_get_all_datasets_empty(client: TestClient):
    """Test getting all datasets when Langfuse has none."""
    with patch("server.api.dataset.list_datasets_view", return_value=[]):
        response = client.get("/dataset")
    assert response.status_code == 200
    assert response.json() == []


def test_get_all_datasets(client: TestClient):
    """Test getting all datasets from Langfuse."""
    views = [_ds_view("dataset1"), _ds_view("dataset2"), _ds_view("dataset3")]
    with patch("server.api.dataset.list_datasets_view", return_value=views):
        response = client.get("/dataset")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3
    assert all("id" in item and "name" in item for item in data)


def test_get_dataset_by_name(client: TestClient):
    """Test getting a specific dataset by name."""
    with patch(
        "server.api.dataset.get_dataset_view", return_value=_ds_view("test_dataset")
    ):
        response = client.get("/dataset", params={"dataset_id": "test_dataset"})
    assert response.status_code == 200
    assert response.json()["name"] == "test_dataset"


def test_get_dataset_by_name_not_found(client: TestClient):
    """Test getting a non-existent dataset."""
    with patch("server.api.dataset.get_dataset_view", return_value=None):
        response = client.get("/dataset", params={"dataset_id": "nope"})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_delete_dataset(client: TestClient):
    """Test deleting a dataset (Langfuse items + Qdrant cascade)."""
    result = {
        "message": "Deleted 2 item(s) from 'my_dataset'.",
        "dataset_id": "my_dataset",
        "records_deleted": 2,
    }
    with patch("server.api.dataset.delete_dataset_view", return_value=result):
        response = client.delete("/dataset/my_dataset")
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_id"] == "my_dataset"
    assert data["records_deleted"] == 2


def test_delete_dataset_not_found(client: TestClient):
    """Test deleting a non-existent dataset."""
    with patch(
        "server.api.dataset.delete_dataset_view",
        side_effect=ValueError("Dataset 'nope' not found"),
    ):
        response = client.delete("/dataset/nope")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_analyze_similarities_dataset_not_found(client: TestClient):
    """Test analyze similarities with non-existent dataset."""
    with patch(
        "server.api.dataset.analyze_similarities_view",
        side_effect=ValueError("Dataset 'nope' not found"),
    ):
        response = client.get("/dataset/nope/analyze-similarities")
    assert response.status_code == 404


def test_clean_similarities_dataset_not_found(client: TestClient):
    """Test clean similarities with non-existent dataset."""
    with patch(
        "server.api.dataset.clean_similarities_view",
        side_effect=ValueError("Dataset 'nope' not found"),
    ):
        response = client.post("/dataset/nope/clean-similarities")
    assert response.status_code == 404


def test_analyze_similarities_success(client: TestClient):
    """Test successful analyze similarities."""
    fake = {
        "dataset_id": "my_dataset",
        "dataset_name": "my_dataset",
        "threshold": 0.8,
        "total_records": 2,
        "similar_pairs_found": 1,
        "similarities": [
            {
                "record1_id": "aaaa1111",
                "record2_id": "bbbb2222",
                "similarity": 0.9,
                "question1": "What is Python?",
                "question2": "What is Python used for?",
            }
        ],
    }
    with patch("server.api.dataset.analyze_similarities_view", return_value=fake):
        response = client.get(
            "/dataset/my_dataset/analyze-similarities", params={"threshold": 0.8}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_id"] == "my_dataset"
    assert data["total_records"] == 2


def test_clean_similarities_success(client: TestClient):
    """Test successful clean similarities."""
    fake = {
        "dataset_id": "my_dataset",
        "dataset_name": "my_dataset",
        "threshold": 0.8,
        "total_records": 2,
        "removed_records": 1,
        "details": [],
        "removed_items": [],
    }
    with patch("server.api.dataset.clean_similarities_view", return_value=fake):
        response = client.post(
            "/dataset/my_dataset/clean-similarities", params={"threshold": 0.8}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_id"] == "my_dataset"
    assert data["removed_records"] == 1


def test_resolve_pair_success(client: TestClient):
    """Test arbitrating a single duplicate pair."""
    fake = {
        "dataset_id": "my_dataset",
        "dataset_name": "my_dataset",
        "removed_id": "aaaa1111",
        "removed_question": "What is Python?",
    }
    with patch("server.api.dataset.resolve_similarity_pair", return_value=fake):
        response = client.post(
            "/dataset/my_dataset/resolve-pair", json={"remove_id": "aaaa1111"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["removed_id"] == "aaaa1111"
    assert data["removed_question"] == "What is Python?"


def test_resolve_pair_dataset_not_found(client: TestClient):
    """Test resolving a pair in a non-existent dataset."""
    with patch(
        "server.api.dataset.resolve_similarity_pair",
        side_effect=ValueError("Dataset 'nope' not found"),
    ):
        response = client.post(
            "/dataset/nope/resolve-pair", json={"remove_id": "aaaa1111"}
        )
    assert response.status_code == 404


def test_resolve_pair_record_not_found(client: TestClient):
    """Test resolving a pair with an id that matches no record."""
    with patch(
        "server.api.dataset.resolve_similarity_pair",
        side_effect=ValueError("Record 'zzzz9999' not found in dataset 'my_dataset'"),
    ):
        response = client.post(
            "/dataset/my_dataset/resolve-pair", json={"remove_id": "zzzz9999"}
        )
    assert response.status_code == 404


def test_resolve_pair_ambiguous_id(client: TestClient):
    """Test resolving a pair with a prefix that matches more than one record."""
    from server.services.dataset_reads import AmbiguousRecordError

    with patch(
        "server.api.dataset.resolve_similarity_pair",
        side_effect=AmbiguousRecordError("Record id 'aaaa' matches 2 items"),
    ):
        response = client.post(
            "/dataset/my_dataset/resolve-pair", json={"remove_id": "aaaa"}
        )
    assert response.status_code == 409
