"""Push a dataset's Q/A pairs into a Qdrant collection as embeddings.

A "collection" in the UI is a stored dataset projected into Qdrant: each Q/A
pair becomes a point whose vector is the embedding of its question + answer +
context, with the original fields kept in the payload for retrieval.

Datasets are read from Postgres (the source of truth); Qdrant is the optional
vector store, which degrades to a clear 503 when not configured/reachable.
"""

import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Protocol

from server.core.config import config
from server.services.datasets import (
    get_dataset_pairs,
    get_dataset_view,
    list_datasets_view,
)
from server.services.credentials import Credentials
from server.services.llm import LLMService

logger = logging.getLogger(__name__)

# Q/A pairs are embedded in batches rather than one `embeddings.create` call
# for the whole dataset — a large dataset could otherwise exceed the
# embedding endpoint's per-request token/size limit.
_EMBED_BATCH_SIZE = 100


class Embedder(Protocol):
    """Anything that can turn texts into vectors (LLMService satisfies this)."""

    def embed_texts(
        self, texts: List[str], model: Optional[str] = None
    ) -> List[List[float]]: ...


class QdrantNotConfiguredError(RuntimeError):
    """Raised when a Qdrant operation is attempted without configuration."""


def is_qdrant_configured() -> bool:
    """True when a Qdrant URL is set (the API key is optional)."""
    return bool(config.qdrant_url)


def default_collection_name(dataset_id: str, stored: Optional[str] = None) -> str:
    """The Qdrant collection holding a dataset's embeddings.

    Named after the dataset's immutable id — never its (user-chosen, non-unique
    across users) name, whose slug could collide between two owners. A dataset
    that predates owners keeps the ``<prefix><slug>`` collection recorded in
    ``datasets.qdrant_collection`` (``stored``), so nothing is re-embedded.
    """
    return stored or f"{config.qdrant_collection_prefix}ds_{dataset_id}"


def legacy_collection_name(dataset_name: str) -> str:
    """The pre-owner collection name (``<prefix><slug>``) — for the migration and
    for tests; new datasets never use it."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", dataset_name.strip().lower()).strip("_")
    return f"{config.qdrant_collection_prefix}{slug or 'unnamed'}"


def get_dataset_collection(owner_id: str, dataset_name: str) -> str:
    """The collection of one of ``owner_id``'s datasets.

    Raises ValueError for a dataset the owner doesn't have — which is also what
    another user's dataset looks like.
    """
    dataset = get_dataset_view(owner_id, dataset_name)
    if dataset is None:
        raise ValueError(f"Dataset '{dataset_name}' not found")
    return default_collection_name(dataset["id"], dataset.get("qdrant_collection"))


def get_qdrant_client() -> Any:
    """Build a Qdrant client, or raise QdrantNotConfiguredError.

    The import is lazy so the package being absent degrades to a 503 instead of
    crashing app startup.
    """
    if not is_qdrant_configured():
        raise QdrantNotConfiguredError(
            "Qdrant is not configured. Set QDRANT_URL (and optionally "
            "QDRANT_API_KEY) to enable collections."
        )
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:  # pragma: no cover - defensive, dep is declared
        raise QdrantNotConfiguredError(
            "qdrant-client is not installed in this environment."
        ) from exc

    return QdrantClient(
        url=config.qdrant_url,
        api_key=config.qdrant_api_key or None,
    )


def _point_id(qa_id: str) -> str:
    """Map a Q/A id to a valid Qdrant point id.

    Qdrant only accepts an unsigned integer or a UUID as a point id, but Q/A ids
    are SHA-256 hex digests. Derive a deterministic UUID from the digest (the
    original id is kept in the payload as ``qa_id``). Deterministic → re-syncing
    overwrites the same point, so the sync stays idempotent.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, qa_id))


