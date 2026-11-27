"""Qdrant, the vector store behind the collections (services/collections.py).

Off until ``QDRANT_URL`` is set: every call then raises
:class:`QdrantNotConfiguredError`, which the routes answer with a 503. The
client is built on first use, once per process, so an absent or unreachable
Qdrant never stops the app from booting; tests swap :func:`get_client` for
qdrant-client's in-memory mode.

Point ids are row positions in the collection's split (unsigned integers, as
Qdrant requires), and vectors are compared by cosine.
"""

import logging
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TypeVar

import numpy as np

from server.core.config import config

logger = logging.getLogger(__name__)

T = TypeVar("T")

# (point id, cosine), most similar first.
Hit = Tuple[int, float]


class QdrantNotConfiguredError(RuntimeError):
    """Collections need a Qdrant, and QDRANT_URL is unset."""


class QdrantUnavailableError(RuntimeError):
    """Qdrant didn't answer, or refused the request (logged with its reason)."""


NOT_CONFIGURED = (
    "Vector collections need a Qdrant: set QDRANT_URL (and QDRANT_API_KEY when "
    "it requires one)."
)


def is_configured() -> bool:
    return bool(config.qdrant_url)


_lock = threading.Lock()
_client: Any = None
_client_key: Optional[Tuple[str, str]] = None


def get_client() -> Any:
    """The process-wide client (thread-safe), or QdrantNotConfiguredError."""
    global _client, _client_key
    if not is_configured():
        raise QdrantNotConfiguredError(NOT_CONFIGURED)
    key = (config.qdrant_url, config.qdrant_api_key)
    with _lock:
        if _client is None or _client_key != key:
            # Imported here: the package pulls in grpc, which the app only
            # needs once collections are used.
            from qdrant_client import QdrantClient

            # No version check: it is a request to a server that may be down,
            # made while holding the lock (docker-compose.yml pins the image).
            _client = QdrantClient(
                url=config.qdrant_url,
                api_key=config.qdrant_api_key or None,
                timeout=30,
                check_compatibility=False,
            )
            _client_key = key
        return _client


def _call(what: str, fn: Callable[[Any], T]) -> T:
    """``fn(client)``, its failures turned into QdrantUnavailableError.

    The client's own message (a URL, a response body) is logged, not passed on.
    """
    client = get_client()
    try:
        return fn(client)
    except QdrantNotConfiguredError:
        raise
    except Exception as exc:
        logger.warning("Qdrant: %s failed: %s", what, exc)
        raise QdrantUnavailableError(
            f"Qdrant didn't answer while {what}. Check that it is running and "
            "reachable at QDRANT_URL."
        ) from None


def collection_name(collection_id: str) -> str:
    """The Qdrant collection of a ``vector_collections`` row: its id, never a
    user-chosen name, behind the deployment's prefix."""
    return f"{config.qdrant_collection_prefix}c_{collection_id}"


def build_name(name: str) -> str:
    """A new collection for one build of ``name``: the build fills it, then
    :func:`publish` makes ``name`` point at it."""
    return f"{name}_{uuid.uuid4().hex[:12]}"


def publish(name: str, built: str) -> None:
    """Make ``name`` an alias of ``built``, then drop what it named before.

    The switch is one atomic call in Qdrant: a search sees the previous
    vectors, then the new ones, never nothing. The one exception is a
    collection from before builds were aliased — a real collection called
    ``name``, which an alias can't share a name with: it is deleted first.
    """
    from qdrant_client import models

    def run(client: Any) -> None:
        aliases = {a.alias_name for a in client.get_aliases().aliases}
        operations: List[Any] = []
        if name in aliases:
            operations.append(
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=name)
                )
            )
        elif client.collection_exists(name):
            client.delete_collection(name)
        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(collection_name=built, alias_name=name)
            )
        )
        client.update_collection_aliases(change_aliases_operations=operations)

    _call("publishing a collection", run)
    logger.info("Qdrant: %s now names %s", name, built)
    for other in builds_of(name):
        if other != built:
            drop_build(other)


def builds_of(name: str) -> List[str]:
    """The collections built for ``name``: the one it names and any left over."""
    prefix = f"{name}_"
    return [n for n in names() if n.startswith(prefix)]


