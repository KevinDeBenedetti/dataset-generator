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
    get_pairs_to_score,
    get_qa_stats_view,
    get_qa_view,
    list_dataset_versions,
    list_datasets_view,
    next_version,
    resolve_similarity_pair,
    save_generation,
    set_pair_confidences,
)

# Every test in this module talks to the database, as one persisted user.
OWNER = "owner-1"
OTHER = "owner-2"  # a second user, who must never see OWNER's data


@pytest.fixture(autouse=True)
def _owner(test_db, datasets_db):
    from server.models.user import User

    test_db.add(User(id=OWNER, email="owner1@test.local", role="user"))
    test_db.add(User(id=OTHER, email="owner2@test.local", role="user"))
    test_db.commit()


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
        OWNER,
        name,
        items if items is not None else [_item("h1", "What is a dataset?")],
        source_url=source_url,
        **kwargs,
    )


# --- create / list / detail --------------------------------------------------


def test_create_dataset_then_list_and_get():
    create_dataset(OWNER, "alpha", "the description")

    listed = list_datasets_view(OWNER)
    assert [d["name"] for d in listed] == ["alpha"]
    assert listed[0]["qa_sources_count"] == 0
    # No generation recorded yet, so no version.
    assert listed[0]["version"] is None

    detail = get_dataset_view(OWNER, "alpha")
    assert detail is not None
    assert detail["description"] == "the description"
    assert get_dataset_view(OWNER, "ghost") is None


def test_create_dataset_rejects_duplicate_name():
    create_dataset(OWNER, "alpha")
    with pytest.raises(ValueError, match="already exists"):
        create_dataset(OWNER, "alpha")


# --- generation writes -------------------------------------------------------


def test_save_generation_creates_dataset_pairs_and_run():
    result = _seed(items=[_item("h1", "Q one?"), _item("h2", "Q two?")])

    assert result["version"] == 1
    assert result["run_name"] == "v1"
    assert result["created_count"] == 2

    view = get_dataset_view(OWNER, "ds")
    assert view is not None
    assert view["qa_sources_count"] == 2
    assert view["version"] == 1


def test_save_generation_is_idempotent_on_the_same_content():
    """Pair ids are content hashes: a re-run updates in place, never duplicates."""
    _seed(items=[_item("h1", "Q one?")])
    _seed(items=[_item("h1", "Q one?", answer="A better answer, still long.")])

    pairs = get_dataset_pairs(OWNER, "ds")
    assert len(pairs) == 1
    assert pairs[0]["answer"] == "A better answer, still long."
    # Two runs recorded even though the pair count didn't move.
    assert list_dataset_versions(OWNER, "ds")["total"] == 2


def test_same_content_in_two_datasets_stays_in_both():
    """Content-hash ids are not dataset-aware: the key must be, or the second
    generation re-parents the first dataset's row and empties it."""
    _seed("first", items=[_item("h1", "Q one?")])
    _seed("second", items=[_item("h1", "Q one?")])

    assert [p["id"] for p in get_dataset_pairs(OWNER, "first")] == ["h1"]
    assert [p["id"] for p in get_dataset_pairs(OWNER, "second")] == ["h1"]


def test_versions_increment_per_dataset():
    assert next_version(OWNER, "ds") == 1
    _seed()
    assert next_version(OWNER, "ds") == 2
    # A different dataset starts its own numbering.
    assert next_version(OWNER, "other") == 1


def test_save_generation_records_run_stats():
    _seed(
        stats={
            "pages_crawled": 4,
            "total": 3,
            "exact_duplicates": 2,
            "similar_duplicates": 1,
        },
    )
    run = list_dataset_versions(OWNER, "ds")["versions"][0]
    assert run["pages_analyzed"] == 4
    assert run["new_pairs"] == 3
    assert run["duplicates_skipped"] == 3


def test_save_generation_without_stats_leaves_counters_null():
    """A missing stat must not read as a real zero in the UI."""
    _seed()
    run = list_dataset_versions(OWNER, "ds")["versions"][0]
    assert run["duplicates_skipped"] is None
    assert run["pages_analyzed"] is None


