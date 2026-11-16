"""File and web page drafts (services/drafts.py) and their publishing.

The database is the per-test one; the Hub is the in-memory one
(tests/fake_hub.py), so a test can read what a publication left in the repo
and make the dataset move while a publication is under way.
"""

import json
from contextlib import contextmanager

import pytest
from sqlalchemy.orm import sessionmaker

from server.jobs.qa_dataset import JobError
from server.services import drafts
from server.services import jobs as jobs_service
from server.services.hub_repo import (
    APP_CARD_TAG,
    DatasetMoved,
    HubTokenMissing,
    HubTokenRejected,
    RepoNotPrivate,
    to_jsonl,
)
from server.services.jobs import get_run, publish_run
from server.services.users import create_user
from server.tests.creds import NONE, make_creds

CREDS = make_creds(hf_token="hf_test_token")
REPO = "kevin/docs-qa"
DATA = "data/train.jsonl"
OLD = {"id": "old", "question": "Q0?", "answer": "A0"}


@pytest.fixture
def owner(test_db):
    return create_user(test_db, email="owner@test.local", password="pw12345")


@pytest.fixture
def db(monkeypatch, test_engine):
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    @contextmanager
    def scoped():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(drafts, "get_scoped_db", scoped)
    monkeypatch.setattr(jobs_service, "get_scoped_db", scoped)
    return scoped


def _item(id_, question):
    return {
        "id": id_,
        "question": question,
        "answer": f"Answer to {question}",
        "context": "ctx",
        "source_url": "https://example.com/page",
        "confidence": 0.9,
    }


def _draft(*items, repo_id=REPO):
    return {"repo_id": repo_id, "title": "Docs", "pairs": list(items)}


def _rows(hub, path=DATA, repo_id=REPO):
    raw = hub.files(repo_id)[path].decode("utf-8")
    return [json.loads(line) for line in raw.splitlines() if line]


def _make_draft(owner, target=REPO, items=None, creds=CREDS):
    return drafts.create_generation_draft(
        owner.id,
        creds,
        target,
        items or [_item("a", "Q1?"), _item("b", "Q2?")],
        title="Docs",
        source="https://example.com/page",
        kind="web",
        language="en",
        model_ref="openai:gpt-x",
    )


# --- making a draft ----------------------------------------------------------


def test_a_generation_becomes_a_reviewable_draft(db, memory_hub, owner):
    memory_hub.push(REPO, {DATA: to_jsonl([OLD])})

    run_id = _make_draft(owner, target="docs-qa")

    run = get_run(owner.id, run_id)
    assert run["status"] == "succeeded" and run["has_draft"] is True
    assert run["preview"]["repo_id"] == "kevin/docs-qa"
    assert run["preview"]["kept"] == 1
    assert [p["id"] for p in run["preview"]["new"]] == ["a", "b"]
    assert run["preview"]["new"][0]["category"] == "web"
    listed = drafts.list_drafts(owner.id)
    assert [(d["id"], d["title"], d["new"]) for d in listed] == [(run_id, "Docs", 2)]


def test_a_draft_counts_a_job_datasets_rows_too(db, memory_hub, owner):
    memory_hub.push(REPO, {"train.jsonl": to_jsonl([OLD, {**OLD, "id": "older"}])})
    run_id = _make_draft(owner)
    assert get_run(owner.id, run_id)["preview"]["kept"] == 2


def test_a_draft_needs_a_token(db, memory_hub, owner):
    with pytest.raises(HubTokenMissing):
        _make_draft(owner, creds=NONE)


def test_a_dataset_that_cannot_be_read_does_not_cost_the_draft(db, memory_hub, owner):
    memory_hub.push(REPO, {DATA: b"not json lines\n"})
    run_id = _make_draft(owner)
    assert get_run(owner.id, run_id)["preview"]["kept"] == 0


