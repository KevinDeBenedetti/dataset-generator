import logging

from fastapi import APIRouter, Depends, HTTPException

from server.services.auth import require_admin
from server.services.qdrant import (
    LangfuseUnavailableError,
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
async def get_collections():
    """List Langfuse datasets as collections, annotated with their Qdrant status."""
    try:
        return list_collections()
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logging.error(f"Error listing collections: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{dataset_name}/qdrant",
    response_model=QdrantSyncResponse,
    # Costly (embeds every Q/A item + writes to Qdrant) — admin only.
    dependencies=[Depends(require_admin)],
)
async def push_collection_to_qdrant(dataset_name: str):
    """Embed a Langfuse dataset's Q/A items and upsert them into Qdrant."""
    try:
        return sync_dataset_to_qdrant(dataset_name)
    except QdrantNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error syncing dataset {dataset_name} to Qdrant: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{dataset_name}/search", response_model=CollectionSearchResponse)
async def search_collection_endpoint(
    dataset_name: str, body: CollectionSearchRequest
):
    """Embed the query and return the most similar Q/A pairs from the collection."""
    try:
        return search_collection(
            dataset_name,
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