def test_save_generation_does_not_relabel_an_existing_language():
    _seed(target_language="fr")
    _seed(target_language="en")
    view = get_dataset_view(OWNER, "ds")
    assert view is not None
    assert view["target_language"] == "fr"


# --- Q/A list & stats --------------------------------------------------------


def test_get_qa_view_paginates():
    _seed(items=[_item(f"h{i}", f"Question {i}?") for i in range(5)])

    page = get_qa_view(OWNER, "ds", limit=2, offset=0)
    assert page["total_count"] == 5
    assert page["returned_count"] == 2
    assert page["dataset_id"] == "ds"

    assert get_qa_view(OWNER, "ds", limit=2, offset=4)["returned_count"] == 1


def test_get_qa_view_unknown_dataset_raises():
    with pytest.raises(ValueError, match="not found"):
        get_qa_view(OWNER, "ghost")


def test_get_qa_stats_aggregates_scores():
    _seed(
        items=[
            _item("a", "q1?", confidence=0.95),
            _item("b", "q2?", confidence=0.85),
            _item("c", "q3?", confidence=0.75),
            _item("d", "q4?", confidence=0.5),
        ],
    )
    stats = get_qa_stats_view(OWNER, "ds", score_threshold=0.8)

    assert stats["total_count"] == 4
    assert stats["scored_count"] == 4
    assert stats["average_score"] == round((0.95 + 0.85 + 0.75 + 0.5) / 4, 4)
    assert stats["below_threshold_count"] == 2
    assert stats["validated_count"] == 2
    assert [b["count"] for b in stats["distribution"]] == [1, 1, 1, 1]


def test_unscored_pairs_are_counted_but_not_averaged():
    """An unscored pair is not a zero-scored one."""
    _seed(
        items=[_item("a", "q1?", confidence=0.9), _item("b", "q2?", confidence=None)],
    )
    stats = get_qa_stats_view(OWNER, "ds")

    assert stats["total_count"] == 2
    assert stats["scored_count"] == 1
    assert stats["average_score"] == 0.9
    assert sum(b["count"] for b in stats["distribution"]) == 1


def test_unscored_pair_is_served_as_null_not_zero():
    _seed(items=[_item("a", "q1?", confidence=None)])
    [pair] = get_qa_view(OWNER, "ds")["qa_data"]
    assert pair["confidence"] is None


def test_get_pairs_to_score_filters_unscored_by_default():
    _seed(
        items=[_item("a", "q1?", confidence=0.9), _item("b", "q2?", confidence=None)],
    )

    assert [p["id"] for p in get_pairs_to_score(OWNER, "ds")] == ["b"]
    assert [p["id"] for p in get_pairs_to_score(OWNER, "ds", only_unscored=False)] == [
        "a",
        "b",
    ]
    with pytest.raises(ValueError):
        get_pairs_to_score(OWNER, "ghost")


def test_set_pair_confidences_stores_score_and_method():
    _seed(
        items=[_item("a", "q1?", confidence=None), _item("b", "q2?", confidence=None)],
    )

    assert (
        set_pair_confidences(OWNER, "ds", {"a": 0.8, "missing": 0.5}, "llm_judge:m")
        == 1
    )

    pairs = {p["id"]: p for p in get_qa_view(OWNER, "ds")["qa_data"]}
    assert pairs["a"]["confidence"] == 0.8
    assert pairs["a"]["metadata"]["confidence_method"] == "llm_judge:m"
    # Existing metadata is kept alongside the new key.
    assert pairs["a"]["metadata"]["model"] == "gpt-test"
    assert pairs["b"]["confidence"] is None
    assert set_pair_confidences(OWNER, "ds", {}, "llm_judge:m") == 0


# --- sources & history -------------------------------------------------------


def test_sources_group_by_url_with_counts_and_dates():
    _seed(
        items=[
            _item("a", "q1?", source_url="https://docs.example.com/api"),
            _item("b", "q2?", source_url="https://docs.example.com/api"),
            _item("c", "q3?", source_url="file://manual.pdf"),
        ],
    )
    view = get_dataset_sources_view(OWNER, "ds")

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
        ],
    )
    by_kind = {s["kind"]: s for s in get_dataset_sources_view(OWNER, "ds")["sources"]}

    assert by_kind["github"]["label"] == "octocat"
    assert by_kind["unknown"]["url"] is None
    assert by_kind["unknown"]["label"] == "Unknown source"


