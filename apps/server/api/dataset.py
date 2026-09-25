import logging
from typing import List, Union

from fastapi import APIRouter, Depends, HTTPException, Query

from server.services.auth import require_admin
from server.services.datasets import (
    AmbiguousRecordError,
    list_datasets_view,
    get_dataset_view,
    create_dataset as create_dataset_view,
    delete_dataset as delete_dataset_view,
    duplicate_dataset as duplicate_dataset_view,
    analyze_similarities_view,
    clean_similarities_view,
    get_dataset_sources_view,
    list_dataset_versions,
    resolve_similarity_pair,
)
from server.services.huggingface import (
    HuggingFaceNotConfiguredError,
    HuggingFaceRepoPublicError,
    export_dataset_to_hub,
)
from server.schemas.dataset import (
    DatasetResponse,
    DatasetSourcesResponse,
    DatasetVersionsResponse,
    DuplicateDatasetResponse,
    HuggingFaceExportResponse,
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
    """Create a new (empty) dataset."""
    try:
        return create_dataset_view(name, description)
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
    """Retrieve all datasets, or a specific one (by name)."""
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
    except Exception as e:
        logging.error(f"Error fetching datasets: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dataset/{dataset_name}/sources", response_model=DatasetSourcesResponse)
async def get_dataset_sources(dataset_name: str):
    """List the sources a dataset was built from, with its analysis history."""
    try:
        return get_dataset_sources_view(dataset_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error fetching sources for {dataset_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dataset/{dataset_name}/versions", response_model=DatasetVersionsResponse)
async def get_dataset_versions(dataset_name: str):
    """The dataset's version history (one entry per recorded generation)."""
    try:
        return list_dataset_versions(dataset_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error fetching versions for {dataset_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/dataset/{dataset_name}/export/huggingface",
    response_model=HuggingFaceExportResponse,
    # Publishing outside the app — admin only, like the destructive routes.
    dependencies=[Depends(require_admin)],
)
async def export_to_huggingface(
    dataset_name: str,
    repo_id: str = Query(
        None,
        description="Target repo as 'namespace/name' (defaults to the "
        "configured namespace and the dataset's slug)",
    ),
):
    """Export a dataset to the Hugging Face Hub as a **private** dataset repo."""
    try:
        return export_dataset_to_hub(dataset_name, repo_id)
    except HuggingFaceNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HuggingFaceRepoPublicError as e:
        # The dataset would become public — refuse, and say how to proceed.
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error exporting {dataset_name} to Hugging Face: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Hugging Face export failed: {e}")


@router.post(
    "/dataset/{dataset_name}/duplicate", response_model=DuplicateDatasetResponse
)
async def duplicate_dataset(
    dataset_name: str,
    target_name: str = Query(
        None, description="Name of the copy (defaults to '<name>-copy')"
    ),
):
    """Copy a dataset's Q/A pairs into another dataset."""
    try:
        return duplicate_dataset_view(dataset_name, target_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error duplicating dataset {dataset_name}: {str(e)}")
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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error in analyze_similarities endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/dataset/{dataset_name}/clean-similarities",
    response_model=CleanSimilarityResponse,
    # Destructive (deletes stored pairs) — admin only.
    dependencies=[Depends(require_admin)],
)
async def clean_similarities(
    dataset_name: str,
    threshold: float = Query(
        0.8, description="Similarity threshold to detect duplicates (0.0-1.0)"
    ),
):
    """Remove near-duplicate questions from a dataset (deletes stored pairs)."""
    try:
        return clean_similarities_view(dataset_name, threshold)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error in clean_similarities endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/dataset/{dataset_name}/resolve-pair",
    response_model=ResolvePairResponse,
    # Destructive (deletes one stored pair) — admin only, like clean.
    dependencies=[Depends(require_admin)],
)
async def resolve_pair(dataset_name: str, body: ResolvePairRequest):
    """Arbitrate a single duplicate pair: delete the given record, keep the other.

    Accepts the full item id or the 8-char prefix returned by
    analyze-similarities.
    """
    try:
        return resolve_similarity_pair(dataset_name, body.remove_id)
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
    # Destructive (drops the dataset, its pairs + Qdrant collection) — admin only.
    dependencies=[Depends(require_admin)],
)
async def delete_dataset(dataset_name: str):
    """Delete a dataset, its Q/A pairs and its Qdrant collection."""
    try:
        return delete_dataset_view(dataset_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error deleting dataset {dataset_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
