"""Where recipe runs keep their files: fetched data and draft Parquet (ADR 0004).

A tabular draft's rows are never in Postgres: they are ``data.parquet`` in the
run's folder, next to the files the connector fetched (``raw/``). Uploaded
files of a data source live in its own folder until the data source goes::

    <owner_id>/<run_id>/data.parquet
    <owner_id>/<run_id>/raw/<file>
    <owner_id>/sources/<data_source_id>/<file>

The store is a local directory (``DRAFT_STORE_URL=file:///…``): the engine
(DuckDB) reads and writes its files in place. Every key is checked segment by
segment, so no caller can reach outside an owner's folder. A user holds at
most ``QUOTA_DRAFT_BYTES_PER_USER`` (checked before a fetch and after the
engine writes).
"""

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Iterable, List, Optional
from urllib.parse import unquote, urlsplit

from server.core.config import config

logger = logging.getLogger(__name__)

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
SOURCES_DIR = "sources"
RAW_DIR = "raw"
DATA_FILE = "data.parquet"
_CHUNK = 1024 * 1024


class DraftStoreError(ValueError):
    """A key that is not acceptable, or a store that is misconfigured."""


class DraftQuotaExceeded(Exception):
    """The user would hold more than ``QUOTA_DRAFT_BYTES_PER_USER``."""


class TooLarge(Exception):
    """A streamed write went past the byte limit it was given."""


def _segments(*parts: str) -> List[str]:
    out: List[str] = []
    for part in parts:
        for segment in str(part).split("/"):
            if not _SEGMENT.match(segment) or segment in (".", ".."):
                raise DraftStoreError(f"Not a valid storage name: '{segment}'")
            out.append(segment)
    return out


@dataclass
class DraftStore:
    """The draft store on a local directory."""

    root: Path

    @classmethod
    def from_url(cls, url: str) -> "DraftStore":
        parts = urlsplit(url)
        if parts.scheme != "file" or parts.netloc not in ("", "localhost"):
            raise DraftStoreError(
                f"DRAFT_STORE_URL must be a file:/// directory (got '{url}')"
            )
        return cls(Path(unquote(parts.path)))

    # --- paths -------------------------------------------------------------

    def path(self, owner_id: str, *parts: str) -> Path:
        """The local path of a key under ``owner_id``'s folder (not created)."""
        return self.root.joinpath(*_segments(owner_id, *parts))

    def run_dir(self, owner_id: str, run_id: str) -> Path:
        return self.path(owner_id, run_id)

    def raw_dir(self, owner_id: str, run_id: str) -> Path:
        directory = self.path(owner_id, run_id, RAW_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def data_path(self, owner_id: str, run_id: str) -> Path:
        directory = self.run_dir(owner_id, run_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / DATA_FILE

    def source_dir(self, owner_id: str, data_source_id: str) -> Path:
        directory = self.path(owner_id, SOURCES_DIR, data_source_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    # --- bytes -------------------------------------------------------------

    def write(self, owner_id: str, key: str, data: bytes) -> Path:
        target = self.path(owner_id, key)
        self.ensure_quota(owner_id, len(data))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def write_stream(
        self, owner_id: str, key: str, stream: BinaryIO, max_bytes: int
    ) -> Path:
        """Copy ``stream`` to ``key``, refusing (and removing the partial file)
        past ``max_bytes`` or past the owner's quota."""
        target = self.path(owner_id, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        room = self.room(owner_id)
        written = 0
        try:
            with target.open("wb") as out:
                while chunk := stream.read(_CHUNK):
                    written += len(chunk)
                    if written > max_bytes:
                        raise TooLarge()
                    if written > room:
                        raise DraftQuotaExceeded()
                    out.write(chunk)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target

    def read(self, owner_id: str, key: str) -> bytes:
        return self.path(owner_id, key).read_bytes()

    def exists(self, owner_id: str, key: str) -> bool:
        return self.path(owner_id, key).exists()

    def delete(self, owner_id: str, *parts: str) -> None:
        """Delete a file or a folder (and everything in it). Missing is fine."""
        target = self.path(owner_id, *parts)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)

    def delete_owner(self, owner_id: str) -> None:
        shutil.rmtree(self.path(owner_id), ignore_errors=True)

    # --- sizes and quota -----------------------------------------------------

    @staticmethod
    def _size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        if not path.is_dir():
            return 0
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    def size(self, owner_id: str, *parts: str) -> int:
        return self._size(self.path(owner_id, *parts))

    def room(self, owner_id: str) -> int:
        """Bytes ``owner_id`` may still write."""
        return max(0, config.quota_draft_bytes - self.size(owner_id))

    def ensure_quota(self, owner_id: str, incoming: int = 0) -> None:
        if self.size(owner_id) + incoming > config.quota_draft_bytes:
            raise DraftQuotaExceeded()

    # --- what the sweep walks ----------------------------------------------

    def owners(self) -> Iterable[str]:
        if not self.root.is_dir():
            return []
        return [p.name for p in self.root.iterdir() if p.is_dir()]

    def runs(self, owner_id: str) -> Iterable[str]:
        folder = self.path(owner_id)
        if not folder.is_dir():
            return []
        return [
            p.name for p in folder.iterdir() if p.is_dir() and p.name != SOURCES_DIR
        ]


_store: Optional[DraftStore] = None


def get_store() -> DraftStore:
    """The process's draft store, from ``DRAFT_STORE_URL``."""
    global _store
    if _store is None or str(_store.root) != str(
        DraftStore.from_url(config.draft_store_url).root
    ):
        _store = DraftStore.from_url(config.draft_store_url)
    return _store


# Runs whose files are done with: the sweep deletes them.
_FINISHED = ("published", "rejected", "failed", "cancelled")


def sweep(now: Optional[datetime] = None) -> int:
    """Delete the run folders that are no longer needed: the run is gone, done
    with (published, rejected, failed, cancelled) or older than
    ``DRAFT_RETENTION_DAYS``. Returns the number of folders deleted."""
    from server.core.database import get_scoped_db
    from server.models.job_run import JobRun

    store = get_store()
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=config.draft_retention_days)
    deleted = 0
    with get_scoped_db() as db:
        for owner_id in store.owners():
            for run_id in store.runs(owner_id):
                run = db.get(JobRun, run_id)
                stale = run is None or run.owner_id != owner_id
                if not stale:
                    created = run.started_at
                    if created is not None and created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    stale = (run.status in _FINISHED) or (
                        created is not None and created < cutoff
                    )
                if stale:
                    store.delete(owner_id, run_id)
                    deleted += 1
    if deleted:
        logger.info("draft store sweep: %d run folder(s) deleted", deleted)
    return deleted
