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
    """Repo files in memory; records the commits made — each one a new head —
    and the downloads."""

    def __init__(self, files=None, private=True):
        self.files = dict(files or {})
        self.private = private
        self.commits = []
        self.downloads = []

    @property
    def head(self):
        return f"commit-{len(self.commits)}"

    def dataset_info(self, repo_id, **kwargs):
        return SimpleNamespace(sha=self.head)

    def get_paths_info(self, repo_id, paths, repo_type=None, revision=None):
        from huggingface_hub.hf_api import RepoFile

        return [
            RepoFile(path=p, size=len(self.files[p]), oid="0" * 40)
            for p in paths
            if p in self.files
        ]

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

    def download(creds, repo_id, filename, max_bytes, revision=None):
        fake.downloads.append((repo_id, filename, revision))
        return fake.files[filename]

    monkeypatch.setattr(hf, "_download_file", download)
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


async def test_a_draft_and_its_publication_read_the_dataset_once(db, hub, owner):
    hub.files["data/train.jsonl"] = (
        b'{"id": "old", "question": "Q0?", "answer": "A0"}\n'
    )
    run_id = drafts.create_generation_draft(
        owner.id,
        CREDS,
        "kevin/docs-qa",
        [_item("a", "Q1?")],
        title="Docs",
        source="https://example.com/page",
        kind="web",
        language="en",
        model_ref=None,
    )

    await publish_run(owner.id, CREDS, run_id, exclude=[], edits={})

    # The count and the merge read the same commit: one download for both.
    assert hub.downloads == [("kevin/docs-qa", "data/train.jsonl", "commit-0")]
    assert {r["id"] for r in _rows(hub.files["data/train.jsonl"])} == {"old", "a"}


def test_a_new_commit_is_read_again(hub):
    hub.files["data/train.jsonl"] = (
        b'{"id": "old", "question": "Q0?", "answer": "A0"}\n'
    )
    assert [r["id"] for r in hf.existing_pairs(CREDS, "kevin/x")] == ["old"]

    hf.publish_generation_draft(
        CREDS, {"repo_id": "kevin/x", "pairs": [_item("a", "Q1?")]}, [], {}
    )

    assert {r["id"] for r in hf.existing_pairs(CREDS, "kevin/x")} == {"old", "a"}
    assert [revision for *_, revision in hub.downloads] == ["commit-0", "commit-1"]


def test_another_token_reads_the_dataset_for_itself(hub):
    hub.files["data/train.jsonl"] = (
        b'{"id": "old", "question": "Q0?", "answer": "A0"}\n'
    )
    hf.existing_pairs(CREDS, "kevin/x")
    hf.existing_pairs(CREDS, "kevin/x")
    hf.existing_pairs(make_creds(hf_token="hf_other_token"), "kevin/x")
    assert len(hub.downloads) == 2


def test_a_repo_without_pairs_downloads_nothing(hub, monkeypatch):
    from unittest.mock import MagicMock

    from huggingface_hub.errors import RepositoryNotFoundError

    assert hf.existing_pairs(CREDS, "kevin/empty") == []

    def unknown(repo_id, **kwargs):
        raise RepositoryNotFoundError("no repo", response=MagicMock())

    monkeypatch.setattr(hub, "dataset_info", unknown)
    assert hf.existing_pairs(CREDS, "kevin/nope") == []
    assert hub.downloads == []


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
