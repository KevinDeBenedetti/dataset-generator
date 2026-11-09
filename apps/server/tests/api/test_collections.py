"""Vector collections through the API: define, build on the worker, search,
test, export, delete — and how each failure answers.

Isolation between users is walked by tests/api/test_tenant_isolation.py; the
service itself by tests/services/test_collections.py.
"""

import asyncio
import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pyarrow as pa
import pytest
from qdrant_client import QdrantClient

from server.api import collections as api_collections
from server.core.config import config
from server.services import collections, hub, qdrant, queue
from server.services.users import create_user
from server.tests.creds import FULL
from server.tests.fake_embedder import FakeEmbedder

REPO = "kevin/qa"
SHA = "c" * 40
ROWS = [
    {"question": "What is the capital of France?", "answer": "Paris is the capital."},
    {"question": "Who wrote Hamlet?", "answer": "Shakespeare wrote Hamlet."},
    {"question": "Which river flows through Cairo?", "answer": "The Nile does."},
]
NEW = {
    "name": "Answers",
    "repo_id": REPO,
    "text_columns": ["answer"],
    "query_column": "question",
}


@pytest.fixture
def alice(test_db):
    return create_user(test_db, email="alice@test.local", password="pw12345")


@pytest.fixture
def client(alice, client_for):
    return client_for(alice)


@pytest.fixture
def stack(monkeypatch, datasets_db):
    """Qdrant in memory, the fake model, a one-split dataset, and the jobs,
    the worker and the build on the test database."""
    vectors = QdrantClient(":memory:")
    monkeypatch.setattr(config, "qdrant_url", "http://qdrant.test:6333")
    monkeypatch.setattr(qdrant, "get_client", lambda: vectors)
    monkeypatch.setattr(collections, "_embedder", lambda model, creds: FakeEmbedder())
    for target in (
        "server.services.jobs.get_scoped_db",
        "server.services.queue.get_scoped_db",
        "server.services.collections.get_scoped_db",
    ):
        monkeypatch.setattr(target, datasets_db)
    monkeypatch.setattr(config, "quota_runs_per_day", 0)
    monkeypatch.setattr(
        "server.services.credentials.resolve_credentials", lambda owner_id: FULL
    )

    table = pa.Table.from_pylist(ROWS)
    table = table.append_column(hub.ROW_IDX, pa.array(range(3), type=pa.int64()))

    def resolve(creds, repo_id, revision=None):
        if repo_id != REPO:
            raise hub.HubNotFoundError("Dataset not found")
        return hub.Snapshot(
            repo_id=repo_id,
            sha=revision or SHA,
            info=SimpleNamespace(card_data=None),
            files=(hub.HubFile("train.jsonl", 100, False),),
        )

    monkeypatch.setattr(hub, "resolve", resolve)
    monkeypatch.setattr(hub, "load_split", lambda creds, snapshot, view: table)
    return vectors


def _work(test_db):
    """Let the worker run every queued build, then forget what the request's
    session had cached (a request gets a fresh session; the test's is shared)."""

    async def drain():
        while await queue.run_once() is not None:
            pass

    asyncio.run(drain())
    test_db.expire_all()


def test_a_collection_goes_from_a_split_to_search_and_test(client, stack, test_db):
    created = client.post("/collections", json=NEW)
    assert created.status_code == 202, created.text
    collection = created.json()
    assert collection["status"] == "building"
    assert collection["revision"] == SHA and collection["run_id"]

    _work(test_db)
    ready = client.get(f"/collections/{collection['id']}").json()
    assert ready["status"] == "ready", ready
    assert ready["points_count"] == 3 and ready["vector_size"] > 0

    found = client.post(
        f"/collections/{collection['id']}/search",
        json={"query": "capital of France", "limit": 1},
    )
    assert found.status_code == 200, found.text
    (hit,) = found.json()["hits"]
    assert hit["row_idx"] == 0 and hit["fields"]["question"].startswith("What is")

    tested = client.post(f"/collections/{collection['id']}/evaluate", json={"k": 3})
    assert tested.status_code == 200, tested.text
    assert tested.json()["queries"] == 3
    listed = client.get("/collections").json()
    assert listed["qdrant_configured"] is True
    assert [c["id"] for c in listed["collections"]] == [collection["id"]]
    assert listed["collections"][0]["evaluation"]["k"] == 3


