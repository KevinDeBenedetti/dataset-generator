"""Vector collections: splits of Hub datasets embedded into Qdrant, then tested.

Owner-scoped: another user's collection answers 404, like an unknown one (see
tests/api/test_tenant_isolation.py). The dataset is read with the caller's own
Hugging Face token, so a split their token can't read can't be embedded; an
endpoint embedding model runs on the caller's own OpenAI-compatible key.
"""

from typing import Callable, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server.api.deps import get_credentials
from server.api.errors import internal_error
from server.core.database import get_db
from server.models.user import User
from server.schemas.collections import (
    CollectionBuildRequest,
    CollectionCreate,
    CollectionEvaluateRequest,
    CollectionEvaluation,
    CollectionOut,
    CollectionSearchOut,
    CollectionSearchRequest,
    CollectionsOut,
)
from server.services import collections, hub
from server.services.auth import get_current_user
from server.services.credentials import Credentials
from server.services.huggingface import HuggingFaceNotConfiguredError
from server.services.providers import get_provider
from server.services.jobs import QuotaExceededError, RunConflictError
from server.services.qdrant import QdrantNotConfiguredError, QdrantUnavailableError
from server.services.semantic import EmbeddingModelError

router = APIRouter(prefix="/collections", tags=["collections"])

T = TypeVar("T")


def _http(exc: Exception) -> HTTPException:
    """The answer to a known failure of a collection call."""
    if isinstance(exc, collections.CollectionNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (collections.CollectionConflictError, RunConflictError)):
        detail = str(exc)
        if isinstance(exc, RunConflictError):
            detail = "A collection is already being built: wait for it, or cancel it."
        return HTTPException(status_code=409, detail=detail)
    if isinstance(exc, (collections.CollectionQuotaError, QuotaExceededError)):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, collections.CollectionInputError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, (QdrantNotConfiguredError, HuggingFaceNotConfiguredError)):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, EmbeddingModelError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, QdrantUnavailableError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, hub.HubNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, hub.HubTooLargeError):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, hub.HubUnavailableError):
        return HTTPException(
            status_code=502,
            detail="The Hugging Face Hub didn't answer. Try again shortly.",
        )
    return internal_error("The request")


_KNOWN = (
    collections.CollectionNotFoundError,
    collections.CollectionConflictError,
    collections.CollectionQuotaError,
    collections.CollectionInputError,
    RunConflictError,
    QuotaExceededError,
    QdrantNotConfiguredError,
    QdrantUnavailableError,
    HuggingFaceNotConfiguredError,
    EmbeddingModelError,
    hub.HubNotFoundError,
    hub.HubTooLargeError,
    hub.HubUnavailableError,
)


def _call(fn: Callable[[], T], what: str) -> T:
    try:
        return fn()
    except _KNOWN as e:
        raise _http(e) from e
    except Exception:
        raise internal_error(what) from None


@router.get("", response_model=CollectionsOut, summary="Your vector collections")
async def get_collections(
    discover: bool = Query(
        False,
        description="Also ask your OpenAI-compatible endpoint which embedding "
        "models it serves (a network call, 5 s max, then cached a few minutes) "
        "on top of OPENAI_EMBEDDING_MODEL",
    ),
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
    db: Session = Depends(get_db),
):
    """Your collections, most recently changed first, with the embedding models
    a collection can use (your endpoint's, then the local ones) and whether
    Qdrant is set up."""
    if discover:
        await get_provider("openai").list_models(creds)
    return await run_in_threadpool(
        _call,
        lambda: collections.list_collections(db, user.id, creds),
        "Listing collections",
    )


@router.post(
    "",
    response_model=CollectionOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a collection from a split",
)
async def post_collection(
    body: CollectionCreate,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
    db: Session = Depends(get_db),
):
    """Pin the split at its latest commit (or ``revision``) and queue its build:
    a worker embeds every row. Poll ``GET /collections/{id}`` for progress."""
    try:
        return await collections.create_collection(
            db, user.id, creds, body.model_dump()
        )
    except _KNOWN as e:
        raise _http(e) from e
    except Exception:
        raise internal_error("Creating the collection") from None


@router.get("/{collection_id}", response_model=CollectionOut, summary="One collection")
def get_collection(
    collection_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _call(
        lambda: collections.get_collection(db, user.id, collection_id),
        "Reading the collection",
    )


@router.post(
    "/{collection_id}/build",
    response_model=CollectionOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Build a collection again",
)
async def build_collection(
    collection_id: str,
    body: CollectionBuildRequest,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
    db: Session = Depends(get_db),
):
    """Re-embed the split at the dataset's latest commit (or ``revision``):
    the collection's vectors are replaced."""
    try:
        return await collections.rebuild_collection(
            db, user.id, creds, collection_id, body.revision
        )
    except _KNOWN as e:
        raise _http(e) from e
    except Exception:
        raise internal_error("Building the collection") from None


@router.delete(
    "/{collection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a collection",
)
def delete_collection(
    collection_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Deletes the collection and its vectors; the dataset stays on the Hub."""
    _call(
        lambda: collections.delete_collection(db, user.id, collection_id),
        "Deleting the collection",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{collection_id}/search",
    response_model=CollectionSearchOut,
    summary="Search a collection",
)
def search_collection(
    collection_id: str,
    body: CollectionSearchRequest,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
    db: Session = Depends(get_db),
):
    """The rows closest to the query, embedded with the collection's model."""
    return _call(
        lambda: collections.search(
            db,
            user.id,
            collection_id,
            body.query,
            body.limit,
            body.score_threshold,
            creds=creds,
        ),
        "Searching the collection",
    )


@router.post(
    "/{collection_id}/evaluate",
    response_model=CollectionEvaluation,
    summary="Test a collection's retrieval",
)
def evaluate_collection(
    collection_id: str,
    body: CollectionEvaluateRequest,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
    db: Session = Depends(get_db),
):
    """Sampled rows ask with their query column; a row whose own point comes
    back first is a hit. Saved as the collection's latest test."""
    return _call(
        lambda: collections.evaluate(
            db,
            user.id,
            collection_id,
            body.sample,
            body.k,
            body.query_column,
            creds=creds,
        ),
        "Testing the collection",
    )
