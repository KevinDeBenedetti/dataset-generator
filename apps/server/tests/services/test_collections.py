"""Vector collections (services/collections.py): define, build, search, test.

Qdrant runs in qdrant-client's in-memory mode and the model is the
bag-of-words fake, so the whole flow, the worker's build included, runs
without a Qdrant server or a model download. The Hub is faked at its two read
calls; the split itself is a real Arrow table.
"""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pyarrow as pa
import pytest
from qdrant_client import QdrantClient
from sqlalchemy.orm import sessionmaker

from server.core.config import config
from server.models.job_run import JobRun
from server.models.user import User
from server.models.vector_collection import VectorCollection
from server.services import collections, hub, qdrant
from server.services import jobs as jobs_service
from server.services import queue
from server.services.jobs import RunConflictError, get_run
from server.tests.creds import FULL
from server.tests.fake_embedder import DIM, FakeEmbedder

OWNER = "owner-1"
OTHER = "owner-2"
REPO = "kevin/qa"
SHA = "a" * 40
NEWER = "b" * 40

# Answers share words with their own question; "egypt" asks about the Nile,
# whose answer is the "nile" row's: the retrieval test's one miss.
ROWS = [
    {
        "id": "fr",
        "question": "What is the capital of France?",
        "answer": "Paris is the capital of France.",
        "context": "Geography of France.",
    },
    {
        "id": "nile",
        "question": "Which river flows through Cairo?",
        "answer": "The Nile river flows through Cairo.",
        "context": "Rivers of Egypt.",
    },
    {
        "id": "hamlet",
        "question": "Who wrote Hamlet?",
        "answer": "Shakespeare wrote Hamlet.",
        "context": "English plays.",
    },
    {"id": "empty", "question": "Is this row empty?", "answer": "", "context": ""},
    {
        "id": "egypt",
        "question": "Where does the Nile flow?",
        "answer": "Through Egypt and Sudan.",
        "context": "Rivers of Egypt.",
    },
]


def _table(rows):
    table = pa.Table.from_pylist(rows)
    return table.append_column(
        hub.ROW_IDX, pa.array(range(table.num_rows), type=pa.int64())
    )


@pytest.fixture
def db(monkeypatch, test_engine):
    """One test database for the routes' session, the jobs and the worker."""
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    @contextmanager
    def scoped():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    for module in (jobs_service, queue, collections):
        monkeypatch.setattr(module, "get_scoped_db", scoped)
    monkeypatch.setattr(config, "worker_heartbeat_seconds", 0.02)
    monkeypatch.setattr(config, "quota_active_runs", 0)
    monkeypatch.setattr(config, "quota_runs_per_day", 0)
    monkeypatch.setattr(
        "server.services.credentials.resolve_credentials", lambda owner_id: FULL
    )
    session = TestingSession()
    session.add(User(id=OWNER, email="owner1@test.local", role="user"))
    session.add(User(id=OTHER, email="owner2@test.local", role="user"))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def vectors(monkeypatch):
    """An in-memory Qdrant, as the deployment's."""
    client = QdrantClient(":memory:")
    monkeypatch.setattr(config, "qdrant_url", "http://qdrant.test:6333")
    monkeypatch.setattr(qdrant, "get_client", lambda: client)
    return client


@pytest.fixture
def embedder(monkeypatch):
    fake = FakeEmbedder()
    models = []

    def load(model):
        models.append(model)
        return fake

    monkeypatch.setattr(collections, "_embedder", load)
    return SimpleNamespace(fake=fake, models=models)


@pytest.fixture
def fake_hub(monkeypatch):
    """``kevin/qa``: one train split, at SHA (latest) and NEWER."""
    state = SimpleNamespace(
        latest=SHA, size=1000, tables={SHA: _table(ROWS), NEWER: _table(ROWS[:2])}
    )
    state.loads = []

    def resolve(creds, repo_id, revision=None):
        if repo_id != REPO:
            raise hub.HubNotFoundError("Dataset not found")
        sha = revision or state.latest
        return hub.Snapshot(
            repo_id=repo_id,
            sha=sha,
            info=SimpleNamespace(card_data=None),
            files=(hub.HubFile("data/train.jsonl", state.size, False),),
        )

    def load_split(creds, snapshot, view):
        state.loads.append((snapshot.sha, view.config, view.split))
        return state.tables[snapshot.sha]

    monkeypatch.setattr(hub, "resolve", resolve)
    monkeypatch.setattr(hub, "load_split", load_split)
    return state


