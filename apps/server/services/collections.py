"""Vector collections: a split of a Hub dataset, embedded into Qdrant and tested.

A collection is built from one split of a Hugging Face dataset at one commit,
read the viewer's way (services/hub.py) with the owner's own token: each row
becomes a point whose vector embeds the chosen text columns, with the row's
text fields in its payload. Then the app tests it:

* **search** — any query, embedded with the collection's model, against its
  points;
* **retrieval test** — a sample of the rows ask with their own question (the
  query column), and a row whose own point comes back first is a hit. The hit
  rates at 1 and at k and the mean reciprocal rank tell how well the embedded
  text answers the questions; the misses show which rows the model confuses.
  The sample depends on the split and its commit only, so collections built
  from the same split with other models or columns are tested on the same rows.

The definition and state of a collection are a ``vector_collections`` row; the
vectors are in Qdrant only, named after the row's id (services/qdrant.py). A
build is a job run (``vector-collection``, jobs/registry.py) that a worker
executes. While the row says "building", the run is the truth: a build that
fails, is cancelled or loses its worker shows as failed, with the run's error.
"""

import asyncio
import json
import logging
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server.core.config import config
from server.core.cpu import cpu_bound
from server.core.database import get_scoped_db
from server.models.job_run import JobRun
from server.models.vector_collection import VectorCollection
from server.services import hub, qdrant
from server.services.credentials import Credentials
from server.services.semantic import (
    RetrievalEmbedder,
    collection_models,
    get_collection_embedder,
)

logger = logging.getLogger(__name__)

COLLECTION_JOB_ID = "vector-collection"

MAX_TEXT_COLUMNS = 4
# A payload value is cut like a cell of the viewer.
MAX_PAYLOAD_CHARS = hub.MAX_CELL_CHARS
# Rows embedded, then stored, per step: the progress and cancellation grain.
BUILD_BATCH = 128
# The retrieval test keeps this many misses, their texts cut this short.
MAX_MISSES = 20
MISS_TEXT_CHARS = 400
# A run not attached yet (the request is still queuing it) reads as queued
# for this long, then as failed.
_ATTACH_GRACE = timedelta(seconds=60)

_ACTIVE_RUNS = ("queued", "running")
_STOPPED = {
    "cancelled": "The build was cancelled.",
    "interrupted": "The worker building it stopped. Build it again.",
    "succeeded": "The build finished but its result wasn't saved. Build it again.",
}

# (done, total, label), as the job registry reports progress.
ProgressFn = Callable[[int, int, str], None]


class CollectionNotFoundError(LookupError):
    """Unknown — or another user's, which looks the same."""


class CollectionConflictError(ValueError):
    """The name is taken, or the collection's state doesn't allow the action."""


class CollectionQuotaError(ValueError):
    pass


class CollectionInputError(ValueError):
    """A request the collection can't serve (an unknown model, a column)."""