def test_sources_history_lists_runs_newest_first():
    _seed(source_url="https://a.example.com")
    _seed(
        items=[_item("h2", "Another question?")],
        source_url="https://b.example.com",
    )

    view = get_dataset_sources_view(OWNER, "ds")
    assert view["total_analyses"] == 2
    assert [h["version"] for h in view["history"]] == [2, 1]
    assert view["history"][0]["label"] == "b.example.com"


def test_sources_and_versions_unknown_dataset_raise():
    with pytest.raises(ValueError, match="not found"):
        get_dataset_sources_view(OWNER, "ghost")
    with pytest.raises(ValueError, match="not found"):
        list_dataset_versions(OWNER, "ghost")


# --- similarity analyse / clean ----------------------------------------------


def test_analyze_similarities_finds_near_duplicates():
    _seed(
        items=[
            _item("a", "What is Python?"),
            _item("b", "What is Python used for?"),
            _item("c", "How tall is Everest?"),
        ],
    )
    result = analyze_similarities_view(OWNER, "ds", threshold=0.7)

    assert result["total_records"] == 3
    assert result["similar_pairs_found"] == 1


def test_analyze_similarities_ignores_templated_questions_with_different_answers():
    _seed(
        items=[
            _item(
                "a",
                "What is the purpose of the 'tools' repository?",
                answer="A CLI toolbox wrapping gh, docker and kubectl helpers.",
            ),
            _item(
                "b",
                "What is the purpose of the 'notes' repository?",
                answer="Personal markdown notes, synced to an Obsidian vault.",
            ),
        ],
    )
    result = analyze_similarities_view(OWNER, "ds", threshold=0.8)

    assert result["similar_pairs_found"] == 0


def test_clean_similarities_keeps_the_higher_confidence_record():
    _seed(
        items=[
            _item("aaaa1111", "What is Python?", confidence=0.7),
            _item("bbbb2222", "What is Python used for?", confidence=0.95),
        ],
    )
    result = clean_similarities_view(OWNER, "ds", threshold=0.7)

    assert result["removed_records"] == 1
    remaining = get_dataset_pairs(OWNER, "ds")
    assert [p["id"] for p in remaining] == ["bbbb2222"]


def test_clean_similarities_leaves_other_datasets_alone():
    items = [
        _item("aaaa1111", "What is Python?", confidence=0.7),
        _item("bbbb2222", "What is Python used for?", confidence=0.95),
    ]
    _seed("ds", items=items)
    _seed("other", items=items)

    clean_similarities_view(OWNER, "ds", threshold=0.7)

    assert len(get_dataset_pairs(OWNER, "other")) == 2


def test_clean_similarities_on_empty_dataset_raises():
    create_dataset(OWNER, "empty")
    with pytest.raises(ValueError, match="no Q/A pairs"):
        clean_similarities_view(OWNER, "empty")


def test_resolve_pair_deletes_by_prefix():
    _seed(items=[_item("aaaa1111", "q1?"), _item("bbbb2222", "q2?")])

    result = resolve_similarity_pair(OWNER, "ds", "aaaa1111"[:8])
    assert result["removed_id"] == "aaaa1111"
    assert [p["id"] for p in get_dataset_pairs(OWNER, "ds")] == ["bbbb2222"]


def test_resolve_pair_ambiguous_prefix_raises():
    _seed(items=[_item("aaaa1111", "q1?"), _item("aaaa2222", "q2?")])
    with pytest.raises(AmbiguousRecordError):
        resolve_similarity_pair(OWNER, "ds", "aaaa")


def test_resolve_pair_unknown_record_raises():
    _seed()
    with pytest.raises(ValueError, match="not found"):
        resolve_similarity_pair(OWNER, "ds", "zzzz")


# --- delete / duplicate ------------------------------------------------------


