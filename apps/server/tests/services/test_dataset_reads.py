"""Tests for the Langfuse-backed dataset read service (Phase 2b)."""

from unittest.mock import MagicMock, patch

import pytest

from server.services.dataset_reads import (
    AmbiguousRecordError,
    analyze_similarities_view,
    clean_similarities_view,
    create_dataset,
    delete_dataset,
    get_dataset_sources_view,
    get_dataset_view,
    get_qa_stats_view,
    get_qa_view,
    list_datasets_view,
    resolve_similarity_pair,
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


def test_get_qa_stats_aggregates_scores():
    items = [
        _item("a", "q1", confidence=0.95),
        _item("b", "q2", confidence=0.85),
        _item("c", "q3", confidence=0.75),
        _item("d", "q4", confidence=0.5),
    ]
    with patch("server.services.dataset_reads.get_dataset_items", return_value=items):
        stats = get_qa_stats_view("ds", score_threshold=0.8)

    assert stats["total_count"] == 4
    assert stats["scored_count"] == 4
    assert stats["average_score"] == round((0.95 + 0.85 + 0.75 + 0.5) / 4, 4)
    assert stats["below_threshold_count"] == 2
    assert stats["validated_count"] == 2
    assert [(b["label"], b["count"]) for b in stats["distribution"]] == [
        ("0.9–1.0", 1),
        ("0.8–0.9", 1),
        ("0.7–0.8", 1),
        ("< 0.7", 1),
    ]


def test_get_qa_stats_ignores_unscored_and_reads_metadata_fallback():
    # One unscored item (no confidence anywhere) must not drag the average to 0;
    # one item scored only via metadata (the generation sync path) must count.
    unscored = _item("u", "q-unscored")
    unscored["expected_output"] = {"answer": "a"}
    via_metadata = _item("m", "q-meta")
    via_metadata["expected_output"] = {"answer": "a"}
    via_metadata["metadata"] = {"confidence": 0.9}

    with patch(
        "server.services.dataset_reads.get_dataset_items",
        return_value=[unscored, via_metadata],
    ):
        stats = get_qa_stats_view("ds")

    assert stats["total_count"] == 2
    assert stats["scored_count"] == 1
    assert stats["average_score"] == 0.9


def test_get_qa_stats_empty_existing_dataset():
    with patch("server.services.dataset_reads.get_dataset_items", return_value=[]):
        with patch(
            "server.services.dataset_reads.list_datasets",
            return_value=[_dataset("ds")],
        ):
            stats = get_qa_stats_view("ds")
    assert stats["total_count"] == 0
    assert stats["average_score"] is None


def test_get_qa_stats_unknown_dataset_raises():
    with patch("server.services.dataset_reads.get_dataset_items", return_value=[]):
        with patch("server.services.dataset_reads.list_datasets", return_value=[]):
            with pytest.raises(ValueError, match="not found"):
                get_qa_stats_view("ghost")


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


def test_resolve_pair_deletes_by_prefix():
    items = [_item("abcdef1234567890", "q1"), _item("zzzzzz9876543210", "q2")]
    with patch(
        "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
    ):
        with patch(
            "server.services.dataset_reads.get_dataset_items", return_value=items
        ):
            with patch(
                "server.services.dataset_reads.delete_dataset_item"
            ) as mock_delete:
                result = resolve_similarity_pair("ds", "abcdef12")

    mock_delete.assert_called_once_with("abcdef1234567890")
    assert result["removed_id"] == "abcdef1234567890"
    assert result["removed_question"] == "q1"


def test_resolve_pair_ambiguous_prefix_raises():
    items = [_item("abcdef1234", "q1"), _item("abcdef1299", "q2")]
    with patch(
        "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
    ):
        with patch(
            "server.services.dataset_reads.get_dataset_items", return_value=items
        ):
            with pytest.raises(AmbiguousRecordError):
                resolve_similarity_pair("ds", "abcdef12")


def test_resolve_pair_exact_id_wins_over_prefix():
    # An id that is itself a prefix of another must match exactly, not both.
    items = [_item("abcd", "q1"), _item("abcdef", "q2")]
    with patch(
        "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
    ):
        with patch(
            "server.services.dataset_reads.get_dataset_items", return_value=items
        ):
            with patch(
                "server.services.dataset_reads.delete_dataset_item"
            ) as mock_delete:
                result = resolve_similarity_pair("ds", "abcd")

    mock_delete.assert_called_once_with("abcd")
    assert result["removed_question"] == "q1"


def test_resolve_pair_unknown_record_raises():
    with patch(
        "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
    ):
        with patch("server.services.dataset_reads.get_dataset_items", return_value=[]):
            with pytest.raises(ValueError, match="not found"):
                resolve_similarity_pair("ds", "nope1234")


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


# --- sources & analysis history ----------------------------------------------


def _sourced_item(item_id, source_url, created_at):
    """A minimal active item carrying a source URL and a creation date."""
    return {
        "id": item_id,
        "status": "ACTIVE",
        "input": {"question": "q?", "context": "ctx", "source_url": source_url},
        "expected_output": {"answer": "a", "confidence": 0.9},
        "metadata": {},
        "created_at": created_at,
    }


def _run(name, version, source_url, **metadata):
    return {
        "run_name": name,
        "version": version,
        "description": None,
        "item_count": metadata.get("item_count"),
        "source_url": source_url,
        "created_at": "2026-01-03T00:00:00Z",
        "metadata": metadata,
    }


def test_get_sources_view_groups_items_by_source():
    """One row per distinct source_url, busiest first, with a first/last seen."""
    items = [
        _sourced_item("a", "https://docs.example.com/api", "2026-01-02T00:00:00Z"),
        _sourced_item("b", "https://docs.example.com/api", "2026-01-01T00:00:00Z"),
        _sourced_item("c", "file://manual.pdf", "2026-01-01T00:00:00Z"),
    ]
    with (
        patch(
            "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
        ),
        patch("server.services.dataset_reads.get_dataset_items", return_value=items),
        patch("server.services.dataset_reads.list_dataset_runs", return_value=[]),
    ):
        view = get_dataset_sources_view("ds")

    assert view["total_qa"] == 3
    assert view["total_sources"] == 2
    web, file_source = view["sources"]
    assert web["qa_count"] == 2
    assert web["kind"] == "web"
    assert web["label"] == "docs.example.com/api"
    # Aggregated over both items, not just the first one seen.
    assert web["first_seen_at"].startswith("2026-01-01")
    assert web["last_seen_at"].startswith("2026-01-02")
    assert file_source["kind"] == "file"
    assert file_source["label"] == "manual.pdf"


def test_get_sources_view_labels_every_source_kind():
    items = [
        _sourced_item("a", "github://octocat", "2026-01-01T00:00:00Z"),
        _sourced_item("b", "", "2026-01-01T00:00:00Z"),
    ]
    with (
        patch(
            "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
        ),
        patch("server.services.dataset_reads.get_dataset_items", return_value=items),
        patch("server.services.dataset_reads.list_dataset_runs", return_value=[]),
    ):
        view = get_dataset_sources_view("ds")

    by_kind = {s["kind"]: s for s in view["sources"]}
    assert by_kind["github"]["label"] == "octocat"
    # An item with no recorded source still gets a row, with a null URL.
    assert by_kind["unknown"]["url"] is None
    assert by_kind["unknown"]["label"] == "Unknown source"


def test_get_sources_view_tolerates_mixed_timestamp_offsets():
    """Langfuse returns dates with and without an offset — both must aggregate."""
    items = [
        _sourced_item("a", "https://ex.com", "2026-01-02T00:00:00Z"),
        _sourced_item("b", "https://ex.com", "2026-01-01T00:00:00"),
    ]
    with (
        patch(
            "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
        ),
        patch("server.services.dataset_reads.get_dataset_items", return_value=items),
        patch("server.services.dataset_reads.list_dataset_runs", return_value=[]),
    ):
        view = get_dataset_sources_view("ds")

    assert view["sources"][0]["qa_count"] == 2
    assert view["sources"][0]["first_seen_at"].startswith("2026-01-01")


def test_get_sources_view_maps_run_history():
    runs = [
        _run(
            "v2",
            2,
            "https://docs.example.com",
            item_count=5,
            pages_crawled=4,
            total=5,
            exact_duplicates=2,
            similar_duplicates=1,
        )
    ]
    with (
        patch(
            "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
        ),
        patch("server.services.dataset_reads.get_dataset_items", return_value=[]),
        patch("server.services.dataset_reads.list_dataset_runs", return_value=runs),
    ):
        view = get_dataset_sources_view("ds")

    assert view["total_analyses"] == 1
    analysis = view["history"][0]
    assert analysis["run_name"] == "v2"
    assert analysis["version"] == 2
    assert analysis["pages_analyzed"] == 4
    assert analysis["new_pairs"] == 5
    assert analysis["duplicates_skipped"] == 3
    assert analysis["kind"] == "web"


def test_get_sources_view_history_without_stats_is_null_not_zero():
    """A run recorded without stats must not claim "0 duplicates skipped"."""
    with (
        patch(
            "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
        ),
        patch("server.services.dataset_reads.get_dataset_items", return_value=[]),
        patch(
            "server.services.dataset_reads.list_dataset_runs",
            return_value=[_run("v1", 1, "file://a.pdf")],
        ),
    ):
        view = get_dataset_sources_view("ds")

    analysis = view["history"][0]
    assert analysis["duplicates_skipped"] is None
    assert analysis["pages_analyzed"] is None


def test_get_sources_view_survives_unreadable_runs():
    """Runs are best-effort (see sync_qa_to_langfuse): sources still render."""
    items = [_sourced_item("a", "https://ex.com", "2026-01-01T00:00:00Z")]
    with (
        patch(
            "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
        ),
        patch("server.services.dataset_reads.get_dataset_items", return_value=items),
        patch(
            "server.services.dataset_reads.list_dataset_runs",
            side_effect=RuntimeError("boom"),
        ),
    ):
        view = get_dataset_sources_view("ds")

    assert view["total_sources"] == 1
    assert view["history"] == []


def test_get_sources_view_propagates_langfuse_unavailable():
    """A down Langfuse is a 503, not an empty history."""
    with (
        patch(
            "server.services.dataset_reads.list_datasets", return_value=[_dataset("ds")]
        ),
        patch("server.services.dataset_reads.get_dataset_items", return_value=[]),
        patch(
            "server.services.dataset_reads.list_dataset_runs",
            side_effect=LangfuseUnavailableError("down"),
        ),
    ):
        with pytest.raises(LangfuseUnavailableError):
            get_dataset_sources_view("ds")


def test_get_sources_view_unknown_dataset_raises():
    with patch("server.services.dataset_reads.list_datasets", return_value=[]):
        with pytest.raises(ValueError, match="not found"):
            get_dataset_sources_view("ghost")