class CollectionBuildError(RuntimeError):
    """A build stopped for a reason the owner can act on (saved on its run)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    # The database hands naive timestamps back (UTC by construction).
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _embedder(model: str, creds: Credentials) -> RetrievalEmbedder:
    """The collection's model (an endpoint one runs on ``creds``); tests swap
    it for a fake."""
    return get_collection_embedder(model, creds)


# --- reading -------------------------------------------------------------------


def _owned(db: Session, owner_id: str, collection_id: str) -> VectorCollection:
    row = db.get(VectorCollection, collection_id)
    if row is None or row.owner_id != owner_id:
        raise CollectionNotFoundError("Collection not found")
    return row


def _runs(db: Session, run_ids: Iterable[Optional[str]]) -> Dict[str, JobRun]:
    ids = [i for i in run_ids if i]
    if not ids:
        return {}
    return {r.id: r for r in db.scalars(select(JobRun).where(JobRun.id.in_(ids)))}


def _state(
    row: VectorCollection, run: Optional[JobRun]
) -> Tuple[str, Optional[str], Optional[Dict[str, Any]]]:
    """``(status, error, progress)`` of a collection, its build run included."""
    if row.status != "building":
        return row.status, None, None
    if run is None:
        if row.run_id is None and _now() - _aware(row.updated_at) < _ATTACH_GRACE:
            return "building", None, {"done": 0, "total": 0, "label": "Queued…"}
        return "failed", "The build never started. Build it again.", None
    if run.status in _ACTIVE_RUNS:
        return "building", None, run.progress
    error = run.error or _STOPPED.get(run.status, "The build failed.")
    return "failed", error, None


def _view(row: VectorCollection, run: Optional[JobRun]) -> Dict[str, Any]:
    status, error, progress = _state(row, run)
    return {
        "id": row.id,
        "name": row.name,
        "repo_id": row.repo_id,
        "revision": row.revision,
        "config": row.config_name,
        "split": row.split,
        "text_columns": list(row.text_columns or []),
        "query_column": row.query_column,
        "model": row.model,
        "status": status,
        "error": error,
        "progress": progress,
        "run_id": row.run_id,
        "vector_size": row.vector_size,
        "rows_total": row.rows_total,
        "points_count": row.points_count,
        "fields": list(row.fields or []),
        "qdrant_collection": qdrant.collection_name(row.id),
        "evaluation": row.evaluation,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "built_at": row.built_at,
    }


def list_collections(
    db: Session, owner_id: str, creds: Optional[Credentials] = None
) -> Dict[str, Any]:
    """The owner's collections, most recently changed first, with what the
    create form offers (the models — the endpoint's ones on ``creds`` — and
    whether Qdrant is set up)."""
    rows = list(
        db.scalars(
            select(VectorCollection)
            .where(VectorCollection.owner_id == owner_id)
            .order_by(VectorCollection.updated_at.desc())
        )
    )
    runs = _runs(db, (r.run_id for r in rows))
    return {
        "qdrant_configured": qdrant.is_configured(),
        "quota": config.quota_collections,
        "models": [asdict(m) for m in collection_models(creds)],
        "collections": [_view(r, runs.get(r.run_id or "")) for r in rows],
    }


def get_collection(db: Session, owner_id: str, collection_id: str) -> Dict[str, Any]:
    row = _owned(db, owner_id, collection_id)
    return _view(row, _runs(db, [row.run_id]).get(row.run_id or ""))


def _require_ready(db: Session, row: VectorCollection) -> None:
    status, error, _ = _state(row, _runs(db, [row.run_id]).get(row.run_id or ""))
    if status == "building":
        raise CollectionConflictError("This collection is still being built.")
    if status != "ready":
        raise CollectionConflictError(error or "This collection has no vectors yet.")


# --- creating and building -------------------------------------------------------


def _resolve_split(
    creds: Credentials,
    repo_id: str,
    revision: Optional[str],
    config_name: Optional[str],
    split: Optional[str],
) -> Tuple[hub.Snapshot, hub.View]:
    """The split at ``revision`` (pinned to its sha), as the owner's token sees
    it — refused up front when it is too large to be read."""
    owner, _, name = repo_id.partition("/")
    repo_id = hub.repo_id_of(owner, name)
    snapshot = hub.resolve(creds, repo_id, revision)
    view = hub.find_view(snapshot, config_name, split)
    known = [snapshot.size_of(path) for path in view.files]
    if sum(size or 0 for size in known) > config.max_hub_view_bytes:
        limit = config.max_hub_view_bytes // (1024 * 1024)
        raise hub.HubTooLargeError(
            f"The '{view.split}' split is larger than the {limit} MB a collection "
            "can be built from."
        )
    return snapshot, view


def _check_model(model: Optional[str], creds: Credentials) -> str:
    models = [m.name for m in collection_models(creds)]
    chosen = model or models[0]
    if chosen not in models:
        raise CollectionInputError(f"'{chosen}' is not one of the collection models")
    return chosen


def _check_columns(text_columns: Sequence[str]) -> List[str]:
    columns = list(dict.fromkeys(c for c in text_columns if c))
    if not columns:
        raise CollectionInputError("Pick at least one column to embed")
    if len(columns) > MAX_TEXT_COLUMNS:
        raise CollectionInputError(f"Embed {MAX_TEXT_COLUMNS} columns at most")
    return columns


def _insert(
    db: Session, owner_id: str, creds: Credentials, data: Dict[str, Any]
) -> str:
    if not qdrant.is_configured():
        raise qdrant.QdrantNotConfiguredError(qdrant.NOT_CONFIGURED)
    name = data["name"].strip()
    model = _check_model(data.get("model"), creds)
    columns = _check_columns(data.get("text_columns") or [])
    count = db.scalar(
        select(func.count())
        .select_from(VectorCollection)
        .where(VectorCollection.owner_id == owner_id)
    )
    if config.quota_collections and (count or 0) >= config.quota_collections:
        raise CollectionQuotaError(
            f"You already have {count} collections (limit "
            f"{config.quota_collections}). Delete one first."
        )
    taken = db.scalar(
        select(VectorCollection.id).where(
            VectorCollection.owner_id == owner_id, VectorCollection.name == name
        )
    )
    if taken:
        raise CollectionConflictError(f"You already have a collection named '{name}'")
    snapshot, view = _resolve_split(
        creds,
        data["repo_id"],
        data.get("revision"),
        data.get("config"),
        data.get("split"),
    )
    row = VectorCollection(
        owner_id=owner_id,
        name=name,
        repo_id=snapshot.repo_id,
        revision=snapshot.sha,
        config_name=view.config,
        split=view.split,
        text_columns=columns,
        query_column=data.get("query_column") or None,
        model=model,
        status="building",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # the same name, created meanwhile
        raise CollectionConflictError(
            f"You already have a collection named '{name}'"
        ) from None
    return row.id


def _reset_for_build(
    db: Session,
    owner_id: str,
    creds: Credentials,
    collection_id: str,
    revision: Optional[str],
) -> Dict[str, Any]:
    """Point the row at a new build; returns what to restore if it can't start."""
    row = _owned(db, owner_id, collection_id)
    status, _, _ = _state(row, _runs(db, [row.run_id]).get(row.run_id or ""))
    if status == "building":
        raise CollectionConflictError("This collection is already being built.")
    snapshot, _ = _resolve_split(
        creds, row.repo_id, revision, row.config_name, row.split
    )
    previous = {"status": row.status, "revision": row.revision, "run_id": row.run_id}
    row.status, row.revision, row.run_id = "building", snapshot.sha, None
    db.commit()
    return previous


