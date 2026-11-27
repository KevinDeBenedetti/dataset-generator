"""The draft store (services/draft_store.py): one folder per owner and run."""

import io
from datetime import datetime, timedelta, timezone

import pytest

from server.core.config import config
from server.models.job_run import JobRun
from server.services import draft_store
from server.services.draft_store import (
    DraftQuotaExceeded,
    DraftStore,
    DraftStoreError,
    TooLarge,
)


@pytest.fixture
def store(tmp_path):
    return DraftStore(tmp_path / "store")


def test_write_read_size_delete(store):
    store.write("alice", "run1/raw/data.csv", b"a,b\n1,2\n")
    assert store.read("alice", "run1/raw/data.csv") == b"a,b\n1,2\n"
    assert store.size("alice") == 8 and store.size("alice", "run1") == 8
    store.delete("alice", "run1")
    assert not store.exists("alice", "run1/raw/data.csv")
    assert store.size("alice") == 0


@pytest.mark.parametrize(
    "key", ["../bob/x", "run/../../etc", "/etc/passwd", "a//b", ".hidden"]
)
def test_no_key_reaches_outside_the_owners_folder(store, key):
    with pytest.raises(DraftStoreError):
        store.write("alice", key, b"x")


def test_the_quota_is_checked_before_writing(store, monkeypatch):
    monkeypatch.setattr(config, "quota_draft_bytes", 10)
    store.write("alice", "run1/a", b"12345678")
    with pytest.raises(DraftQuotaExceeded):
        store.write("alice", "run1/b", b"123")
    assert not store.exists("alice", "run1/b")
    store.write("bob", "run1/a", b"12345678")  # another owner has their own


def test_a_stream_past_its_limit_leaves_nothing(store):
    with pytest.raises(TooLarge):
        store.write_stream("alice", "sources/s1/big.csv", io.BytesIO(b"x" * 100), 50)
    assert not store.exists("alice", "sources/s1/big.csv")
    store.write_stream("alice", "sources/s1/ok.csv", io.BytesIO(b"x" * 40), 50)
    assert store.size("alice", "sources", "s1") == 40


def test_a_stream_past_the_quota_leaves_nothing(store, monkeypatch):
    monkeypatch.setattr(config, "quota_draft_bytes", 30)
    with pytest.raises(DraftQuotaExceeded):
        store.write_stream("alice", "run1/raw/x", io.BytesIO(b"x" * 40), 1000)
    assert store.size("alice") == 0


def test_only_file_urls_are_accepted():
    assert DraftStore.from_url("file:///data/drafts").root.as_posix() == "/data/drafts"
    with pytest.raises(DraftStoreError):
        DraftStore.from_url("s3://bucket/prefix")


def test_the_sweep_deletes_what_is_done_with(test_db, datasets_db, owner):
    store = draft_store.get_store()
    now = datetime.now(timezone.utc)
    runs = {
        "fresh": ("succeeded", now),
        "published": ("published", now),
        "old": ("succeeded", now - timedelta(days=config.draft_retention_days + 1)),
    }
    for run_id, (status, created) in runs.items():
        test_db.add(
            JobRun(
                id=run_id,
                job_id="recipe",
                owner_id=owner.id,
                status=status,
                options={},
                started_at=created,
            )
        )
        store.write(owner.id, f"{run_id}/data.parquet", b"PAR1")
    test_db.commit()
    store.write(owner.id, "gone/data.parquet", b"PAR1")  # no such run any more
    store.write(owner.id, "sources/s1/file.csv", b"a")  # a data source's upload

    assert draft_store.sweep(now) == 3
    assert store.exists(owner.id, "fresh/data.parquet")
    assert store.exists(owner.id, "sources/s1/file.csv")
    for gone in ("published", "old", "gone"):
        assert not store.exists(owner.id, f"{gone}/data.parquet")
