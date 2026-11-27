"""Data sources, recipes, reviews and publications (ADR 0001, 0004).

One generic path for every dataset built from data: a **data source** (a
connector kind and its settings) feeds a **recipe** (steps, output kind, target
Hub dataset repo); a recipe run is a ``job_runs`` row (``job_id="recipe"``)
whose draft is reviewed (``reviews``) and, once approved, published
(``publications``). Tabular draft rows live as Parquet in the draft store
(services/draft_store.py), never here. Every row is owned.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex


class OutputKind:
    TABLE = "table"
    QA = "qa"
    CORPUS = "corpus"
    ALL = (TABLE, QA, CORPUS)


class Visibility:
    PRIVATE = "private"
    PUBLIC = "public"
    ALL = (PRIVATE, PUBLIC)


class ReviewDecision:
    APPROVED = "approved"
    REJECTED = "rejected"
    ALL = (APPROVED, REJECTED)


def _owner() -> Mapped[str]:
    return mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )


class DataSource(Base):
    """A configured origin of rows: a connector kind plus its settings."""

    __tablename__ = "data_sources"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_data_sources_owner_name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    owner_id: Mapped[str] = _owner()
    name: Mapped[str] = mapped_column(String, nullable=False)
    # The connector registry's key (apps/server/connectors).
    connector: Mapped[str] = mapped_column(String, nullable=False)
    # Validated by the connector's schema; never a secret value.
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Which ``user_secrets`` kind the connector uses, if any.
    secret_kind: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The licence the data comes with, as the source or the user states it.
    licence: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_fingerprint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, onupdate=_now
    )


class Recipe(Base):
    """What to do with a data source: steps, output kind, target, visibility."""

    __tablename__ = "recipes"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_recipes_owner_name"),
        CheckConstraint(
            "output_kind IN ('table', 'qa', 'corpus')", name="ck_recipes_output_kind"
        ),
        CheckConstraint(
            "visibility IN ('private', 'public')", name="ck_recipes_visibility"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    owner_id: Mapped[str] = _owner()
    data_source_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("data_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    steps: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    output_kind: Mapped[str] = mapped_column(
        String, nullable=False, default=OutputKind.TABLE
    )
    output_options: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    # "namespace/name", or a bare name completed with the user's namespace.
    target_repo: Mapped[str] = mapped_column(String, nullable=False)
    visibility: Mapped[str] = mapped_column(
        String, nullable=False, default=Visibility.PRIVATE
    )
    # "<provider>:<model>" for the Q&A output; null = the jobs default.
    model_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, onupdate=_now
    )


class Review(Base):
    """A reviewer's decision on a recipe run's draft."""

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('approved', 'rejected')", name="ck_reviews_decision"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    owner_id: Mapped[str] = _owner()
    run_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("job_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Q&A only: row id → "keep" | "drop" (and edits).
    row_decisions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class Publication(Base):
    """One publication of a recipe run's draft to the Hub."""

    __tablename__ = "publications"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('private', 'public')", name="ck_publications_visibility"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    owner_id: Mapped[str] = _owner()
    run_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("job_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recipe_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    repo_id: Mapped[str] = mapped_column(String, nullable=False)
    commit_sha: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pr_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String, nullable=False, default=Visibility.PRIVATE
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now
    )