def test_the_export_holds_the_collections(client, stack, test_db):
    client.post("/collections", json=NEW)
    _work(test_db)

    archive = zipfile.ZipFile(io.BytesIO(client.get("/me/export").content))
    (exported,) = json.loads(archive.read("collections.json"))
    assert exported["name"] == "Answers" and exported["repo_id"] == REPO
    assert exported["text_columns"] == ["answer"]


def test_deleting_a_collection_drops_its_vectors(client, stack, test_db):
    collection = client.post("/collections", json=NEW).json()
    _work(test_db)
    name = collection["qdrant_collection"]
    assert stack.collection_exists(name)

    assert client.delete(f"/collections/{collection['id']}").status_code == 204
    assert not stack.collection_exists(name)
    assert client.get(f"/collections/{collection['id']}").status_code == 404


def test_one_build_at_a_time_and_none_while_building(client, stack, test_db):
    first = client.post("/collections", json=NEW).json()

    second = client.post("/collections", json={**NEW, "name": "Questions"})
    assert second.status_code == 409
    assert "already being built" in second.json()["detail"]
    # The refused one is not left behind.
    assert len(client.get("/collections").json()["collections"]) == 1

    for method, path, body in (
        ("POST", f"/collections/{first['id']}/search", {"query": "capital"}),
        ("POST", f"/collections/{first['id']}/evaluate", {}),
        ("POST", f"/collections/{first['id']}/build", {}),
        ("DELETE", f"/collections/{first['id']}", None),
    ):
        response = client.request(method, path, json=body)
        assert response.status_code == 409, (method, path, response.text)


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"model": "someone/two-gigabyte-model"}, 400),
        ({"repo_id": "someone/private"}, 404),
        ({"repo_id": "not a repo id"}, 404),
        ({"split": "test"}, 404),
        ({"text_columns": []}, 422),
        ({"text_columns": ["a", "b", "c", "d", "e"]}, 422),
        ({"name": "  "}, 422),
    ],
)
def test_what_can_not_be_built_is_refused(client, stack, change, status):
    response = client.post("/collections", json={**NEW, **change})
    assert response.status_code == status, response.text
    assert client.get("/collections").json()["collections"] == []


def test_the_listing_asks_the_endpoint_for_its_models_only_when_told(
    client, stack, monkeypatch
):
    """Discovery is a network call: the Collections page asks for it, tests
    and other callers don't pay it."""
    provider = SimpleNamespace(list_models=AsyncMock(return_value=[]))
    monkeypatch.setattr(api_collections, "get_provider", lambda name: provider)

    assert client.get("/collections").status_code == 200
    provider.list_models.assert_not_awaited()
    assert client.get("/collections?discover=true").status_code == 200
    provider.list_models.assert_awaited_once()


def test_without_qdrant_collections_are_off(client, stack, monkeypatch):
    monkeypatch.setattr(config, "qdrant_url", "")

    assert client.get("/collections").json()["qdrant_configured"] is False
    response = client.post("/collections", json=NEW)
    assert response.status_code == 503
    assert "QDRANT_URL" in response.json()["detail"]


def test_an_unreachable_qdrant_answers_502(client, stack, test_db, monkeypatch):
    collection = client.post("/collections", json=NEW).json()
    _work(test_db)

    class Down:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise ConnectionError("connection refused by 10.0.0.7:6333")

            return fail

    monkeypatch.setattr(qdrant, "get_client", lambda: Down())
    response = client.post(
        f"/collections/{collection['id']}/search", json={"query": "capital"}
    )
    assert response.status_code == 502
    # The client's own message (an internal address) stays in the log.
    assert "10.0.0.7" not in response.text


def test_the_build_job_stays_off_the_jobs_page(client, stack):
    assert collections.COLLECTION_JOB_ID not in [
        job["id"] for job in client.get("/jobs").json()["jobs"]
    ]
    response = client.post(
        f"/jobs/{collections.COLLECTION_JOB_ID}/run",
        json={"options": {"collection_id": "x"}},
    )
    assert response.status_code == 404
