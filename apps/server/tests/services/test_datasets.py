"""Tests for the Postgres-backed dataset service.

These run against the real (throwaway) Postgres rather than mocks: the service
is mostly SQL now — aggregates, a GROUP BY, an ON DELETE CASCADE — and a mocked
session would assert nothing about any of it.
"""

import pytest

from server.services.datasets import (
    AmbiguousRecordError,
    analyze_similarities_view,
    clean_similarities_view,
    create_dataset,
    delete_dataset,
    duplicate_dataset,
    get_dataset_pairs,
    get_dataset_sources_view,
    get_dataset_view,
    get_qa_stats_view,
    get_qa_view,
    list_dataset_versions,
    list_datasets_view,
    next_version,
    resolve_similarity_pair,
    save_generation,
)

# Every test in this module talks to the database.
pytestmark = pytest.mark.usefixtures("datasets_db")


def _item(item_id, question, answer="A sufficiently long answer.", **overrides):
    item = {
        "id": item_id,
        "question": question,
        "answer": answer,
        "context": "ctx",
        "source_url": "https://example.com/a",
        "confidence": 0.9,
        "metadata": {"model": "gpt-test"},
    }
    item.update(overrides)
    return item


def _seed(name="ds", items=None, source_url="https://example.com", **kwargs):
    return save_generation(
        name,
        items if items is not None else [_item("h1", "What is a dataset?")],
        source_url=source_url,
        **kwargs,
    )


# --- create / list / detail --------------------------------------------------


def test_create_dataset_then_list_and_get():
    create_dataset("alpha", "the description")

    listed = list_datasets_view()
    assert [d["name"] for d in listed] == ["alpha"]
    assert listed[0]["qa_sources_count"] == 0
    # No generation recorded yet, so no version.
    assert listed[0]["version"] is None

    detail = get_dataset_view("alpha")
    assert detail is not None
    assert detail["description"] == "the description"
    assert get_dataset_view("ghost") is None


def test_create_dataset_rejects_duplicate_name():
    create_dataset("alpha")
    with pytest.raises(ValueError, match="already exists"):
        create_dataset("alpha")


# --- generation writes -------------------------------------------------------


def test_save_generation_creates_dataset_pairs_and_run():
    result = _seed(items=[_item("h1", "Q one?"), _item("h2", "Q two?")])

    assert result["version"] == 1
    assert result["run_name"] == "v1"
    assert result["created_count"] == 2

    view = get_dataset_view("ds")
    assert view is not None
    assert view["qa_sources_count"] == 2
    assert view["version"] == 1


def test_save_generation_is_idempotent_on_the_same_content():
    """Pair ids are content hashes: a re-run updates in place, never duplicates."""
    _seed(items=[_item("h1", "Q one?")])
    _seed(items=[_item("h1", "Q one?", answer="A better answer, still long.")])

    pairs = get_dataset_pairs("ds")
    assert len(pairs) == 1
    assert pairs[0]["answer"] == "A better answer, still long."
    # Two runs recorded even though the pair count didn't move.
    assert list_dataset_versions("ds")["total"] == 2


def test_versions_increment_per_dataset():
    assert next_version("ds") == 1
    _seed()
    assert next_version("ds") == 2
    # A different dataset starts its own numbering.
    assert next_version("other") == 1


def test_save_generation_records_run_stats():
    _seed(
        stats={
            "pages_crawled": 4,
            "total": 3,
            "exact_duplicates": 2,
            "similar_duplicates": 1,
        }
    )
    run = list_dataset_versions("ds")["versions"][0]
    assert run["pages_analyzed"] == 4
    assert run["new_pairs"] == 3
    assert run["duplicates_skipped"] == 3


def test_save_generation_without_stats_leaves_counters_null():
    """A missing stat must not read as a real zero in the UI."""
    _seed()
    run = list_dataset_versions("ds")["versions"][0]
    assert run["duplicates_skipped"] is None
    assert run["pages_analyzed"] is None


