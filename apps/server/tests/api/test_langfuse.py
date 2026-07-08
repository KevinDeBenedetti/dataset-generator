"""
Tests for Langfuse API endpoints.
"""

from unittest.mock import patch
from fastapi.testclient import TestClient

# Preview/export now read Q/A items directly from Langfuse (the source of
# truth), so these tests mock the Langfuse-backed helpers instead of the DB.


def _ds_view(name: str):
    return {
        "id": name,
        "name": name,
        "description": None,
        "target_language": None,
        "qa_sources_count": 0,
        "created_at": None,
    }


def _item(question: str, answer: str, context: str = "", item_id: str = "item1"):
    return {
        "id": item_id,
        "status": "ACTIVE",
        "input": {"question": question, "context": context},
        "expected_output": {"answer": answer},
        "metadata": {},
    }


def test_preview_dataset_not_found(client: TestClient):
    """Test preview endpoint when dataset doesn't exist."""
    with (
        patch("server.api.langfuse.get_dataset_view", return_value=None),
        patch("server.api.langfuse.list_datasets", return_value=[]),
    ):
        response = client.get("/langfuse/preview?dataset_name=nonexistent")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_preview_dataset_no_qa_data(client: TestClient):
    """Test preview endpoint when dataset exists but has no QA data."""
    with (
        patch(
            "server.api.langfuse.get_dataset_view",
            return_value=_ds_view("empty-dataset"),
        ),
        patch("server.api.langfuse.get_dataset_items", return_value=[]),
    ):
        response = client.get("/langfuse/preview?dataset_name=empty-dataset")
    assert response.status_code == 404
    assert "No QA data found" in response.json()["detail"]


def test_preview_dataset_success(client: TestClient):
    """Test preview endpoint with valid dataset and QA data."""
    items = [_item("What is Python?", "A programming language")]
    with (
        patch(
            "server.api.langfuse.get_dataset_view",
            return_value=_ds_view("test-dataset"),
        ),
        patch("server.api.langfuse.get_dataset_items", return_value=items),
    ):
        response = client.get("/langfuse/preview?dataset_name=test-dataset")
    assert response.status_code == 200
    data = response.json()
    assert "sample_items" in data
    assert "total_items" in data
    assert data["total_items"] == 1


def test_preview_dataset_multiple_items(client: TestClient):
    """Test preview endpoint returns max 3 items."""
    items = [
        _item(f"Question {i}?", f"Answer {i}", item_id=f"item{i}") for i in range(5)
    ]
    with (
        patch(
            "server.api.langfuse.get_dataset_view",
            return_value=_ds_view("multi-dataset"),
        ),
        patch("server.api.langfuse.get_dataset_items", return_value=items),
    ):
        response = client.get("/langfuse/preview?dataset_name=multi-dataset")
    assert response.status_code == 200
    data = response.json()
    assert len(data["sample_items"]) == 3
    assert data["total_items"] == 5


def test_export_dataset_not_configured(client: TestClient):
    """Export endpoint returns 503 when Langfuse is not configured."""
    with patch("server.api.langfuse.is_langfuse_configured", return_value=False):
        response = client.post("/langfuse/export?dataset_name=anything")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()


def test_export_dataset_not_found(client: TestClient):
    """Test export endpoint when dataset doesn't exist."""
    with (
        patch("server.api.langfuse.is_langfuse_configured", return_value=True),
        patch("server.api.langfuse.get_dataset_view", return_value=None),
        patch("server.api.langfuse.list_datasets", return_value=[]),
    ):
        response = client.post("/langfuse/export?dataset_name=nonexistent")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_export_dataset_no_qa_data(client: TestClient):
    """Test export endpoint when dataset exists but has no QA data."""
    with (
        patch("server.api.langfuse.is_langfuse_configured", return_value=True),
        patch(
            "server.api.langfuse.get_dataset_view",
            return_value=_ds_view("empty-export"),
        ),
        patch("server.api.langfuse.get_dataset_items", return_value=[]),
    ):
        response = client.post("/langfuse/export?dataset_name=empty-export")
    assert response.status_code == 404
    assert "No QA data found" in response.json()["detail"]


def test_export_dataset_success(client: TestClient):
    """Test export endpoint with valid dataset."""
    items = [_item("Test question?", "Test answer")]
    with (
        patch("server.api.langfuse.is_langfuse_configured", return_value=True),
        patch(
            "server.api.langfuse.get_dataset_view",
            return_value=_ds_view("export-test"),
        ),
        patch("server.api.langfuse.get_dataset_items", return_value=items),
        patch("server.api.langfuse.create_langfuse_dataset_with_items") as mock_create,
    ):
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


def test_export_dataset_with_custom_name(client: TestClient):
    """Test export endpoint with custom Langfuse dataset name."""
    items = [_item("Test question?", "Test answer")]
    with (
        patch("server.api.langfuse.is_langfuse_configured", return_value=True),
        patch(
            "server.api.langfuse.get_dataset_view",
            return_value=_ds_view("original-name"),
        ),
        patch("server.api.langfuse.get_dataset_items", return_value=items),
        patch("server.api.langfuse.create_langfuse_dataset_with_items") as mock_create,
    ):
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


def test_export_dataset_langfuse_error(client: TestClient):
    """Test export endpoint when Langfuse API fails."""
    items = [_item("Test question?", "Test answer")]
    with (
        patch("server.api.langfuse.is_langfuse_configured", return_value=True),
        patch(
            "server.api.langfuse.get_dataset_view",
            return_value=_ds_view("error-test"),
        ),
        patch("server.api.langfuse.get_dataset_items", return_value=items),
        patch("server.api.langfuse.create_langfuse_dataset_with_items") as mock_create,
    ):
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


def test_list_langfuse_datasets_success(client: TestClient):
    """Datasets endpoint returns the dataset list from Langfuse."""
    datasets = [
        {"id": "d2", "name": "beta", "item_count": 8, "version": 2},
        {"id": "d1", "name": "alpha", "item_count": 5, "version": 1},
    ]
    with (
        patch("server.api.langfuse.is_langfuse_configured", return_value=True),
        patch("server.api.langfuse.list_datasets", return_value=datasets) as mock_list,
    ):
        response = client.get("/langfuse/datasets")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["datasets"][0]["name"] == "beta"
    mock_list.assert_called_once_with()


def test_list_langfuse_datasets_not_configured(client: TestClient):
    """Datasets endpoint returns 503 when Langfuse is not configured."""
    with patch("server.api.langfuse.is_langfuse_configured", return_value=False):
        response = client.get("/langfuse/datasets")
    assert response.status_code == 503


def test_list_langfuse_datasets_upstream_error(client: TestClient):
    """A Langfuse failure surfaces as a 502."""
    with (
        patch("server.api.langfuse.is_langfuse_configured", return_value=True),
        patch("server.api.langfuse.list_datasets", side_effect=Exception("boom")),
    ):
        response = client.get("/langfuse/datasets")
    assert response.status_code == 502
