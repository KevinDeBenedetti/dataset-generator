"""Tests for the Langfuse-backed dataset read service (Phase 2b)."""

from unittest.mock import MagicMock, patch

import pytest

from server.services.dataset_reads import (
    analyze_similarities_view,
    clean_similarities_view,
    create_dataset,
    delete_dataset,
    get_dataset_view,
    get_qa_view,
    list_datasets_view,
)
from server.services.langfuse import LangfuseUnavailableError


def _item(item_id, question, answer="A sufficiently long answer.", *, confidence=0.9):
    return {
        "id": item_id,
        "status": "ACTIVE",
        "input": {"question": question, "context": "ctx", "source_url": "u"},
        "expected_output": {"answer": answer, "confidence": confidence},
        "metadata": {},
        "created_at": "2026-01-01T00:00:00Z",
    }


def _dataset(name, item_count=2):
    return {
        "id": f"lf-{name}",
        "name": name,
        "description": "d",
        "item_count": item_count,
        "created_at": "2026-01-01T00:00:00Z",
        "metadata": {},
    }


@pytest.fixture(autouse=True)
def _langfuse_up():
    with patch(
        "server.services.dataset_reads.is_langfuse_available", return_value=True
    ):
        yield


def test_views_raise_when_langfuse_unavailable():
    with patch(
        "server.services.dataset_reads.is_langfuse_available", return_value=False
    ):
        with pytest.raises(LangfuseUnavailableError):
            list_datasets_view()


def test_list_datasets_view_maps_shape():
    # The Q/A count is the live item count, not the dataset's metadata value.
    with (
        patch(
            "server.services.dataset_reads.list_datasets",
            return_value=[_dataset("alpha", 5)],
        ),
        patch(
            "server.services.dataset_reads.count_dataset_items",
            return_value=42,
        ),
    ):
        result = list_datasets_view()
    assert result == [
        {
            "id": "lf-alpha",
            "name": "alpha",
            "description": "d",
            "target_language": None,
            "qa_sources_count": 42,
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]


def test_list_datasets_view_keeps_metadata_count_when_count_fails():
    # If the live count errors, the metadata-derived value is kept (best-effort).
    with (
        patch(
            "server.services.dataset_reads.list_datasets",
            return_value=[_dataset("alpha", 5)],
        ),
        patch(
            "server.services.dataset_reads.count_dataset_items",
            side_effect=RuntimeError("boom"),
        ),
    ):
        result = list_datasets_view()
    assert result[0]["qa_sources_count"] == 5


def test_get_dataset_view_found_and_missing():
    with patch(
        "server.services.dataset_reads.list_datasets",
        return_value=[_dataset("alpha"), _dataset("beta")],
    ):
        beta = get_dataset_view("beta")
        assert beta is not None and beta["name"] == "beta"
        assert get_dataset_view("ghost") is None


def test_get_qa_view_paginates_newest_first():
    items = [_item(f"h{i}", f"Question {i}") for i in range(5)]
    with patch("server.services.dataset_reads.get_dataset_items", return_value=items):
        view = get_qa_view("ds", limit=2, offset=0)
    assert view["total_count"] == 5
    assert view["returned_count"] == 2
    assert view["dataset_id"] == "ds"


def test_get_qa_view_unknown_dataset_raises():
    with patch("server.services.dataset_reads.get_dataset_items", return_value=[]):
        with patch("server.services.dataset_reads.list_datasets", return_value=[]):
            with pytest.raises(ValueError, match="not found"):
                get_qa_view("ghost")


def test_analyze_similarities_finds_near_duplicates():
    items = [
        _item("a", "What is Python used for?"),
        _item("b", "What is Python used for??"),  # near-identical
        _item("c", "Completely unrelated question about cats?"),
    ]
    with patch(
        "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
    ):
        with patch(
            "server.services.dataset_reads.get_dataset_items", return_value=items
        ):
            result = analyze_similarities_view("ds", threshold=0.8)
    assert result["total_records"] == 3
    assert result["similar_pairs_found"] == 1


def test_clean_similarities_deletes_lower_confidence():
    items = [
        _item("keep", "What is Python used for?", confidence=0.95),
        _item("drop", "What is Python used for??", confidence=0.50),
        _item("solo", "An unrelated question about cats?", confidence=0.9),
    ]
    with patch(
        "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
    ):
        with patch(
            "server.services.dataset_reads.get_dataset_items", return_value=items
        ):
            with patch(
                "server.services.dataset_reads.delete_dataset_item"
            ) as mock_delete:
                result = clean_similarities_view("ds", threshold=0.8)

    assert result["removed_records"] == 1
    # The lower-confidence duplicate is the one deleted.
    mock_delete.assert_called_once_with("drop")
    assert result["removed_items"][0]["id"] == "drop"


def test_create_dataset_creates_when_absent():
    client = MagicMock()
    with patch("server.services.dataset_reads.list_datasets", return_value=[]):
        with patch("server.services.dataset_reads.get_client", return_value=client):
            result = create_dataset("brand_new", "desc")
    assert result["name"] == "brand_new"
    assert result["message"] == "Dataset created successfully"
    client.create_dataset.assert_called_once()


def test_create_dataset_rejects_duplicate():
    with patch(
        "server.services.dataset_reads.list_datasets",
        return_value=[_dataset("existing")],
    ):
        with pytest.raises(ValueError, match="already exists"):
            create_dataset("existing")


def test_delete_dataset_deletes_items_and_qdrant():
    items = [_item("a", "q1"), _item("b", "q2")]
    with patch(
        "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
    ):
        with patch(
            "server.services.dataset_reads.get_dataset_items", return_value=items
        ):
            with patch("server.services.dataset_reads.delete_dataset_item") as mock_del:
                with patch(
                    "server.services.qdrant.delete_collection_for", return_value=True
                ) as mock_drop:
                    result = delete_dataset("ds")

    assert result["records_deleted"] == 2
    assert mock_del.call_count == 2
    mock_drop.assert_called_once_with("ds")
    assert "Qdrant" in result["message"]


def test_delete_dataset_unknown_raises():
    with patch("server.services.dataset_reads.list_datasets", return_value=[]):
        with pytest.raises(ValueError, match="not found"):
            delete_dataset("ghost")
