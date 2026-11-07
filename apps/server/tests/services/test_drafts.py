"""File and URL drafts (services/drafts.py) and their publishing.

The database is the per-test one; the Hub is a fake HfApi recording commits.
"""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from server.services import drafts
from server.services import huggingface as hf
from server.services import jobs as jobs_service
from server.services.jobs import get_run, publish_run
from server.services.users import create_user
from server.tests.creds import make_creds

CREDS = make_creds(hf_token="hf_test_token")


class FakeHub:
    """Repo files in memory; records the commits made."""

    def __init__(self, files=None, private=True):
        self.files = dict(files or {})
        self.private = private
        self.commits = []

    def whoami(self, *a, **k):
        return {"name": "kevin"}

    def create_repo(self, repo_id, **kwargs):
        return repo_id

    def repo_info(self, repo_id, **kwargs):
        return SimpleNamespace(private=self.private)

    def create_commit(self, *, repo_id, repo_type, operations, commit_message):
        self.commits.append((repo_id, commit_message))
        for op in operations:
            self.files[op.path_in_repo] = op.path_or_fileobj


@pytest.fixture
def hub(monkeypatch):
    fake = FakeHub()
    monkeypatch.setattr(hf, "_api", lambda creds: fake)
    monkeypatch.setattr(
        hf,
        "_repo_tree",
        lambda creds, repo_id: {n: len(b) for n, b in fake.files.items()},
    )
    monkeypatch.setattr(
        hf,
        "_download_file",
        lambda creds, repo_id, filename, max_bytes: fake.files[filename],
    )
    return fake


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


def _rows(raw: bytes):
    return [json.loads(line) for line in raw.decode().splitlines() if line]


def test_a_generation_becomes_a_reviewable_draft(db, hub, owner):
    hub.files["data/train.jsonl"] = (
        b'{"id": "old", "question": "Q0?", "answer": "A0"}\n'
    )

    run_id = drafts.create_generation_draft(
        owner.id,
        CREDS,
        "docs-qa",
        [_item("a", "Q1?"), _item("b", "Q2?")],
        title="Docs",
        source="https://example.com/page",
        kind="web",
        language="en",
        model_ref="openai:gpt-x",
    )

    run = get_run(owner.id, run_id)
    assert run["status"] == "succeeded" and run["has_draft"] is True
    assert run["preview"]["repo_id"] == "kevin/docs-qa"
    assert run["preview"]["kept"] == 1
    assert [p["id"] for p in run["preview"]["new"]] == ["a", "b"]
    assert run["preview"]["new"][0]["category"] == "web"
    listed = drafts.list_drafts(owner.id)
    assert [(d["id"], d["title"], d["new"]) for d in listed] == [(run_id, "Docs", 2)]


async def test_publishing_merges_the_reviewed_pairs(db, hub, owner):
    hub.files["data/train.jsonl"] = (
        b'{"id": "old", "question": "Q0?", "answer": "A0"}\n'
        b'{"id": "a", "question": "Q1?", "answer": "Stale"}\n'
    )
    run_id = drafts.create_generation_draft(
        owner.id,
        CREDS,
        "kevin/docs-qa",
        [_item("a", "Q1?"), _item("b", "Q2?"), _item("c", "Q3?")],
        title="Docs",
        source="https://example.com/page",
        kind="web",
        language="en",
        model_ref=None,
    )

    published = await publish_run(
        owner.id,
        CREDS,
        run_id,
        exclude=["c"],
        edits={"b": {"question": "Q2, rewritten?", "answer": "Better."}},
    )

    assert published["status"] == "published"
    rows = {r["id"]: r for r in _rows(hub.files["data/train.jsonl"])}
    # Kept, replaced by the fresh pair, edited; the excluded one never lands.
    assert set(rows) == {"old", "a", "b"}
    assert rows["a"]["answer"] == "Answer to Q1?"
    assert rows["b"]["question"] == "Q2, rewritten?"
    assert "3 question/answer pairs" in hub.files["README.md"].decode()
    assert hub.commits == [
        ("kevin/docs-qa", "Add 2 Q/A pair(s) from https://example.com/page")
    ]
    assert drafts.list_drafts(owner.id) == []


def test_a_draft_with_every_pair_left_out_is_refused(hub):
    with pytest.raises(ValueError, match="Nothing to publish"):
        hf.publish_generation_draft(
            CREDS,
            {"repo_id": "kevin/x", "pairs": [_item("a", "Q?")]},
            exclude=["a"],
            edits={},
        )


def test_publishing_into_a_public_repo_is_refused(hub):
    hub.private = False
    with pytest.raises(hf.HuggingFaceRepoPublicError):
        hf.publish_generation_draft(
            CREDS, {"repo_id": "kevin/x", "pairs": [_item("a", "Q?")]}, [], {}
        )
