"""Tests for the Qdrant collections service.

Datasets/pairs are read from Postgres; here those reads are stubbed and a fake
in-memory Qdrant client records upserts, so the whole path runs offline.
"""

import uuid
from typing import List, Optional
from unittest.mock import patch

import pytest

from server.core.config import config
from server.tests.creds import FULL
from server.services import qdrant as qdrant_service
from server.services.qdrant import (
    QdrantNotConfiguredError,
    default_collection_name,
    delete_collection,
    is_qdrant_configured,
    legacy_collection_name,
    list_collections,
    search_collection,
    sync_dataset_to_qdrant,
)


OWNER = "owner-1"
DS_ID = "ds-my-dataset"  # the id the stubbed dataset store gives "My Dataset"


@pytest.fixture(autouse=True)
def _dataset_store():
    """The dataset store, stubbed: every name resolves to a dataset owned by
    OWNER whose id is derived from the name — except "Ghost", which the owner
    doesn't have (also what another user's dataset looks like)."""

    def view(owner_id, name):
        if owner_id != OWNER or name == "Ghost":
            return None
        return {
            "id": DS_ID if name == "My Dataset" else f"ds-{name.lower()}",
            "name": name,
        }

    with patch("server.services.qdrant.get_dataset_view", side_effect=view) as stub:
        yield stub


class FakeQdrantClient:
    """Minimal stand-in for qdrant_client.QdrantClient used in tests."""

    def __init__(self):
        self.collections: dict[str, dict] = {}

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(self, collection_name: str, vectors_config) -> None:
        self.collections[collection_name] = {"points": {}, "config": vectors_config}

    def upsert(self, collection_name: str, points) -> None:
        store = self.collections[collection_name]["points"]
        for point in points:
            store[point.id] = point

    def get_collection(self, collection_name: str):
        count = len(self.collections[collection_name]["points"])
        return type("Info", (), {"points_count": count})()

    def query_points(
        self,
        collection_name: str,
        query,
        limit: int = 10,
        score_threshold=None,
        with_payload: bool = True,
    ):
        # Return stored points (newest-first irrelevant here) wrapped like a
        # QueryResponse; each scored 0.9. Honours limit and score_threshold.
        points = []
        for point in self.collections[collection_name]["points"].values():
            scored = type("Scored", (), {"payload": point.payload, "score": 0.9})()
            points.append(scored)
        if score_threshold is not None:
            points = [p for p in points if p.score >= score_threshold]
        points = points[:limit]
        return type("QueryResponse", (), {"points": points})()


class FakeLLM:
    """Stand-in for LLMService returning deterministic 3-dim vectors (offline)."""

    def __init__(self):
        self.calls = 0

    def embed_texts(
        self, texts: List[str], model: Optional[str] = None
    ) -> List[List[float]]:
        self.calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]


def _item(item_id: str, i: int) -> dict:
    """A stored Q/A pair in the shape get_dataset_pairs returns."""
    return {
        "id": item_id,
        "question": f"Question {i}?",
        "answer": f"Answer {i}.",
        "context": f"Context for item {i}.",
        "source_url": f"https://example.com/{i}",
        "confidence": 0.9,
        "metadata": {},
        "dataset_name": "My Dataset",
    }


# --- configuration helpers ---------------------------------------------------


def test_is_qdrant_configured_reflects_url(monkeypatch):
    monkeypatch.setattr(config, "qdrant_url", "")
    assert is_qdrant_configured() is False
    monkeypatch.setattr(config, "qdrant_url", "http://localhost:6333")
    assert is_qdrant_configured() is True


def test_collection_is_named_after_the_dataset_id(monkeypatch):
    monkeypatch.setattr(config, "qdrant_collection_prefix", "dataset_")
    assert default_collection_name("abc123") == "dataset_ds_abc123"


def test_two_datasets_with_the_same_name_never_share_a_collection(monkeypatch):
    """Names are unique per *owner* only: a slug of the name would collide."""
    monkeypatch.setattr(config, "qdrant_collection_prefix", "dataset_")
    assert default_collection_name("id-of-alices-docs") != default_collection_name(
        "id-of-bobs-docs"
    )


def test_a_dataset_that_predates_owners_keeps_its_collection(monkeypatch):
    monkeypatch.setattr(config, "qdrant_collection_prefix", "dataset_")
    # Recorded by the ownership migration: nothing is re-embedded.
    assert default_collection_name("any-id", "dataset_my_cool_dataset") == (
        "dataset_my_cool_dataset"
    )
    assert legacy_collection_name("My Cool Dataset!") == "dataset_my_cool_dataset"
    assert legacy_collection_name("  ") == "dataset_unnamed"


def test_get_qdrant_client_raises_when_unconfigured(monkeypatch):
    monkeypatch.setattr(config, "qdrant_url", "")
    with pytest.raises(QdrantNotConfiguredError):
        qdrant_service.get_qdrant_client()


