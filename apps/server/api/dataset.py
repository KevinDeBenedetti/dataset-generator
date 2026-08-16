import logging
from typing import List, Union

from fastapi import APIRouter, Depends, HTTPException, Query

from server.services.auth import require_admin
from server.services.dataset_reads import (
    AmbiguousRecordError,
    list_datasets_view,
    get_dataset_view,
    create_dataset as create_dataset_view,
    delete_dataset as delete_dataset_view,
    analyze_similarities_view,
    clean_similarities_view,
    get_dataset_sources_view,
    resolve_similarity_pair,
)
from server.services.langfuse import LangfuseUnavailableError
from server.schemas.dataset import (
    DatasetResponse,
    DatasetSourcesResponse,
    SimilarityAnalysisResponse,
    CleanSimilarityResponse,
    DeleteDatasetResponse,
    ResolvePairRequest,
    ResolvePairResponse,
)

router = APIRouter(
    tags=["dataset"],
)


@router.post("/dataset", response_model=DatasetResponse)
async def create_dataset(
    name: str = Query(..., description="Name of the new dataset"),
    description: str = Query(None, description="Optional dataset description"),
):
    """Create a new (empty) dataset in Langfuse."""
    try:
        return create_dataset_view(name, description)
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"Error creating new dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dataset", response_model=Union[DatasetResponse, List[DatasetResponse]])
async def get_all_datasets(
    dataset_id: str = Query(
        None,
        description="Optional dataset name to get a specific dataset's details",
    ),
):
    """Retrieve all datasets from Langfuse, or a specific one (by name)."""
    try:
        if dataset_id:
            dataset = get_dataset_view(dataset_id)
            if not dataset:
                raise HTTPException(
                    status_code=404, detail=f"Dataset '{dataset_id}' not found"
                )
            return dataset
        return list_datasets_view()
    except HTTPException:
        raise
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logging.error(f"Error fetching datasets: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dataset/{dataset_name}/sources", response_model=DatasetSourcesResponse)
async def get_dataset_sources(dataset_name: str):
    """List the sources a dataset was built from, with its analysis history."""
    try:
        return get_dataset_sources_view(dataset_name)
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error fetching sources for {dataset_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/dataset/{dataset_name}/analyze-similarities",
    response_model=SimilarityAnalysisResponse,
)
async def analyze_similarities(
    dataset_name: str,
    threshold: float = Query(0.8, description="Similarity threshold"),
):
    """Analyze near-duplicate questions in a dataset (read-only)."""
    try:
        return analyze_similarities_view(dataset_name, threshold)
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error in analyze_similarities endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/dataset/{dataset_name}/clean-similarities",
    response_model=CleanSimilarityResponse,
    # Destructive (deletes Langfuse items) — admin only.
    dependencies=[Depends(require_admin)],
)
async def clean_similarities(
    dataset_name: str,
    threshold: float = Query(
        0.8, description="Similarity threshold to detect duplicates (0.0-1.0)"
    ),
):
    """Remove near-duplicate questions from a dataset (deletes Langfuse items)."""
    try:
        return clean_similarities_view(dataset_name, threshold)
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error in clean_similarities endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/dataset/{dataset_name}/resolve-pair",
    response_model=ResolvePairResponse,
    # Destructive (deletes one Langfuse item) — admin only, like clean.
    dependencies=[Depends(require_admin)],
)
async def resolve_pair(dataset_name: str, body: ResolvePairRequest):
    """Arbitrate a single duplicate pair: delete the given record, keep the other.

    Accepts the full item id or the 8-char prefix returned by
    analyze-similarities.
    """
    try:
        return resolve_similarity_pair(dataset_name, body.remove_id)
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AmbiguousRecordError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error in resolve_pair endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/dataset/{dataset_name}",
    response_model=DeleteDatasetResponse,
    # Destructive (drops the dataset's items + Qdrant collection) — admin only.
    dependencies=[Depends(require_admin)],
)
async def delete_dataset(dataset_name: str):
    """Delete a dataset's Q/A items from Langfuse and drop its Qdrant collection.

    Langfuse has no delete-dataset API, so the empty dataset shell remains.
    """
    try:
        return delete_dataset_view(dataset_name)
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error deleting dataset {dataset_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