def test_a_refused_token_does_not_cost_the_draft(db, memory_hub, owner):
    memory_hub.rejects_token = True
    run_id = _make_draft(owner)  # the pairs are paid for: publishing will say why
    preview = get_run(owner.id, run_id)["preview"]
    assert preview["repo_id"] == REPO and preview["kept"] == 0


def test_a_refused_token_cannot_complete_a_bare_repo_name(db, memory_hub, owner):
    memory_hub.rejects_token = True
    with pytest.raises(HubTokenRejected):
        _make_draft(owner, target="docs-qa")


# --- publishing --------------------------------------------------------------


async def test_publishing_merges_the_reviewed_pairs(db, memory_hub, owner):
    memory_hub.push(
        REPO, {DATA: to_jsonl([OLD, {"id": "a", "question": "Q1?", "answer": "Stale"}])}
    )
    run_id = _make_draft(
        owner, items=[_item("a", "Q1?"), _item("b", "Q2?"), _item("c", "Q3?")]
    )

    published = await publish_run(
        owner.id,
        CREDS,
        run_id,
        exclude=["c"],
        edits={"b": {"question": " Q2, rewritten? ", "answer": "Better."}},
    )

    assert published["status"] == "published"
    rows = _rows(memory_hub)
    # Kept, replaced in place by the fresh pair, edited; the excluded one never lands.
    assert [r["id"] for r in rows] == ["old", "a", "b"]
    assert rows[1]["answer"] == "Answer to Q1?"
    assert rows[2]["question"] == "Q2, rewritten?" and rows[2]["answer"] == "Better."
    # The review page's filter is not a column of the dataset.
    assert "category" not in rows[1]
    card = memory_hub.files(REPO)["README.md"].decode()
    assert "3 question/answer pairs" in card and "data_files: data/train.jsonl" in card
    assert f"- {APP_CARD_TAG}" in card
    assert memory_hub.log(REPO)[-1] == "Add 2 Q/A pair(s) from https://example.com/page"
    assert drafts.list_drafts(owner.id) == []


def test_a_first_publication_creates_the_dataset_private(memory_hub):
    result = drafts.publish_generation_draft(CREDS, _draft(_item("a", "Q1?")), [], {})
    assert memory_hub.is_private(REPO) is True
    assert [r["id"] for r in _rows(memory_hub)] == ["a"]
    assert result == {
        "repo_id": REPO,
        "url": "https://huggingface.co/datasets/kevin/docs-qa",
        "pairs": 1,
        "new": 1,
    }


def test_the_rows_already_there_stay_exactly_as_stored(memory_hub):
    foreign = {"prompt": "no id", "completion": "kept", "extra": {"n": 1}}
    rich = {**OLD, "category": "projects", "repo": "demo", "grounding": 0.8}
    memory_hub.push(REPO, {DATA: to_jsonl([foreign, rich])})

    drafts.publish_generation_draft(CREDS, _draft(_item("a", "Q1?")), [], {})

    rows = _rows(memory_hub)
    assert rows[:2] == [foreign, rich]
    assert rows[2]["id"] == "a"


def test_add_data_on_a_job_dataset_lands_in_its_own_file(memory_hub):
    """A recipe's dataset keeps its rows at the root, with a review list, a
    manifest and the job's card: a draft adds to those rows and touches
    nothing else."""
    job_card = b'---\npretty_name: "GitHub Q&A"\n---\n\n# GitHub Q&A\n'
    kept = {
        "review.jsonl": to_jsonl([{"id": "r", "question": "Q?", "answer": "A"}]),
        "manifest.json": b'{"sources": {"demo/overview": "h"}}',
        "README.md": job_card,
    }
    memory_hub.push(
        REPO, {"train.jsonl": to_jsonl([{**OLD, "category": "projects"}]), **kept}
    )

    drafts.publish_generation_draft(CREDS, _draft(_item("a", "Q1?")), [], {})

    files = memory_hub.files(REPO)
    assert [r["id"] for r in _rows(memory_hub, "train.jsonl")] == ["old", "a"]
    assert DATA not in files
    assert {path: files[path] for path in kept} == kept