@pytest.fixture
def queued(db, monkeypatch):
    """Builds are queued — a run row each — and never run, unless a test
    drives the worker or builds itself."""
    calls = []

    async def queue_build(owner_id, creds, collection_id):
        calls.append(collection_id)
        run_id = f"run-{len(calls)}"
        with collections.get_scoped_db() as session:
            # A job id per run: the one-active-run index would refuse a second.
            session.add(
                JobRun(
                    id=run_id,
                    owner_id=owner_id,
                    job_id=f"test-build-{len(calls)}",
                    status="queued",
                    options={"collection_id": collection_id},
                )
            )
            session.commit()
        return run_id

    monkeypatch.setattr(collections, "_queue", queue_build)
    return calls


def _define(db, **values):
    data = {
        "name": "QA answers",
        "repo_id": REPO,
        "text_columns": ["answer"],
        "query_column": "question",
        **values,
    }
    return asyncio.run(collections.create_collection(db, OWNER, FULL, data))


async def _build_now(collection_id):
    progress = []
    built = await collections.build(
        FULL, collection_id, lambda *step: progress.append(step)
    )
    return built, progress


def _ready(db, embedder, fake_hub, queued, **values):
    created = _define(db, **values)
    asyncio.run(_build_now(created["id"]))
    return collections.get_collection(db, OWNER, created["id"])


# --- defining ---------------------------------------------------------------------


def test_a_new_collection_pins_the_latest_commit_and_queues_its_build(
    db, vectors, fake_hub, queued
):
    created = _define(db)

    assert created["status"] == "building"
    assert created["revision"] == SHA
    assert (created["config"], created["split"]) == ("default", "train")
    assert created["model"] == collections.collection_models()[0].name
    assert created["run_id"] == "run-1"
    assert queued == [created["id"]]
    # Named after the row's id, behind the deployment's prefix.
    assert created["qdrant_collection"] == (
        f"{config.qdrant_collection_prefix}c_{created['id']}"
    )


def test_what_a_collection_can_not_be_built_from_is_refused(
    db, vectors, fake_hub, queued, monkeypatch
):
    with pytest.raises(collections.CollectionInputError, match="not one of"):
        _define(db, model="some/huge-model")
    with pytest.raises(collections.CollectionInputError, match="at least one"):
        _define(db, text_columns=[""])
    with pytest.raises(hub.HubNotFoundError):
        _define(db, repo_id="someone/else")
    with pytest.raises(hub.HubNotFoundError):
        _define(db, split="validation")
    fake_hub.size = config.max_hub_view_bytes + 1
    with pytest.raises(hub.HubTooLargeError, match="collection"):
        _define(db)
    monkeypatch.setattr(config, "qdrant_url", "")
    with pytest.raises(qdrant.QdrantNotConfiguredError):
        _define(db)
    assert queued == []
    assert db.query(VectorCollection).count() == 0


def test_names_are_unique_per_user_and_the_quota_holds(
    db, vectors, fake_hub, queued, monkeypatch
):
    _define(db)
    with pytest.raises(collections.CollectionConflictError, match="already"):
        _define(db)
    other = asyncio.run(
        collections.create_collection(
            db,
            OTHER,
            FULL,
            {"name": "QA answers", "repo_id": REPO, "text_columns": ["answer"]},
        )
    )
    assert other["name"] == "QA answers"

    monkeypatch.setattr(config, "quota_collections", 1)
    with pytest.raises(collections.CollectionQuotaError):
        _define(db, name="Another")


def test_a_build_that_can_not_be_queued_takes_its_row_back(
    db, vectors, fake_hub, monkeypatch
):
    async def busy(owner_id, creds, collection_id):
        raise RunConflictError("A vector-collection run is already in progress")

    monkeypatch.setattr(collections, "_queue", busy)
    with pytest.raises(RunConflictError):
        _define(db)
    assert db.query(VectorCollection).count() == 0


