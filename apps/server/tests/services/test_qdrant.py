"""Tests for the Qdrant collections service (Langfuse-backed).

Datasets/items are read from Langfuse; here those reads are stubbed and a fake
in-memory Qdrant client records upserts, so the whole path runs offline.
"""

import uuid
from typing import List, Optional
from unittest.mock import patch

import pytest

from server.core.config import config
from server.services import qdrant as qdrant_service
from server.services.qdrant import (
    LangfuseUnavailableError,
    QdrantNotConfiguredError,
    collection_name_for,
    is_qdrant_configured,
    list_collections,
    sync_dataset_to_qdrant,
)


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


class FakeLLM:
    """Stand-in for LLMService returning deterministic 3-dim vectors (offline)."""

    def __init__(self):
        self.calls = 0

    def embed_texts(
        self, texts: List[str], model: Optional[str] = None
    ) -> List[List[float]]:
        self.calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]


def _item(item_id: str, i: int, status: str = "ACTIVE") -> dict:
    """A Langfuse dataset item in the shape get_dataset_items returns."""
    return {
        "id": item_id,
        "status": status,
        "input": {
            "question": f"Question {i}?",
            "context": f"Context for item {i}.",
            "source_url": f"https://example.com/{i}",
        },
        "expected_output": {"answer": f"Answer {i}.", "confidence": 0.9},
        "metadata": {},
        "dataset_name": "My Dataset",
    }


# --- configuration helpers ---------------------------------------------------


def test_is_qdrant_configured_reflects_url(monkeypatch):
    monkeypatch.setattr(config, "qdrant_url", "")
    assert is_qdrant_configured() is False
    monkeypatch.setattr(config, "qdrant_url", "http://localhost:6333")
    assert is_qdrant_configured() is True


def test_collection_name_sanitises_and_prefixes(monkeypatch):
    monkeypatch.setattr(config, "qdrant_collection_prefix", "dataset_")
    assert collection_name_for("My Cool Dataset!") == "dataset_my_cool_dataset"
    assert collection_name_for("  ") == "dataset_unnamed"


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
        "My Dataset", llm_service=fake_llm, client=fake_client, items=items
    )

    assert result["points_upserted"] == 3
    assert result["vector_size"] == 3
    assert result["collection_name"] == collection_name_for("My Dataset")
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
        "My Dataset", llm_service=fake_llm, client=fake_client, items=items
    )
    second = sync_dataset_to_qdrant(
        "My Dataset", llm_service=fake_llm, client=fake_client, items=items
    )

    assert second["points_upserted"] == 2
    assert len(fake_client.collections[second["collection_name"]]["points"]) == 2


def test_sync_reads_active_items_from_langfuse():
    """When items aren't injected, they're read from Langfuse (archived dropped)."""
    fake_client = FakeQdrantClient()
    fake_llm = FakeLLM()
    langfuse_items = [_item("h0", 0), _item("h1", 1, status="ARCHIVED")]

    with patch(
        "server.services.qdrant.get_dataset_items", return_value=langfuse_items
    ) as mock_get:
        result = sync_dataset_to_qdrant(
            "My Dataset", llm_service=fake_llm, client=fake_client
        )

    mock_get.assert_called_once_with("My Dataset")
    # Only the ACTIVE item is synced.
    assert result["points_upserted"] == 1


def test_sync_empty_dataset_raises_value_error():
    with pytest.raises(ValueError, match="no Q/A pairs"):
        sync_dataset_to_qdrant(
            "Empty", llm_service=FakeLLM(), client=FakeQdrantClient(), items=[]
        )


# --- listing -----------------------------------------------------------------


def test_list_collections_raises_when_langfuse_unavailable():
    with patch("server.services.qdrant.is_langfuse_available", return_value=False):
        with pytest.raises(LangfuseUnavailableError):
            list_collections()


def test_list_collections_unconfigured_qdrant(monkeypatch):
    monkeypatch.setattr(config, "qdrant_url", "")  # Qdrant off, Langfuse on
    datasets = [
        {
            "id": "lf-1",
            "name": "Alpha",
            "description": "d",
            "item_count": 3,
            "created_at": "2026-01-01",
            "metadata": {},
        },
    ]
    with patch("server.services.qdrant.is_langfuse_available", return_value=True):
        with patch("server.services.qdrant.list_datasets", return_value=datasets):
            result = list_collections()

    assert result["qdrant_configured"] is False
    assert result["total"] == 1
    entry = result["collections"][0]
    assert entry["name"] == "Alpha"
    assert entry["qa_sources_count"] == 3
    assert entry["collection_name"] == collection_name_for("Alpha")
    # Qdrant off → status unknown.
    assert entry["in_qdrant"] is None
    assert entry["points_count"] is None


def test_list_collections_reports_qdrant_status(monkeypatch):
    monkeypatch.setattr(config, "qdrant_url", "http://localhost:6333")
    datasets = [
        {
            "id": "lf-2",
            "name": "Beta",
            "description": "d",
            "item_count": 2,
            "created_at": "2026-01-02",
            "metadata": {},
        },
    ]
    fake_client = FakeQdrantClient()
    name = collection_name_for("Beta")
    fake_client.create_collection(name, vectors_config=None)
    fake_client.collections[name]["points"]["x"] = object()

    with patch("server.services.qdrant.is_langfuse_available", return_value=True):
        with patch("server.services.qdrant.list_datasets", return_value=datasets):
            with patch(
                "server.services.qdrant.get_qdrant_client", return_value=fake_client
            ):
                result = list_collections()

    assert result["qdrant_configured"] is True
    entry = result["collections"][0]
    assert entry["in_qdrant"] is True
    assert entry["points_count"] == 1