def _item_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a stored Q/A pair into the fields kept in the point payload."""
    return {
        "qa_id": item.get("id"),
        "dataset_name": item.get("dataset_name"),
        "question": item.get("question", ""),
        "answer": item.get("answer", ""),
        "context": item.get("context", ""),
        "source_url": item.get("source_url", ""),
        "confidence": item.get("confidence", 1.0),
    }


def _item_to_text(item: Dict[str, Any]) -> str:
    """Flatten a Q/A item into the text that gets embedded."""
    f = _item_fields(item)
    parts = [f["question"], f["answer"], f["context"]]
    return "\n\n".join(part for part in parts if part).strip()


def _embed_in_batches(llm_service: Embedder, texts: List[str]) -> List[List[float]]:
    """Embed ``texts`` in fixed-size batches (``_EMBED_BATCH_SIZE``), preserving order."""
    vectors: List[List[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        vectors.extend(llm_service.embed_texts(texts[i : i + _EMBED_BATCH_SIZE]))
    return vectors


def delete_collection(name: str) -> bool:
    """Drop a Qdrant collection (best-effort).

    Returns True if a collection was dropped, False if Qdrant is unconfigured,
    the collection doesn't exist, or the drop failed. Never raises — used as a
    cascade when a dataset is deleted, which must not fail on Qdrant issues.
    """
    if not is_qdrant_configured():
        return False
    try:
        client = get_qdrant_client()
        if client.collection_exists(name):
            client.delete_collection(name)
            logger.info("Dropped Qdrant collection %s", name)
            return True
    except Exception as exc:
        logger.warning("Could not drop Qdrant collection %s: %s", name, exc)
    return False


def get_collection_status(
    client: Any, collection_name: str
) -> Optional[Dict[str, Any]]:
    """Return ``{exists, points_count}`` for a collection, or None on error.

    Best-effort: a transient Qdrant failure must not break listing datasets, so
    callers treat None as "unknown".
    """
    try:
        if not client.collection_exists(collection_name):
            return {"exists": False, "points_count": 0}
        info = client.get_collection(collection_name)
        # points_count can be None right after creation; coerce to 0.
        count = getattr(info, "points_count", None) or 0
        return {"exists": True, "points_count": count}
    except Exception as exc:
        logger.warning("Qdrant status check failed for %s: %s", collection_name, exc)
        return None


def sync_dataset_to_qdrant(
    owner_id: str,
    dataset_name: str,
    creds: Credentials,
    llm_service: Optional[Embedder] = None,
    client: Any = None,
    items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Embed every Q/A pair of a dataset and upsert them into Qdrant.

    Reads the pairs from Postgres (unless ``items`` is injected for testing),
    creates the collection (sized from the first embedding) if needed, then
    upserts one point per item keyed by a deterministic UUID of the item id so
    re-syncing is idempotent. ``llm_service``/``client`` are injectable too.

    Raises ValueError for an empty/unknown dataset and QdrantNotConfiguredError
    when Qdrant isn't wired up.
    """
    from qdrant_client import models as qmodels

    # Raises ValueError for a dataset the owner doesn't have.
    collection_name = get_dataset_collection(owner_id, dataset_name)
    if items is None:
        items = get_dataset_pairs(owner_id, dataset_name)
    if not items:
        raise ValueError(f"Dataset '{dataset_name}' has no Q/A pairs to sync")

    llm_service = llm_service or LLMService(creds)
    client = client or get_qdrant_client()

    texts = [_item_to_text(it) for it in items]
    vectors = _embed_in_batches(llm_service, texts)
    if len(vectors) != len(items):
        raise RuntimeError(
            f"Embedding count mismatch: {len(vectors)} vectors for {len(items)} items"
        )

    vector_size = len(vectors[0])
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(
                size=vector_size, distance=qmodels.Distance.COSINE
            ),
        )
        logger.info(
            "Created Qdrant collection %s (dim=%d)", collection_name, vector_size
        )

    points = [
        qmodels.PointStruct(
            id=_point_id(str(it["id"])),
            vector=vector,
            payload=_item_fields(it),
        )
        for it, vector in zip(items, vectors)
    ]
    client.upsert(collection_name=collection_name, points=points)

    logger.info(
        "Synced %d points to Qdrant collection %s", len(points), collection_name
    )
    return {
        "dataset_name": dataset_name,
        "collection_name": collection_name,
        "points_upserted": len(points),
        "vector_size": vector_size,
    }