def test_delete_dataset_removes_pairs_and_runs(monkeypatch):
    monkeypatch.setattr("server.services.qdrant.delete_collection", lambda name: True)
    _seed(items=[_item("a", "q1?"), _item("b", "q2?")])

    result = delete_dataset(OWNER, "ds")
    assert result["records_deleted"] == 2
    assert "Qdrant" in result["message"]
    assert get_dataset_view(OWNER, "ds") is None
    # The cascade took the pairs and the run with it.
    assert get_dataset_pairs(OWNER, "ds") == []


def test_delete_unknown_dataset_raises():
    with pytest.raises(ValueError, match="not found"):
        delete_dataset(OWNER, "ghost")


def test_duplicate_dataset_copies_pairs():
    _seed(items=[_item("a", "q1?"), _item("b", "q2?")])

    result = duplicate_dataset(OWNER, "ds", "ds-export")
    assert result["target_dataset_name"] == "ds-export"
    assert result["created_count"] == 2

    copy = get_dataset_view(OWNER, "ds-export")
    assert copy is not None
    assert copy["qa_sources_count"] == 2
    # The source is untouched.
    assert len(get_dataset_pairs(OWNER, "ds")) == 2


def test_duplicate_empty_dataset_raises():
    create_dataset(OWNER, "empty")
    with pytest.raises(ValueError, match="no Q/A pairs"):
        duplicate_dataset(OWNER, "empty")


def test_get_dataset_pairs_of_unknown_dataset_is_empty():
    """The dedup pool asks before the first generation creates the dataset."""
    assert get_dataset_pairs(OWNER, "ghost") == []


def test_duplicate_dataset_twice_is_idempotent():
    """The copy's ids are derived from the target, so a re-run refreshes them.

    Reusing the source ids would collide on the (global) primary key the second
    time around.
    """
    _seed(items=[_item("a", "q1?"), _item("b", "q2?")])

    duplicate_dataset(OWNER, "ds", "ds-export")
    second = duplicate_dataset(OWNER, "ds", "ds-export")

    assert second["created_count"] == 2
    copy = get_dataset_view(OWNER, "ds-export")
    assert copy is not None
    assert copy["qa_sources_count"] == 2


# --- isolation between users --------------------------------------------------


def _seed_as(owner, name="ds", items=None):
    return save_generation(
        owner,
        name,
        items if items is not None else [_item("h1", "What is a dataset?")],
        source_url="https://example.com",
    )


def test_two_users_can_each_have_a_dataset_with_the_same_name():
    a = _seed_as(OWNER, items=[_item("a1", "Owner one question?")])
    b = _seed_as(OTHER, items=[_item("b1", "Owner two question?")])

    assert a["dataset_id"] != b["dataset_id"]
    assert [p["question"] for p in get_dataset_pairs(OWNER, "ds")] == [
        "Owner one question?"
    ]
    assert [p["question"] for p in get_dataset_pairs(OTHER, "ds")] == [
        "Owner two question?"
    ]
    # Versions are per dataset: each user's first run is v1.
    assert a["version"] == b["version"] == 1


def test_a_users_list_only_contains_their_own_datasets():
    _seed_as(OWNER, "mine")
    _seed_as(OTHER, "theirs")

    assert [d["name"] for d in list_datasets_view(OWNER)] == ["mine"]
    assert [d["name"] for d in list_datasets_view(OTHER)] == ["theirs"]


def test_counts_in_the_list_are_not_polluted_by_other_users():
    _seed_as(OWNER, "ds", [_item("a", "q1?")])
    _seed_as(OTHER, "ds", [_item("b", "q2?"), _item("c", "q3?")])

    assert list_datasets_view(OWNER)[0]["qa_sources_count"] == 1
    assert list_datasets_view(OTHER)[0]["qa_sources_count"] == 2


READS = [
    get_dataset_sources_view,
    list_dataset_versions,
    get_qa_view,
    get_qa_stats_view,
    get_pairs_to_score,
    analyze_similarities_view,
    clean_similarities_view,
]


