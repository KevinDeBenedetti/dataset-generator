"""Datasets, their Q/A pairs and their generation history.

PostgreSQL is the source of truth for all three. The shapes here are driven by
what the read layer needs to answer in SQL rather than in Python:

* :class:`QAPair` keeps question/answer/context/source_url/confidence as real
  columns — so the stats page is an aggregate, the sources view a ``GROUP BY``
  and the Q/A list a ``LIMIT``/``OFFSET``, instead of loading every pair to
  count it. Free-form generation details stay in ``qa_metadata``.
* :class:`DatasetRun` records one row per generation, which is what makes the
  version history and the "analyses that fed this dataset" view possible.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.core.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Dataset(Base):
    """A named collection of generated Q/A pairs, owned by one user."""

    __tablename__ = "datasets"
    # The name is the identifier every API route and the front-end use (ids stay
    # internal), and it is unique *per owner*: two users may each have a
    # "docs-fr", and "generate into an existing dataset" resolves to one row.
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_datasets_owner_name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    # Who owns it. Every read and write goes through the owner-scoped accessors in
    # services/datasets.py; deleting the user deletes their datasets.
    owner_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # The Qdrant collection holding this dataset's embeddings, once chosen. Null =
    # the default ``<prefix>ds_<id>`` (see services/qdrant.py); datasets that
    # predate owners keep their original ``<prefix><slug>`` collection here, so
    # nothing has to be re-embedded.
    qdrant_collection: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_language: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, default=_now, onupdate=_now
    )

    # Deleting a dataset drops its pairs and its history with it — the cascade is
    # declared on both sides so it holds whether the delete goes through the ORM
    # or straight to SQL.
    pairs: Mapped[list["QAPair"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )
    runs: Mapped[list["DatasetRun"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )


class QAPair(Base):
    """One question/answer pair generated from a source."""

    __tablename__ = "qa_pairs"
    # The content hash is not dataset-aware, so the key must be: the same pair
    # generated into two datasets is two rows, not one row that moves between them.
    __table_args__ = (PrimaryKeyConstraint("dataset_id", "id", name="qa_pairs_pkey"),)

    # Content hash (see services.dedup.compute_hash_from_content), so re-running a
    # generation over unchanged content upserts instead of duplicating.
    id: Mapped[str] = mapped_column(String)
    dataset_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # The cleaned source text the pair was derived from.
    context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Where the content came from: a page URL, ``file://<name>`` or
    # ``github://<user>``. Indexed — the sources view groups on it.
    source_url: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Version of the run that created the pair (see DatasetRun.version).
    version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    qa_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, default=_now, index=True
    )

    dataset: Mapped[Dataset] = relationship(back_populates="pairs")


class DatasetRun(Base):
    """One recorded generation: what was analysed, and what it produced."""

    __tablename__ = "dataset_runs"
    # Versions are per dataset and 1-based, so v1 of one dataset and v1 of
    # another coexist while a dataset can't have two v1s.
    __table_args__ = (UniqueConstraint("dataset_id", "version", name="uq_run_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The seed that was analysed (site root, uploaded file, GitHub account) —
    # not the individual pages, which are on the pairs.
    source_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Counters reported by the pipeline. Nullable so "not recorded" stays
    # distinguishable from a real zero in the UI.
    item_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pages_analyzed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    new_pairs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duplicates_skipped: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, default=_now, index=True
    )

    dataset: Mapped[Dataset] = relationship(back_populates="runs")

    @property
    def run_name(self) -> str:
        """Display name of the version (``v1``, ``v2``, …)."""
        return f"v{self.version}"