def test_save_generation_does_not_relabel_an_existing_language():
    _seed(target_language="fr")
    _seed(target_language="en")
    view = get_dataset_view("ds")
    assert view is not None
    assert view["target_language"] == "fr"


# --- Q/A list & stats --------------------------------------------------------


def test_get_qa_view_paginates():
    _seed(items=[_item(f"h{i}", f"Question {i}?") for i in range(5)])

    page = get_qa_view("ds", limit=2, offset=0)
    assert page["total_count"] == 5
    assert page["returned_count"] == 2
    assert page["dataset_id"] == "ds"

    assert get_qa_view("ds", limit=2, offset=4)["returned_count"] == 1


def test_get_qa_view_unknown_dataset_raises():
    with pytest.raises(ValueError, match="not found"):
        get_qa_view("ghost")


def test_get_qa_stats_aggregates_scores():
    _seed(
        items=[
            _item("a", "q1?", confidence=0.95),
            _item("b", "q2?", confidence=0.85),
            _item("c", "q3?", confidence=0.75),
            _item("d", "q4?", confidence=0.5),
        ]
    )
    stats = get_qa_stats_view("ds", score_threshold=0.8)

    assert stats["total_count"] == 4
    assert stats["scored_count"] == 4
    assert stats["average_score"] == round((0.95 + 0.85 + 0.75 + 0.5) / 4, 4)
    assert stats["below_threshold_count"] == 2
    assert stats["validated_count"] == 2
    assert [b["count"] for b in stats["distribution"]] == [1, 1, 1, 1]


def test_unscored_pairs_are_counted_but_not_averaged():
    """An unscored pair is not a zero-scored one."""
    _seed(items=[_item("a", "q1?", confidence=0.9), _item("b", "q2?", confidence=None)])
    stats = get_qa_stats_view("ds")

    assert stats["total_count"] == 2
    assert stats["scored_count"] == 1
    assert stats["average_score"] == 0.9
    assert sum(b["count"] for b in stats["distribution"]) == 1


# --- sources & history -------------------------------------------------------


def test_sources_group_by_url_with_counts_and_dates():
    _seed(
        items=[
            _item("a", "q1?", source_url="https://docs.example.com/api"),
            _item("b", "q2?", source_url="https://docs.example.com/api"),
            _item("c", "q3?", source_url="file://manual.pdf"),
        ]
    )
    view = get_dataset_sources_view("ds")

    assert view["total_qa"] == 3
    assert view["total_sources"] == 2
    web, file_source = view["sources"]
    assert web["qa_count"] == 2
    assert web["kind"] == "web"
    assert web["label"] == "docs.example.com/api"
    assert web["first_seen_at"] is not None
    assert file_source["kind"] == "file"
    assert file_source["label"] == "manual.pdf"


def test_sources_label_every_kind():
    _seed(
        items=[
            _item("a", "q1?", source_url="github://octocat"),
            _item("b", "q2?", source_url=None),
        ]
    )
    by_kind = {s["kind"]: s for s in get_dataset_sources_view("ds")["sources"]}

    assert by_kind["github"]["label"] == "octocat"
    assert by_kind["unknown"]["url"] is None
    assert by_kind["unknown"]["label"] == "Unknown source"


def test_sources_history_lists_runs_newest_first():
    _seed(source_url="https://a.example.com")
    _seed(items=[_item("h2", "Another question?")], source_url="https://b.example.com")

    view = get_dataset_sources_view("ds")
    assert view["total_analyses"] == 2
    assert [h["version"] for h in view["history"]] == [2, 1]
    assert view["history"][0]["label"] == "b.example.com"


def test_sources_and_versions_unknown_dataset_raise():
    with pytest.raises(ValueError, match="not found"):
        get_dataset_sources_view("ghost")
    with pytest.raises(ValueError, match="not found"):
        list_dataset_versions("ghost")


# --- similarity analyse / clean ----------------------------------------------