# --- building ---------------------------------------------------------------------


def test_a_build_embeds_every_row_with_text(db, vectors, embedder, fake_hub, queued):
    created = _define(db)
    built, progress = asyncio.run(_build_now(created["id"]))

    # The empty answer is skipped; the others are points keyed by row position.
    assert built["points"] == 4 and built["skipped"] == 1 and built["rows"] == 5
    assert built["vector_size"] == DIM
    collection = collections.get_collection(db, OWNER, created["id"])
    assert collection["status"] == "ready"
    assert collection["points_count"] == 4 and collection["rows_total"] == 5
    # The embedded and queried columns, then the Q/A columns of the split.
    assert collection["fields"] == ["answer", "question", "context"]
    assert embedder.models == [created["model"]]
    assert progress[-1] == (4, 4, "Embedding rows")

    name = collection["qdrant_collection"]
    point = vectors.retrieve(name, ids=[2], with_payload=True)[0]
    assert point.payload == {
        "row_idx": 2,
        "text": "Shakespeare wrote Hamlet.",
        "fields": {
            "answer": "Shakespeare wrote Hamlet.",
            "question": "Who wrote Hamlet?",
            "context": "English plays.",
        },
    }
    assert vectors.retrieve(name, ids=[3]) == []


def test_the_chosen_columns_are_joined_in_their_order(
    db, vectors, embedder, fake_hub, queued
):
    created = _define(db, text_columns=["context", "answer"])
    asyncio.run(_build_now(created["id"]))

    name = collections.get_collection(db, OWNER, created["id"])["qdrant_collection"]
    point = vectors.retrieve(name, ids=[0], with_payload=True)[0]
    assert (
        point.payload["text"]
        == "Geography of France.\n\nParis is the capital of France."
    )


def test_a_column_missing_at_the_commit_fails_the_build(
    db, vectors, embedder, fake_hub, queued
):
    created = _define(db, text_columns=["answer", "rationale"])
    with pytest.raises(collections.CollectionBuildError, match="'rationale'"):
        asyncio.run(_build_now(created["id"]))


def test_a_build_of_only_empty_rows_fails(db, vectors, embedder, fake_hub, queued):
    fake_hub.tables[SHA] = _table([{"question": "Q?", "answer": ""}])
    created = _define(db)
    with pytest.raises(collections.CollectionBuildError, match="empty"):
        asyncio.run(_build_now(created["id"]))


async def test_the_worker_runs_the_build_from_the_queue(
    db, vectors, embedder, fake_hub
):
    created = await collections.create_collection(
        db,
        OWNER,
        FULL,
        {"name": "Queued", "repo_id": REPO, "text_columns": ["answer"]},
    )
    assert created["status"] == "building"
    while await queue.run_once() is not None:
        pass

    run = get_run(OWNER, created["run_id"])
    assert run["status"] == "succeeded", run["error"]
    assert ("Points", 4) in [tuple(m) for m in run["result"]["metrics"]]
    db.expire_all()
    assert collections.get_collection(db, OWNER, created["id"])["status"] == "ready"


def _row(**values):
    now = datetime.now(timezone.utc)
    return VectorCollection(
        **{
            "id": "c1",
            "owner_id": OWNER,
            "name": "c",
            "repo_id": REPO,
            "revision": SHA,
            "config_name": "default",
            "split": "train",
            "text_columns": ["answer"],
            "model": "m",
            "status": "building",
            "run_id": "r1",
            "created_at": now,
            "updated_at": now,
            **values,
        }
    )


@pytest.mark.parametrize(
    ("run_status", "error", "expected"),
    [
        ("queued", None, ("building", None)),
        ("running", None, ("building", None)),
        ("failed", "No column 'x'.", ("failed", "No column 'x'.")),
        ("cancelled", None, ("failed", "The build was cancelled.")),
        ("interrupted", None, ("failed", "The worker building it stopped.")),
    ],
)
def test_while_building_the_run_tells_the_state(run_status, error, expected):
    run = JobRun(id="r1", status=run_status, error=error, progress={"done": 1})
    status, message, progress = collections._state(_row(), run)

    assert status == expected[0]
    if expected[1] is None:
        assert message is None
    else:
        assert message is not None and message.startswith(expected[1])
    assert (progress is not None) == (status == "building")