# --- sync --------------------------------------------------------------------


def test_sync_dataset_creates_collection_and_upserts():
    items = [_item("h0", 0), _item("h1", 1), _item("h2", 2)]
    fake_client = FakeQdrantClient()
    fake_llm = FakeLLM()

    result = sync_dataset_to_qdrant(
        OWNER, "My Dataset", FULL, llm_service=fake_llm, client=fake_client, items=items
    )

    assert result["points_upserted"] == 3
    assert result["vector_size"] == 3
    assert result["collection_name"] == default_collection_name(DS_ID)
    points = fake_client.collections[result["collection_name"]]["points"]
    assert len(points) == 3
    assert fake_llm.calls == 1
    # Qdrant only accepts int/UUID point ids — item ids are SHA-256 digests, so
    # they must be mapped to valid UUIDs (regression: a raw digest is a 400).
    for point in points.values():
        uuid.UUID(str(point.id))
        assert point.payload["qa_id"] != point.id  # original id kept in payload
        assert point.payload["question"]
        assert point.payload["answer"]


def test_sync_is_idempotent_on_item_id():
    items = [_item("h0", 0), _item("h1", 1)]
    fake_client = FakeQdrantClient()
    fake_llm = FakeLLM()

    sync_dataset_to_qdrant(
        OWNER, "My Dataset", FULL, llm_service=fake_llm, client=fake_client, items=items
    )
    second = sync_dataset_to_qdrant(
        OWNER, "My Dataset", FULL, llm_service=fake_llm, client=fake_client, items=items
    )

    assert second["points_upserted"] == 2
    assert len(fake_client.collections[second["collection_name"]]["points"]) == 2


def test_sync_reads_pairs_from_the_store():
    """When items aren't injected, they're read from the dataset service."""
    fake_client = FakeQdrantClient()
    fake_llm = FakeLLM()
    stored = [_item("h0", 0), _item("h1", 1)]

    with patch(
        "server.services.qdrant.get_dataset_pairs", return_value=stored
    ) as mock_get:
        result = sync_dataset_to_qdrant(
            OWNER, "My Dataset", FULL, llm_service=fake_llm, client=fake_client
        )

    mock_get.assert_called_once_with(OWNER, "My Dataset")
    assert result["points_upserted"] == 2


def test_sync_empty_dataset_raises_value_error():
    with pytest.raises(ValueError, match="no Q/A pairs"):
        sync_dataset_to_qdrant(
            OWNER,
            "Empty",
            FULL,
            llm_service=FakeLLM(),
            client=FakeQdrantClient(),
            items=[],
        )


def test_sync_embeds_in_batches(monkeypatch):
    """Large datasets are embedded in fixed-size batches, not one giant call."""
    monkeypatch.setattr(qdrant_service, "_EMBED_BATCH_SIZE", 2)
    items = [_item(f"h{i}", i) for i in range(5)]
    fake_client = FakeQdrantClient()
    fake_llm = FakeLLM()

    result = sync_dataset_to_qdrant(
        OWNER, "My Dataset", FULL, llm_service=fake_llm, client=fake_client, items=items
    )

    # 5 items batched by 2 → 3 embedding calls (2, 2, 1), but still one point
    # per item, correctly matched (order preserved across batches).
    assert fake_llm.calls == 3
    assert result["points_upserted"] == 5
    points = fake_client.collections[result["collection_name"]]["points"]
    assert len(points) == 5


# --- search ------------------------------------------------------------------


def test_search_returns_scored_hits_from_payload():
    items = [_item("h0", 0), _item("h1", 1)]
    fake_client = FakeQdrantClient()
    fake_llm = FakeLLM()
    sync_dataset_to_qdrant(
        OWNER, "My Dataset", FULL, llm_service=fake_llm, client=fake_client, items=items
    )

    result = search_collection(
        OWNER,
        "My Dataset",
        FULL,
        "question 0",
        llm_service=fake_llm,
        client=fake_client,
    )

    assert result["dataset_name"] == "My Dataset"
    assert result["count"] == 2
    hit = result["results"][0]
    assert hit["question"]
    assert hit["answer"]
    assert hit["score"] == 0.9
    # The query was embedded (sync=1 call earlier, +1 for the search).
    assert fake_llm.calls == 2


def test_search_empty_query_raises_value_error():
    with pytest.raises(ValueError, match="must not be empty"):
        search_collection(
            OWNER,
            "My Dataset",
            FULL,
            "   ",
            llm_service=FakeLLM(),
            client=FakeQdrantClient(),
        )


def test_search_missing_collection_raises_value_error():
    with pytest.raises(ValueError, match="does not exist yet"):
        search_collection(
            OWNER,
            "Never Synced",
            FULL,
            "hello",
            llm_service=FakeLLM(),
            client=FakeQdrantClient(),
        )