def test_a_card_written_elsewhere_survives_a_publication(memory_hub):
    theirs = b"---\nlicense: mit\n---\n\n# My own words\n"
    memory_hub.push(REPO, {DATA: to_jsonl([OLD]), "README.md": theirs})
    drafts.publish_generation_draft(CREDS, _draft(_item("a", "Q1?")), [], {})
    assert memory_hub.files(REPO)["README.md"] == theirs
    assert [r["id"] for r in _rows(memory_hub)] == ["old", "a"]


def test_the_apps_own_card_follows_the_dataset(memory_hub):
    drafts.publish_generation_draft(CREDS, _draft(_item("a", "Q1?")), [], {})
    drafts.publish_generation_draft(CREDS, _draft(_item("b", "Q2?")), [], {})
    assert "2 question/answer pairs" in memory_hub.files(REPO)["README.md"].decode()


def test_a_draft_with_every_pair_left_out_is_refused(memory_hub):
    with pytest.raises(ValueError, match="Nothing to publish"):
        drafts.publish_generation_draft(CREDS, _draft(_item("a", "Q?")), ["a"], {})
    assert not memory_hub.exists(REPO)


def test_publishing_into_a_public_repo_is_refused(memory_hub):
    memory_hub.push(REPO, {DATA: to_jsonl([OLD])}, private=False)
    with pytest.raises(RepoNotPrivate, match="is public"):
        drafts.publish_generation_draft(CREDS, _draft(_item("a", "Q?")), [], {})
    assert [r["id"] for r in _rows(memory_hub)] == ["old"]


# --- a dataset that moves during the publication -----------------------------


def _someone_adds(hub, *ids):
    """Another publication landing in the repo: these rows on top of its own."""

    def push():
        rows = _rows(hub) + [
            {"id": i, "question": f"{i}?", "answer": "theirs"} for i in ids
        ]
        hub.push(REPO, {DATA: to_jsonl(rows)})

    return push


def test_a_dataset_that_moved_is_read_and_merged_again(memory_hub):
    memory_hub.push(REPO, {DATA: to_jsonl([OLD])})
    memory_hub.before_commit.append(_someone_adds(memory_hub, "theirs"))

    result = drafts.publish_generation_draft(CREDS, _draft(_item("a", "Q1?")), [], {})

    # Nothing of the other publication is lost, and the card counts it.
    assert [r["id"] for r in _rows(memory_hub)] == ["old", "theirs", "a"]
    assert result["pairs"] == 3
    assert "3 question/answer pairs" in memory_hub.files(REPO)["README.md"].decode()


def test_a_dataset_that_keeps_moving_stops_the_publication(memory_hub):
    memory_hub.push(REPO, {DATA: to_jsonl([OLD])})
    memory_hub.before_commit += [
        _someone_adds(memory_hub, "first"),
        _someone_adds(memory_hub, "second"),
    ]
    with pytest.raises(DatasetMoved):
        drafts.publish_generation_draft(CREDS, _draft(_item("a", "Q1?")), [], {})
    assert [r["id"] for r in _rows(memory_hub)] == ["old", "first", "second"]


async def test_a_failed_publication_leaves_the_draft_publishable(db, memory_hub, owner):
    memory_hub.push(REPO, {DATA: to_jsonl([OLD])}, private=False)
    run_id = _make_draft(owner)

    with pytest.raises(JobError, match="is public"):
        await publish_run(owner.id, CREDS, run_id, exclude=[], edits={})
    assert get_run(owner.id, run_id)["status"] == "succeeded"

    memory_hub.set_private(REPO, True)
    published = await publish_run(owner.id, CREDS, run_id, exclude=[], edits={})
    assert published["status"] == "published"
    assert [r["id"] for r in _rows(memory_hub)] == ["old", "a", "b"]