def _attach(
    db: Session, owner_id: str, collection_id: str, run_id: str
) -> Dict[str, Any]:
    row = _owned(db, owner_id, collection_id)
    row.run_id = run_id
    db.commit()
    return get_collection(db, owner_id, collection_id)


def _discard(db: Session, collection_id: str) -> None:
    row = db.get(VectorCollection, collection_id)
    if row is not None:
        db.delete(row)
        db.commit()


def _restore(db: Session, collection_id: str, previous: Dict[str, Any]) -> None:
    row = db.get(VectorCollection, collection_id)
    if row is not None:
        for key, value in previous.items():
            setattr(row, key, value)
        db.commit()


async def _queue(owner_id: str, creds: Credentials, collection_id: str) -> str:
    # Imported here: services.jobs loads the job registry, whose build runner
    # lives in this module.
    from server.services.jobs import start_run

    run = await start_run(
        owner_id, creds, COLLECTION_JOB_ID, {"collection_id": collection_id}
    )
    return run["id"]


async def create_collection(
    db: Session, owner_id: str, creds: Credentials, data: Dict[str, Any]
) -> Dict[str, Any]:
    """Define a collection and queue its first build (a worker runs it).

    ``data``: ``name``, ``repo_id``, ``revision`` (default: the latest commit,
    pinned now), ``config``, ``split``, ``text_columns``, ``query_column``,
    ``model``. Raises the Hub's errors for a dataset the owner can't read,
    QdrantNotConfiguredError, and the jobs' RunConflictError (one build at a
    time) or QuotaExceededError — the row is then removed.
    """
    collection_id = await run_in_threadpool(_insert, db, owner_id, creds, data)
    try:
        run_id = await _queue(owner_id, creds, collection_id)
    except BaseException:
        # No await here: a cancelled request must still take the row back.
        _discard(db, collection_id)
        raise
    return await run_in_threadpool(_attach, db, owner_id, collection_id, run_id)