def test_search_honours_limit():
    items = [_item(f"h{i}", i) for i in range(5)]
    fake_client = FakeQdrantClient()
    fake_llm = FakeLLM()
    sync_dataset_to_qdrant(
        OWNER, "My Dataset", FULL, llm_service=fake_llm, client=fake_client, items=items
    )

    result = search_collection(
        OWNER,
        "My Dataset",
        FULL,
        "anything",
        limit=2,
        llm_service=fake_llm,
        client=fake_client,
    )
    assert result["count"] == 2


# --- listing -----------------------------------------------------------------


def test_list_collections_unconfigured_qdrant(monkeypatch):
    monkeypatch.setattr(config, "qdrant_url", "")  # Qdrant off
    datasets = [
        {
            "id": "ds-1",
            "name": "Alpha",
            "description": "d",
            "qa_sources_count": 3,
            "target_language": None,
            "created_at": "2026-01-01",
            "qdrant_collection": None,
        },
    ]
    with patch("server.services.qdrant.list_datasets_view", return_value=datasets):
        result = list_collections(OWNER)

    assert result["qdrant_configured"] is False
    assert result["total"] == 1
    entry = result["collections"][0]
    assert entry["name"] == "Alpha"
    assert entry["qa_sources_count"] == 3
    assert entry["collection_name"] == default_collection_name("ds-1")
    # Qdrant off → status unknown.
    assert entry["in_qdrant"] is None
    assert entry["points_count"] is None


def test_list_collections_reports_qdrant_status(monkeypatch):
    monkeypatch.setattr(config, "qdrant_url", "http://localhost:6333")
    datasets = [
        {
            "id": "ds-2",
            "name": "Beta",
            "description": "d",
            "qa_sources_count": 2,
            "target_language": None,
            "created_at": "2026-01-02",
            "qdrant_collection": None,
        },
    ]
    fake_client = FakeQdrantClient()
    name = default_collection_name("ds-2")
    fake_client.create_collection(name, vectors_config=None)
    fake_client.collections[name]["points"]["x"] = object()

    with patch("server.services.qdrant.list_datasets_view", return_value=datasets):
        with patch(
            "server.services.qdrant.get_qdrant_client", return_value=fake_client
        ):
            result = list_collections(OWNER)

    assert result["qdrant_configured"] is True
    entry = result["collections"][0]
    assert entry["in_qdrant"] is True
    assert entry["points_count"] == 1


# --- ownership ---------------------------------------------------------------


def test_syncing_a_dataset_you_do_not_own_touches_nothing():
    fake_client = FakeQdrantClient()
    fake_llm = FakeLLM()
    with pytest.raises(ValueError, match="not found"):
        sync_dataset_to_qdrant(
            "someone-else",
            "My Dataset",
            FULL,
            llm_service=fake_llm,
            client=fake_client,
        )
    assert fake_client.collections == {}
    assert fake_llm.calls == 0  # not even embedded


def test_searching_a_dataset_you_do_not_own_is_a_not_found():
    with pytest.raises(ValueError, match="not found"):
        search_collection(
            OWNER,
            "Ghost",
            FULL,
            "hello",
            llm_service=FakeLLM(),
            client=FakeQdrantClient(),
        )
    with pytest.raises(ValueError, match="not found"):
        search_collection(
            "someone-else",
            "My Dataset",
            FULL,
            "hello",
            llm_service=FakeLLM(),
            client=FakeQdrantClient(),
        )


def test_sync_reads_the_stored_collection_of_a_legacy_dataset(_dataset_store):
    _dataset_store.side_effect = lambda owner, name: {
        "id": "old-id",
        "name": name,
        "qdrant_collection": "dev_legacy_slug",
    }
    fake_client = FakeQdrantClient()
    result = sync_dataset_to_qdrant(
        OWNER,
        "Legacy",
        FULL,
        llm_service=FakeLLM(),
        client=fake_client,
        items=[_item("h0", 0)],
    )
    assert result["collection_name"] == "dev_legacy_slug"
    assert "dev_legacy_slug" in fake_client.collections


def test_delete_collection_is_best_effort(monkeypatch):
    monkeypatch.setattr(config, "qdrant_url", "")
    assert delete_collection("dataset_ds_x") is False  # Qdrant off

    monkeypatch.setattr(config, "qdrant_url", "http://localhost:6333")

    class Client(FakeQdrantClient):
        deleted: list = []

        def delete_collection(self, name):
            self.deleted.append(name)

    client = Client()
    client.create_collection("dataset_ds_x", vectors_config=None)
    with patch("server.services.qdrant.get_qdrant_client", return_value=client):
        assert delete_collection("dataset_ds_x") is True
        assert delete_collection("dataset_ds_missing") is False
    assert client.deleted == ["dataset_ds_x"]