def test_a_build_not_queued_yet_reads_as_queued_then_as_failed():
    recent = _row(run_id=None)
    assert collections._state(recent, None)[0] == "building"
    old = _row(
        run_id=None, updated_at=datetime.now(timezone.utc) - timedelta(minutes=5)
    )
    assert collections._state(old, None)[0] == "failed"
    assert collections._state(_row(status="ready"), None) == ("ready", None, None)


# --- rebuilding and deleting --------------------------------------------------------


def test_a_rebuild_moves_to_the_latest_commit_and_replaces_the_vectors(
    db, vectors, embedder, fake_hub, queued
):
    ready = _ready(db, embedder, fake_hub, queued)
    fake_hub.latest = NEWER

    rebuilt = asyncio.run(collections.rebuild_collection(db, OWNER, FULL, ready["id"]))
    assert rebuilt["status"] == "building" and rebuilt["revision"] == NEWER
    asyncio.run(_build_now(ready["id"]))

    db.expire_all()
    after = collections.get_collection(db, OWNER, ready["id"])
    assert after["status"] == "ready" and after["points_count"] == 2
    assert vectors.count(after["qdrant_collection"]).count == 2


def test_a_rebuild_is_refused_while_building_and_restored_if_it_can_not_start(
    db, vectors, embedder, fake_hub, queued, monkeypatch
):
    building = _define(db)
    with pytest.raises(collections.CollectionConflictError, match="already"):
        asyncio.run(collections.rebuild_collection(db, OWNER, FULL, building["id"]))

    ready = _ready(db, embedder, fake_hub, queued, name="Second")
    fake_hub.latest = NEWER

    async def busy(owner_id, creds, collection_id):
        raise RunConflictError("busy")

    monkeypatch.setattr(collections, "_queue", busy)
    with pytest.raises(RunConflictError):
        asyncio.run(collections.rebuild_collection(db, OWNER, FULL, ready["id"]))
    db.expire_all()
    kept = collections.get_collection(db, OWNER, ready["id"])
    assert kept["status"] == "ready" and kept["revision"] == SHA


def test_deleting_drops_the_vectors_but_not_while_building(
    db, vectors, embedder, fake_hub, queued
):
    building = _define(db)
    with pytest.raises(collections.CollectionConflictError, match="cancel"):
        collections.delete_collection(db, OWNER, building["id"])

    ready = _ready(db, embedder, fake_hub, queued, name="Second")
    assert vectors.collection_exists(ready["qdrant_collection"])
    collections.delete_collection(db, OWNER, ready["id"])

    assert not vectors.collection_exists(ready["qdrant_collection"])
    with pytest.raises(collections.CollectionNotFoundError):
        collections.get_collection(db, OWNER, ready["id"])


def test_another_users_collection_looks_unknown(db, vectors, fake_hub, queued):
    created = _define(db)
    for call in (
        lambda: collections.get_collection(db, OTHER, created["id"]),
        lambda: collections.delete_collection(db, OTHER, created["id"]),
        lambda: collections.search(db, OTHER, created["id"], "capital"),
        lambda: collections.evaluate(db, OTHER, created["id"]),
    ):
        with pytest.raises(collections.CollectionNotFoundError):
            call()
    assert collections.list_collections(db, OTHER)["collections"] == []


# --- testing ------------------------------------------------------------------------


def test_search_returns_the_closest_rows(db, vectors, embedder, fake_hub, queued):
    ready = _ready(db, embedder, fake_hub, queued)

    found = collections.search(db, OWNER, ready["id"], "  capital of France  ", limit=2)

    assert found["query"] == "capital of France"
    assert [hit["row_idx"] for hit in found["hits"]][0] == 0
    top = found["hits"][0]
    assert top["text"] == "Paris is the capital of France."
    assert top["fields"]["question"] == "What is the capital of France?"
    assert len(found["hits"]) == 2
    assert found["hits"][0]["score"] >= found["hits"][1]["score"]