async def rebuild_collection(
    db: Session,
    owner_id: str,
    creds: Credentials,
    collection_id: str,
    revision: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the collection again from the split at ``revision`` (default: the
    dataset's latest commit) — its vectors are replaced."""
    previous = await run_in_threadpool(
        _reset_for_build, db, owner_id, creds, collection_id, revision
    )
    try:
        run_id = await _queue(owner_id, creds, collection_id)
    except BaseException:
        _restore(db, collection_id, previous)  # no await, as above
        raise
    return await run_in_threadpool(_attach, db, owner_id, collection_id, run_id)


def delete_collection(db: Session, owner_id: str, collection_id: str) -> None:
    """Delete the collection and drop its vectors; the dataset stays."""
    row = _owned(db, owner_id, collection_id)
    status, _, _ = _state(row, _runs(db, [row.run_id]).get(row.run_id or ""))
    if status == "building":
        raise CollectionConflictError(
            "This collection is being built: cancel the build first."
        )
    name = qdrant.collection_name(row.id)
    db.delete(row)
    db.commit()
    qdrant.drop(name)


def qdrant_names(db: Session, owner_id: str) -> List[str]:
    """The Qdrant collections of every collection ``owner_id`` has — what an
    account deletion drops once the rows are gone."""
    ids = db.scalars(
        select(VectorCollection.id).where(VectorCollection.owner_id == owner_id)
    )
    return [qdrant.collection_name(i) for i in ids]


# --- the build (on a worker) --------------------------------------------------------


@dataclass(frozen=True)
class _BuildSpec:
    id: str
    repo_id: str
    revision: str
    config_name: str
    split: str
    text_columns: Tuple[str, ...]
    query_column: Optional[str]
    model: str


def _load_spec(collection_id: str) -> _BuildSpec:
    with get_scoped_db() as db:
        row = db.get(VectorCollection, collection_id)
        if row is None:
            raise CollectionBuildError("The collection was deleted")
        return _BuildSpec(
            id=row.id,
            repo_id=row.repo_id,
            revision=row.revision,
            config_name=row.config_name,
            split=row.split,
            text_columns=tuple(row.text_columns or ()),
            query_column=row.query_column,
            model=row.model,
        )


def _save_build(collection_id: str, built: Dict[str, Any]) -> None:
    with get_scoped_db() as db:
        row = db.get(VectorCollection, collection_id)
        if row is None:
            return
        row.status = "ready"
        row.vector_size = built["vector_size"]
        row.rows_total = built["rows"]
        row.points_count = built["points"]
        row.fields = built["fields"]
        row.built_at = _now()
        # The test of the previous vectors says nothing about these.
        row.evaluation = None
        db.commit()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(hub.jsonable(value), ensure_ascii=False)


def _texts(
    values: Dict[str, List[Any]], columns: Sequence[str], rows: int
) -> List[str]:
    """Per row, its ``columns`` joined by blank lines (empty ones left out)."""
    out: List[str] = []
    for i in range(rows):
        parts = [_cell(values[c][i]) for c in columns]
        out.append("\n\n".join(p for p in parts if p))
    return out


def _payload(
    i: int, text: str, values: Dict[str, List[Any]], fields: Sequence[str]
) -> Dict[str, Any]:
    return {
        "row_idx": i,
        "text": text[:MAX_PAYLOAD_CHARS],
        "fields": {c: _cell(values[c][i])[:MAX_PAYLOAD_CHARS] for c in fields},
    }


async def _build(
    creds: Credentials, spec: _BuildSpec, progress: ProgressFn
) -> Dict[str, Any]:
    progress(0, 0, "Reading the split from Hugging Face…")
    snapshot = await asyncio.to_thread(hub.resolve, creds, spec.repo_id, spec.revision)
    view = hub.find_view(snapshot, spec.config_name, spec.split)
    table = await asyncio.to_thread(hub.load_split, creds, snapshot, view)

    present = [f.name for f in table.schema if f.name != hub.ROW_IDX]
    wanted = [*spec.text_columns, *([spec.query_column] if spec.query_column else [])]
    missing = [c for c in wanted if c not in present]
    if missing:
        raise CollectionBuildError(
            f"The '{view.split}' split has no column "
            + ", ".join(f"'{c}'" for c in missing)
            + " at this commit."
        )
    qa = hub.qa_columns(table) or {}
    fields = list(dict.fromkeys([*wanted, *(c for c in qa.values() if c)]))
    values = {c: table.column(c).to_pylist() for c in fields}
    texts = _texts(values, spec.text_columns, table.num_rows)
    ids = [i for i, text in enumerate(texts) if text]
    if not ids:
        raise CollectionBuildError(
            "Every row is empty in the columns to embed: pick other columns."
        )

    progress(0, len(ids), "Loading the embedding model…")
    embedder = await asyncio.to_thread(_embedder, spec.model, creds)
    # A local model computes (the CPU pool); an endpoint one waits on the
    # network, which must not hold a CPU slot.
    run = asyncio.to_thread if getattr(embedder, "remote", False) else cpu_bound
    name = qdrant.collection_name(spec.id)
    vector_size = 0
    for start in range(0, len(ids), BUILD_BATCH):
        batch = ids[start : start + BUILD_BATCH]
        vectors = await run(embedder.embed_passages, [texts[i] for i in batch])
        if not vector_size:
            vector_size = int(vectors.shape[1])
            # Replaces the vectors of an earlier build.
            await asyncio.to_thread(qdrant.recreate, name, vector_size)
        payloads = [_payload(i, texts[i], values, fields) for i in batch]
        await asyncio.to_thread(qdrant.upsert, name, batch, vectors, payloads)
        progress(start + len(batch), len(ids), "Embedding rows")

    points = await asyncio.to_thread(qdrant.count, name)
    logger.info(
        "Collection %s: %d points from %s@%s %s/%s (%s)",
        spec.id,
        points,
        spec.repo_id,
        snapshot.sha[:7],
        view.config,
        view.split,
        spec.model,
    )
    return {
        "points": points,
        "rows": table.num_rows,
        "skipped": table.num_rows - len(ids),
        "vector_size": vector_size,
        "fields": fields,
        "sha": snapshot.sha,
        "model": spec.model,
    }


async def build(
    creds: Credentials, collection_id: str, progress: ProgressFn
) -> Dict[str, Any]:
    """Embed the collection's split into Qdrant — the ``vector-collection`` job.

    A failure or a cancellation is the run's to record: the row keeps saying
    "building" and :func:`_state` reads the run.
    """
    spec = await asyncio.to_thread(_load_spec, collection_id)
    built = await _build(creds, spec, progress)
    await asyncio.to_thread(_save_build, collection_id, built)
    return built


# --- testing ---------------------------------------------------------------------------


def _hit(point_id: int, score: float, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "row_idx": point_id,
        "score": score,
        "text": payload.get("text") or "",
        "fields": payload.get("fields") or {},
    }


def _vectors_name(row: VectorCollection) -> str:
    name = qdrant.collection_name(row.id)
    if not qdrant.exists(name):
        raise CollectionConflictError(
            "This collection's vectors are no longer in Qdrant: build it again."
        )
    return name


def search(
    db: Session,
    owner_id: str,
    collection_id: str,
    query: str,
    limit: int = 10,
    score_threshold: Optional[float] = None,
    creds: Optional[Credentials] = None,
) -> Dict[str, Any]:
    """The points closest to ``query``, embedded with the collection's model
    (an endpoint one on ``creds``)."""
    row = _owned(db, owner_id, collection_id)
    _require_ready(db, row)
    query = query.strip()
    if not query:
        raise CollectionInputError("Type something to search for")
    started = time.perf_counter()
    name = _vectors_name(row)
    vector = _embedder(row.model, creds or Credentials()).embed_queries([query])[0]
    hits = qdrant.search(name, vector, limit, score_threshold)
    return {
        "query": query,
        "took_ms": round((time.perf_counter() - started) * 1000),
        "hits": [_hit(*hit) for hit in hits],
    }


def _sample_ids(row: VectorCollection, size: int) -> List[int]:
    """Row positions to test, the same for every collection of this split at
    this commit, whatever its model or columns."""
    population = row.rows_total or 0
    # Not security: a reproducible sample, seeded by the split itself.
    rng = random.Random(  # noqa: S311
        f"{row.repo_id}@{row.revision}/{row.config_name}/{row.split}"
    )
    return sorted(rng.sample(range(population), min(size, population)))


def _brief(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MISS_TEXT_CHARS else text[: MISS_TEXT_CHARS - 1] + "…"


def evaluate(
    db: Session,
    owner_id: str,
    collection_id: str,
    sample: int = 100,
    k: int = 10,
    query_column: Optional[str] = None,
    creds: Optional[Credentials] = None,
) -> Dict[str, Any]:
    """The retrieval test: sampled rows ask with their ``query_column`` value;
    a hit is the row's own point coming back. Saved as the collection's latest
    test, and returned. An endpoint model embeds the questions on ``creds``."""
    row = _owned(db, owner_id, collection_id)
    _require_ready(db, row)
    column = query_column or row.query_column
    fields = list(row.fields or [])
    if not column:
        raise CollectionInputError("Pick the column the questions are in")
    if column not in fields:
        raise CollectionInputError(
            f"'{column}' isn't stored in this collection: pick one of "
            + ", ".join(f"'{f}'" for f in fields)
        )

    name = _vectors_name(row)
    payloads = qdrant.retrieve(name, _sample_ids(row, sample))
    cases = [
        (point_id, _cell((payload.get("fields") or {}).get(column)))
        for point_id, payload in sorted(payloads.items())
    ]
    cases = [(point_id, q) for point_id, q in cases if q]
    if not cases:
        raise CollectionInputError(f"No sampled row has a value in '{column}'")

    vectors = _embedder(row.model, creds or Credentials()).embed_queries(
        [q for _, q in cases]
    )
    results = qdrant.search_batch(name, vectors, k)
    ranks: List[Optional[int]] = []
    misses: List[Tuple[int, str, Optional[int], List[Tuple[int, float]]]] = []
    for (point_id, q), hits in zip(cases, results, strict=True):
        ranked = [hit_id for hit_id, _ in hits]
        rank = ranked.index(point_id) + 1 if point_id in ranked else None
        ranks.append(rank)
        if rank != 1 and len(misses) < MAX_MISSES:
            misses.append((point_id, q, rank, hits))

    # The texts of the misses' expected and top rows, in one read.
    shown = {pid for pid, *_ in misses} | {h[0][0] for *_, h in misses if h}
    texts = {
        pid: (payload.get("text") or "")
        for pid, payload in qdrant.retrieve(name, sorted(shown)).items()
    }
    n = len(ranks)
    result = {
        "query_column": column,
        "sample": sample,
        "queries": n,
        "k": k,
        "hit_at_1": sum(1 for r in ranks if r == 1) / n,
        "hit_at_k": sum(1 for r in ranks if r is not None) / n,
        "mrr": sum(1 / r for r in ranks if r) / n,
        # The question is part of its own point's text: every row finds itself.
        "trivial": column in (row.text_columns or []),
        "model": row.model,
        "revision": row.revision,
        "evaluated_at": _now().isoformat(),
        "misses": [
            {
                "row_idx": pid,
                "query": _brief(q),
                "rank": rank,
                "expected": _brief(texts.get(pid, "")),
                "top_row_idx": hits[0][0] if hits else None,
                "top_score": hits[0][1] if hits else None,
                "top_text": _brief(texts.get(hits[0][0], "")) if hits else "",
            }
            for pid, q, rank, hits in misses
        ],
    }
    row.evaluation = result
    db.commit()
    return result