def test_analyze_similarities_finds_near_duplicates():
    _seed(
        items=[
            _item("a", "What is Python?"),
            _item("b", "What is Python used for?"),
            _item("c", "How tall is Everest?"),
        ]
    )
    result = analyze_similarities_view("ds", threshold=0.7)

    assert result["total_records"] == 3
    assert result["similar_pairs_found"] == 1


def test_clean_similarities_keeps_the_higher_confidence_record():
    _seed(
        items=[
            _item("aaaa1111", "What is Python?", confidence=0.7),
            _item("bbbb2222", "What is Python used for?", confidence=0.95),
        ]
    )
    result = clean_similarities_view("ds", threshold=0.7)

    assert result["removed_records"] == 1
    remaining = get_dataset_pairs("ds")
    assert [p["id"] for p in remaining] == ["bbbb2222"]


def test_clean_similarities_on_empty_dataset_raises():
    create_dataset("empty")
    with pytest.raises(ValueError, match="no Q/A pairs"):
        clean_similarities_view("empty")


def test_resolve_pair_deletes_by_prefix():
    _seed(items=[_item("aaaa1111", "q1?"), _item("bbbb2222", "q2?")])

    result = resolve_similarity_pair("ds", "aaaa1111"[:8])
    assert result["removed_id"] == "aaaa1111"
    assert [p["id"] for p in get_dataset_pairs("ds")] == ["bbbb2222"]


def test_resolve_pair_ambiguous_prefix_raises():
    _seed(items=[_item("aaaa1111", "q1?"), _item("aaaa2222", "q2?")])
    with pytest.raises(AmbiguousRecordError):
        resolve_similarity_pair("ds", "aaaa")


def test_resolve_pair_unknown_record_raises():
    _seed()
    with pytest.raises(ValueError, match="not found"):
        resolve_similarity_pair("ds", "zzzz")


# --- delete / duplicate ------------------------------------------------------


def test_delete_dataset_removes_pairs_and_runs(monkeypatch):
    monkeypatch.setattr(
        "server.services.qdrant.delete_collection_for", lambda name: True
    )
    _seed(items=[_item("a", "q1?"), _item("b", "q2?")])

    result = delete_dataset("ds")
    assert result["records_deleted"] == 2
    assert "Qdrant" in result["message"]
    assert get_dataset_view("ds") is None
    # The cascade took the pairs and the run with it.
    assert get_dataset_pairs("ds") == []


def test_delete_unknown_dataset_raises():
    with pytest.raises(ValueError, match="not found"):
        delete_dataset("ghost")


def test_duplicate_dataset_copies_pairs():
    _seed(items=[_item("a", "q1?"), _item("b", "q2?")])

    result = duplicate_dataset("ds", "ds-export")
    assert result["target_dataset_name"] == "ds-export"
    assert result["created_count"] == 2

    copy = get_dataset_view("ds-export")
    assert copy is not None
    assert copy["qa_sources_count"] == 2
    # The source is untouched.
    assert len(get_dataset_pairs("ds")) == 2


def test_duplicate_empty_dataset_raises():
    create_dataset("empty")
    with pytest.raises(ValueError, match="no Q/A pairs"):
        duplicate_dataset("empty")


def test_get_dataset_pairs_of_unknown_dataset_is_empty():
    """The dedup pool asks before the first generation creates the dataset."""
    assert get_dataset_pairs("ghost") == []


def test_duplicate_dataset_twice_is_idempotent():
    """The copy's ids are derived from the target, so a re-run refreshes them.

    Reusing the source ids would collide on the (global) primary key the second
    time around.
    """
    _seed(items=[_item("a", "q1?"), _item("b", "q2?")])

    duplicate_dataset("ds", "ds-export")
    second = duplicate_dataset("ds", "ds-export")

    assert second["created_count"] == 2
    copy = get_dataset_view("ds-export")
    assert copy is not None
    assert copy["qa_sources_count"] == 2