def search_collection(
    owner_id: str,
    dataset_name: str,
    creds: Credentials,
    query: str,
    limit: int = 10,
    score_threshold: Optional[float] = None,
    llm_service: Optional[Embedder] = None,
    client: Any = None,
) -> Dict[str, Any]:
    """Embed ``query`` and return the most similar Q/A points from the dataset's
    Qdrant collection.

    The counterpart to :func:`sync_dataset_to_qdrant`: that ingests, this reads.
    ``llm_service``/``client`` are injectable for testing. Raises
    QdrantNotConfiguredError when Qdrant isn't wired up and ValueError when the
    query is empty or the collection hasn't been synced yet.
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("Search query must not be empty")

    # Raises ValueError for a dataset the owner doesn't have.
    collection_name = get_dataset_collection(owner_id, dataset_name)
    llm_service = llm_service or LLMService(creds)
    client = client or get_qdrant_client()

    if not client.collection_exists(collection_name):
        raise ValueError(
            f"Collection for dataset '{dataset_name}' does not exist yet — "
            "sync it to Qdrant first"
        )

    query_vector = llm_service.embed_texts([query])[0]
    response = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        limit=limit,
        score_threshold=score_threshold,
        with_payload=True,
    )
    # query_points returns a QueryResponse with .points; tolerate a bare list too.
    points = getattr(response, "points", response)

    results: List[Dict[str, Any]] = []
    for point in points:
        payload = getattr(point, "payload", None) or {}
        results.append(
            {
                "qa_id": payload.get("qa_id"),
                "question": payload.get("question", ""),
                "answer": payload.get("answer", ""),
                "context": payload.get("context", ""),
                "source_url": payload.get("source_url", ""),
                "confidence": payload.get("confidence"),
                "score": getattr(point, "score", None),
            }
        )

    logger.info(
        "Searched Qdrant collection %s (%d hit(s))", collection_name, len(results)
    )
    return {
        "dataset_name": dataset_name,
        "collection_name": collection_name,
        "query": query,
        "count": len(results),
        "results": results,
    }


def list_collections(owner_id: str) -> Dict[str, Any]:
    """List the stored datasets as collections, annotated with their Qdrant status.

    ``qdrant_configured`` tells the UI whether the "Add to Qdrant" action is
    available; when configured, each dataset is annotated with ``in_qdrant``
    and ``points_count`` (best-effort; left null if Qdrant can't be reached).
    """
    datasets = list_datasets_view(owner_id)
    qdrant_configured = is_qdrant_configured()

    client = None
    if qdrant_configured:
        try:
            client = get_qdrant_client()
        except Exception as exc:
            logger.warning("Could not build Qdrant client for listing: %s", exc)
            client = None

    collections: List[Dict[str, Any]] = []
    for dataset in datasets:
        name = dataset["name"]
        collection_name = default_collection_name(
            dataset["id"], dataset.get("qdrant_collection")
        )
        in_qdrant: Optional[bool] = None
        points_count: Optional[int] = None
        if client is not None:
            status = get_collection_status(client, collection_name)
            if status is not None:
                in_qdrant = status["exists"]
                points_count = status["points_count"] if status["exists"] else 0
        collections.append(
            {
                "id": dataset.get("id"),
                "name": name,
                "description": dataset.get("description"),
                "target_language": dataset.get("target_language"),
                "qa_sources_count": dataset.get("qa_sources_count"),
                "created_at": dataset.get("created_at"),
                "collection_name": collection_name,
                "in_qdrant": in_qdrant,
                "points_count": points_count,
            }
        )

    return {
        "qdrant_configured": qdrant_configured,
        "total": len(collections),
        "collections": collections,
    }