def claim(name: str, owner: str) -> Optional[str]:
    """Mark the collection ``name`` as ``owner``'s, unless another owner did.

    The mark is a one-point collection whose payload says who made it: the
    owner already there (``owner`` itself on a fresh claim) is returned.
    """
    from qdrant_client import models

    def run(client: Any) -> Optional[str]:
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=1, distance=models.Distance.COSINE
                ),
            )
            client.upsert(
                collection_name=name,
                points=models.Batch(
                    ids=[1], vectors=[[1.0]], payloads=[{"owner": owner}]
                ),
                wait=True,
            )
        points = client.retrieve(collection_name=name, ids=[1], with_payload=True)
        return str((points[0].payload or {}).get("owner")) if points else None

    return _call("claiming the collection prefix", run)


def names() -> List[str]:
    """Every collection in Qdrant, this deployment's and any other's."""
    return _call(
        "listing the collections",
        lambda c: [col.name for col in c.get_collections().collections],
    )


def exists(name: str) -> bool:
    return _call("checking a collection", lambda c: bool(c.collection_exists(name)))


def recreate(name: str, size: int) -> None:
    """An empty collection of ``size``-dimension cosine vectors, replacing any."""
    from qdrant_client import models

    def run(client: Any) -> None:
        if client.collection_exists(name):
            client.delete_collection(name)
        client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=size, distance=models.Distance.COSINE
            ),
        )

    _call("creating a collection", run)
    logger.info("Qdrant: created %s (%d dimensions)", name, size)


def upsert(
    name: str, ids: Sequence[int], vectors: np.ndarray, payloads: List[Dict[str, Any]]
) -> None:
    from qdrant_client import models

    batch = models.Batch(
        ids=[int(i) for i in ids],
        vectors=np.asarray(vectors, dtype=np.float32).tolist(),
        payloads=payloads,
    )
    _call(
        "storing vectors",
        lambda c: c.upsert(collection_name=name, points=batch, wait=True),
    )


def count(name: str) -> int:
    return _call(
        "counting points",
        lambda c: int(c.count(collection_name=name, exact=True).count),
    )


def search(
    name: str,
    vector: np.ndarray,
    limit: int,
    score_threshold: Optional[float] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Tuple[int, float, Dict[str, Any]]]:
    """The ``limit`` points closest to ``vector``, with their payloads; only
    those whose payload ``key`` (dotted for a nested field) equals each
    ``filters`` value."""
    from qdrant_client import models

    query_filter = None
    if filters:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
                for key, value in filters.items()
            ]
        )
    response = _call(
        "searching",
        lambda c: c.query_points(
            collection_name=name,
            query=np.asarray(vector, dtype=np.float32).tolist(),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            query_filter=query_filter,
        ),
    )
    return [(int(p.id), float(p.score), dict(p.payload or {})) for p in response.points]


def search_batch(name: str, vectors: np.ndarray, limit: int) -> List[List[Hit]]:
    """Per vector, the ids and scores of its ``limit`` closest points."""
    from qdrant_client import models

    requests = [
        models.QueryRequest(query=v.tolist(), limit=limit, with_payload=False)
        for v in np.asarray(vectors, dtype=np.float32)
    ]
    responses = _call(
        "searching",
        lambda c: c.query_batch_points(collection_name=name, requests=requests),
    )
    return [[(int(p.id), float(p.score)) for p in r.points] for r in responses]


def retrieve(name: str, ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    """The payloads of the points among ``ids`` that exist."""
    points = _call(
        "reading points",
        lambda c: c.retrieve(
            collection_name=name,
            ids=[int(i) for i in ids],
            with_payload=True,
            with_vectors=False,
        ),
    )
    return {int(p.id): dict(p.payload or {}) for p in points}


def drop_build(name: str) -> bool:
    """Delete one collection, best effort: True when it was dropped. Never
    raises (see :func:`drop`)."""
    if not is_configured():
        return False
    try:
        client = get_client()
        if client.collection_exists(name):
            client.delete_collection(name)
            logger.info("Qdrant: dropped %s", name)
            return True
    except Exception as exc:  # noqa: BLE001 — best effort
        logger.warning("Qdrant: could not drop %s: %s", name, exc)
    return False


def drop(name: str) -> bool:
    """Delete everything ``name`` has in Qdrant — the collection it names,
    builds left over, a collection from before builds were aliased — best
    effort: True when something was dropped.

    Never raises — it runs after the row is gone (a deleted collection or
    account), which a Qdrant outage must not undo.
    """
    if not is_configured():
        return False
    try:
        targets = [*builds_of(name), name]
    except Exception as exc:  # noqa: BLE001 — best effort, see above
        logger.warning("Qdrant: could not drop %s: %s", name, exc)
        return False
    # ``name`` last: once its builds are gone it is no alias any more, and
    # only a collection from before aliases still answers to it.
    return any([drop_build(target) for target in targets])
