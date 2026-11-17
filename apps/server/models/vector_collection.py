import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class VectorCollection(Base):
    """One split of a Hugging Face dataset, embedded into a Qdrant collection.

    The row is the collection's definition and state; the vectors live in
    Qdrant only, under a name derived from ``id`` (services/collections.py),
    never from anything a user typed. The dataset stays on the Hub: a build
    reads the split at ``revision``, a commit sha pinned when the build is
    queued, with the owner's own token.

    ``status``: building → ready. A build that fails, is cancelled or loses its
    worker leaves "building" behind, and its run (``run_id``) says why.
    A collection built once (``built_at``) keeps its vectors through a rebuild
    and after a failed one: they are replaced only when the new build is
    complete.
    """

    __tablename__ = "vector_collections"
    # Names are how the user tells collections apart: unique per owner.
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_vector_collections_owner_name"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex
    )
    owner_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Where the rows come from: "namespace/name" at a commit sha, one split.
    repo_id: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[str] = mapped_column(String, nullable=False)
    config_name: Mapped[str] = mapped_column(String, nullable=False)
    split: Mapped[str] = mapped_column(String, nullable=False)
    # The columns joined into the text that is embedded, in this order.
    text_columns: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    # The column the retrieval test asks with (the question, for a Q/A split).
    query_column: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The model the points and the queries are embedded with: openai:<id>, an
    # endpoint model (an older collection may name a local one, no longer run).
    model: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="building")
    # The commit a rebuild in flight is embedding (null otherwise): ``revision``
    # stays the one the vectors in Qdrant were built from until it completes,
    # so the collection keeps answering on its previous version meanwhile.
    building_revision: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The job run of the latest build (job_runs.id): while the row says
    # "building", the run's status and error are the collection's.
    run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # --- set by a finished build ---
    vector_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rows_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    points_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # The columns kept in every point's payload, besides the embedded text.
    fields: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    built_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # The host of the OpenAI-compatible endpoint that embedded the points (null
    # for a build from before it was recorded): the model's id alone does not
    # say which endpoint's model it was.
    endpoint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The latest retrieval test (services/collections.py evaluate), or null.
    evaluation: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, onupdate=_now
    )