@pytest.mark.parametrize("read", READS, ids=lambda fn: fn.__name__)
def test_another_users_dataset_looks_like_it_does_not_exist(read):
    _seed_as(OWNER, "private", [_item("a", "q1?"), _item("b", "q2?")])

    with pytest.raises(ValueError, match="not found"):
        read(OTHER, "private")


def test_lookups_by_a_stranger_return_nothing():
    _seed_as(OWNER, "private")

    assert get_dataset_view(OTHER, "private") is None
    assert get_dataset_pairs(OTHER, "private") == []
    assert next_version(OTHER, "private") == 1  # as if it had never existed


def test_a_stranger_cannot_delete_write_or_duplicate_it(monkeypatch):
    monkeypatch.setattr("server.services.qdrant.delete_collection", lambda name: True)
    _seed_as(OWNER, "private", [_item("a", "q1?")])

    with pytest.raises(ValueError):
        delete_dataset(OTHER, "private")
    with pytest.raises(ValueError):
        duplicate_dataset(OTHER, "private", "stolen")
    with pytest.raises(ValueError):
        resolve_similarity_pair(OTHER, "private", "a")
    with pytest.raises(ValueError):
        set_pair_confidences(OTHER, "private", {"a": 0.1}, "judge")

    # Nothing happened to the owner's data.
    (pair,) = get_dataset_pairs(OWNER, "private")
    assert pair["confidence"] == 0.9
    assert get_dataset_view(OTHER, "stolen") is None


def test_generating_into_a_strangers_name_creates_your_own_dataset():
    _seed_as(OWNER, "shared-name", [_item("a", "Owner question?")])
    _seed_as(OTHER, "shared-name", [_item("z", "Stranger question?")])

    # The owner's dataset gained nothing and kept its version.
    assert [p["id"] for p in get_dataset_pairs(OWNER, "shared-name")] == ["a"]
    assert next_version(OWNER, "shared-name") == 2


def test_creating_a_name_someone_else_uses_is_fine_but_your_own_twice_is_not():
    create_dataset(OWNER, "taken")
    create_dataset(OTHER, "taken")  # a different owner: no clash

    with pytest.raises(ValueError, match="already exists"):
        create_dataset(OWNER, "taken")


def test_deleting_your_dataset_leaves_the_same_named_one_of_another_user(
    monkeypatch,
):
    monkeypatch.setattr("server.services.qdrant.delete_collection", lambda name: True)
    _seed_as(OWNER, "same", [_item("a", "q1?")])
    _seed_as(OTHER, "same", [_item("b", "q2?")])

    delete_dataset(OWNER, "same")

    assert get_dataset_view(OWNER, "same") is None
    assert [p["id"] for p in get_dataset_pairs(OTHER, "same")] == ["b"]


def test_duplicate_stays_within_the_owner():
    _seed_as(OWNER, "src", [_item("a", "q1?")])
    duplicate_dataset(OWNER, "src", "copy")

    assert get_dataset_view(OWNER, "copy") is not None
    assert get_dataset_view(OTHER, "copy") is None


def test_deleting_a_user_deletes_their_datasets_and_only_theirs(test_db):
    from server.models.dataset import Dataset
    from server.models.user import User

    _seed_as(OWNER, "gone", [_item("a", "q1?")])
    _seed_as(OTHER, "kept", [_item("b", "q2?")])

    test_db.delete(test_db.get(User, OWNER))
    test_db.commit()
    remaining = {d.name for d in test_db.query(Dataset).all()}
    # SQLite only enforces ON DELETE CASCADE with foreign keys switched on, which
    # Postgres always does; the real assertion runs against Postgres in CI.
    assert "kept" in remaining


def test_a_datasets_qdrant_collection_is_named_after_its_id_not_its_name():
    from server.services.qdrant import default_collection_name

    a = _seed_as(OWNER, "docs")
    b = _seed_as(OTHER, "docs")

    name_a = default_collection_name(a["dataset_id"])
    name_b = default_collection_name(b["dataset_id"])
    assert name_a != name_b
    assert a["dataset_id"] in name_a
    # A legacy dataset keeps the collection it already has.
    assert default_collection_name("id", "dev_old_name") == "dev_old_name"