def test_a_collection_that_is_not_ready_can_not_be_searched(
    db, vectors, embedder, fake_hub, queued
):
    building = _define(db)
    with pytest.raises(collections.CollectionConflictError, match="still being built"):
        collections.search(db, OWNER, building["id"], "capital")

    ready = _ready(db, embedder, fake_hub, queued, name="Second")
    vectors.delete_collection(ready["qdrant_collection"])
    with pytest.raises(collections.CollectionConflictError, match="build it again"):
        collections.search(db, OWNER, ready["id"], "capital")


def test_the_retrieval_test_scores_each_question_against_its_own_answer(
    db, vectors, embedder, fake_hub, queued
):
    ready = _ready(db, embedder, fake_hub, queued)

    result = collections.evaluate(db, OWNER, ready["id"], sample=100, k=10)

    # Four rows have a point (the empty one has none); three find their answer
    # first, "egypt" finds the "nile" row's.
    assert result["queries"] == 4 and result["k"] == 10
    assert result["hit_at_1"] == 0.75
    assert result["hit_at_k"] == 1.0
    assert 0.75 < result["mrr"] < 1.0
    assert result["trivial"] is False
    (miss,) = result["misses"]
    assert miss["row_idx"] == 4 and miss["rank"] > 1
    assert miss["query"] == "Where does the Nile flow?"
    assert miss["expected"] == "Through Egypt and Sudan."
    assert miss["top_row_idx"] == 1
    assert miss["top_text"] == "The Nile river flows through Cairo."
    # Saved as the collection's latest test.
    db.expire_all()
    assert collections.get_collection(db, OWNER, ready["id"])["evaluation"] == result


def test_a_query_column_that_is_embedded_makes_the_test_trivial(
    db, vectors, embedder, fake_hub, queued
):
    ready = _ready(db, embedder, fake_hub, queued, text_columns=["question", "answer"])

    result = collections.evaluate(db, OWNER, ready["id"])

    assert result["trivial"] is True and result["hit_at_1"] == 1.0


def test_the_test_needs_a_stored_query_column(db, vectors, embedder, fake_hub, queued):
    ready = _ready(db, embedder, fake_hub, queued, query_column=None)
    with pytest.raises(collections.CollectionInputError, match="Pick the column"):
        collections.evaluate(db, OWNER, ready["id"])
    with pytest.raises(collections.CollectionInputError, match="isn't stored"):
        collections.evaluate(db, OWNER, ready["id"], query_column="id")
    # A Q/A split stores its question column anyway.
    result = collections.evaluate(db, OWNER, ready["id"], query_column="question")
    assert result["queries"] == 4


def test_every_collection_of_a_split_is_tested_on_the_same_rows():
    a = _row(id="a", model="m1", rows_total=1000)
    b = _row(id="b", model="m2", text_columns=["question"], rows_total=1000)
    newer = _row(id="c", revision=NEWER, rows_total=1000)

    sample = collections._sample_ids(a, 50)
    assert sample == collections._sample_ids(b, 50)
    assert len(sample) == 50 and sample == sorted(set(sample))
    assert sample != collections._sample_ids(newer, 50)
    assert len(collections._sample_ids(_row(rows_total=3), 50)) == 3


def test_a_new_build_clears_the_test_of_the_previous_vectors(
    db, vectors, embedder, fake_hub, queued
):
    ready = _ready(db, embedder, fake_hub, queued)
    collections.evaluate(db, OWNER, ready["id"])
    asyncio.run(collections.rebuild_collection(db, OWNER, FULL, ready["id"]))
    asyncio.run(_build_now(ready["id"]))

    db.expire_all()
    assert collections.get_collection(db, OWNER, ready["id"])["evaluation"] is None


def test_the_listing_offers_the_models_and_says_whether_qdrant_is_set_up(
    db, monkeypatch
):
    monkeypatch.setattr(config, "qdrant_url", "")
    listed = collections.list_collections(db, OWNER)

    assert listed["qdrant_configured"] is False
    assert listed["models"][0]["name"] == config.semantic_model
    assert {m["name"] for m in listed["models"]} >= {"BAAI/bge-small-en-v1.5"}
    assert listed["quota"] == config.quota_collections
