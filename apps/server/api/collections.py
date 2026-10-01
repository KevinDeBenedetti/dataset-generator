import logging

from fastapi import APIRouter, Depends, HTTPException

from server.models.user import User
from server.api.deps import get_credentials
from server.services.auth import get_current_user
from server.services.credentials import Credentials
from server.services.qdrant import (
    QdrantNotConfiguredError,
    list_collections,
    search_collection,
    sync_dataset_to_qdrant,
)
from server.schemas.collection import (
    CollectionSearchRequest,
    CollectionSearchResponse,
    CollectionsResponse,
    QdrantSyncResponse,
)

router = APIRouter(prefix="/collections", tags=["collections"])


@router.get("", response_model=CollectionsResponse)
async def get_collections(user: User = Depends(get_current_user)):
    """List the stored datasets as collections, annotated with their Qdrant status."""
    try:
        return list_collections(user.id)
    except Exception as e:
        logging.error(f"Error listing collections: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{dataset_name}/qdrant",
    response_model=QdrantSyncResponse,
    # Embeds every Q/A item with the caller's own OpenAI key.
)
async def push_collection_to_qdrant(
    dataset_name: str,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
):
    """Embed a dataset's Q/A pairs and upsert them into Qdrant."""
    try:
        return sync_dataset_to_qdrant(user.id, dataset_name, creds)
    except QdrantNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error syncing dataset {dataset_name} to Qdrant: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{dataset_name}/search", response_model=CollectionSearchResponse)
async def search_collection_endpoint(
    dataset_name: str,
    body: CollectionSearchRequest,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
):
    """Embed the query and return the most similar Q/A pairs from the collection."""
    try:
        return search_collection(
            user.id,
            dataset_name,
            creds,
            query=body.query,
            limit=body.limit,
            score_threshold=body.score_threshold,
        )
    except QdrantNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error searching collection {dataset_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
