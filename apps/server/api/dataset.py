from typing import List, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from server.api.errors import internal_error
from server.models.user import User
from server.api.deps import get_credentials
from server.services.auth import get_current_user
from server.services.credentials import Credentials
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
    HuggingFaceImportTooLargeError,
    HuggingFaceNotConfiguredError,
    HuggingFaceRepoPublicError,
    export_dataset_to_hub,
    import_dataset_from_hub,
)
from server.schemas.dataset import (
    DatasetResponse,
    DatasetSourcesResponse,
    DatasetVersionsResponse,
    DuplicateDatasetResponse,
    HuggingFaceExportResponse,
    HuggingFaceImportResponse,
    SimilarityAnalysisResponse,
    CleanSimilarityResponse,
    DeleteDatasetResponse,
    ResolvePairRequest,
    ResolvePairResponse,
)

router = APIRouter(
    tags=["dataset"],
)

# Plain ``def`` routes unless they await: the dataset services block (Postgres,
# similarity passes over every pair, Hub uploads), so FastAPI runs them in its
# threadpool instead of stalling the event loop for every other request.


@router.post("/dataset", response_model=DatasetResponse)
def create_dataset(
    name: str = Query(..., description="Name of the new dataset"),
    description: str = Query(None, description="Optional dataset description"),
    user: User = Depends(get_current_user),
):
    """Create a new (empty) dataset of yours."""
    try:
        return create_dataset_view(user.id, name, description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        raise internal_error("Creating the dataset") from None


@router.get("/dataset", response_model=Union[DatasetResponse, List[DatasetResponse]])
def get_all_datasets(
    dataset_id: str = Query(
        None,
        description="Optional dataset name to get a specific dataset's details",
    ),
    user: User = Depends(get_current_user),
):
    """Retrieve all your datasets, or a specific one (by name)."""
    try:
        if dataset_id:
            dataset = get_dataset_view(user.id, dataset_id)
            if not dataset:
                raise HTTPException(
                    status_code=404, detail=f"Dataset '{dataset_id}' not found"
                )
            return dataset
        return list_datasets_view(user.id)
    except HTTPException:
        raise
    except Exception:
        raise internal_error("Listing your datasets") from None


@router.get("/dataset/{dataset_name}/sources", response_model=DatasetSourcesResponse)
def get_dataset_sources(dataset_name: str, user: User = Depends(get_current_user)):
    """List the sources a dataset was built from, with its analysis history."""
    try:
        return get_dataset_sources_view(user.id, dataset_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        raise internal_error(f"Reading the sources of {dataset_name}") from None


@router.get("/dataset/{dataset_name}/versions", response_model=DatasetVersionsResponse)
def get_dataset_versions(dataset_name: str, user: User = Depends(get_current_user)):
    """The dataset's version history (one entry per recorded generation)."""
    try:
        return list_dataset_versions(user.id, dataset_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        raise internal_error(f"Reading the versions of {dataset_name}") from None


@router.post(
    "/dataset/huggingface/import",
    response_model=HuggingFaceImportResponse,
)
async def import_huggingface_dataset(
    repo_id: str = Query(
        ..., description="Full 'namespace/name' Hub repo id to import"
    ),
    dataset_name: str = Query(
        None,
        description="Local dataset name to import into (defaults to the repo's name segment)",
    ),
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
):
    """Pull a Hugging Face dataset repo's Q/A pairs into a local dataset, so it
    can be analyzed like any other dataset (duplicates, score stats, rules)."""
    try:
        # Same reasoning as the listing route: this does blocking downloads,
        # synchronous parsing over every row, and a blocking DB write, with no
        # size cap — keep it off the event loop thread.
        return await run_in_threadpool(
            import_dataset_from_hub, user.id, creds, repo_id, dataset_name
        )
    except HuggingFaceNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except HuggingFaceImportTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        raise internal_error(f"Importing {repo_id} from Hugging Face", 502) from None


@router.post(
    "/dataset/{dataset_name}/export/huggingface",
    response_model=HuggingFaceExportResponse,
)
def export_to_huggingface(
    dataset_name: str,
    repo_id: str = Query(
        None,
        description="Target repo as 'namespace/name' (defaults to the "
        "configured namespace and the dataset's slug)",
    ),
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
):
    """Export one of your datasets to the Hugging Face Hub as a **private** repo."""
    try:
        return export_dataset_to_hub(user.id, creds, dataset_name, repo_id)
    except HuggingFaceNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except HuggingFaceRepoPublicError as e:
        # The dataset would become public — refuse, and say how to proceed.
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        raise internal_error(
            f"Publishing {dataset_name} to Hugging Face", 502
        ) from None


@router.post(
    "/dataset/{dataset_name}/duplicate", response_model=DuplicateDatasetResponse
)
def duplicate_dataset(
    dataset_name: str,
    target_name: str = Query(
        None, description="Name of the copy (defaults to '<name>-copy')"
    ),
    user: User = Depends(get_current_user),
):
    """Copy one of your datasets' Q/A pairs into another dataset of yours."""
    try:
        return duplicate_dataset_view(user.id, dataset_name, target_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        raise internal_error(f"Copying {dataset_name}") from None


@router.get(
    "/dataset/{dataset_name}/analyze-similarities",
    response_model=SimilarityAnalysisResponse,
)
def analyze_similarities(
    dataset_name: str,
    threshold: float = Query(
        0.8,
        ge=0.5,
        le=1.0,
        description="Similarity threshold (0.5-1.0)",
    ),
    user: User = Depends(get_current_user),
):
    """Analyze near-duplicate questions in a dataset (read-only)."""
    try:
        return analyze_similarities_view(user.id, dataset_name, threshold)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        raise internal_error("The duplicate analysis") from None


@router.post(
    "/dataset/{dataset_name}/clean-similarities",
    response_model=CleanSimilarityResponse,
)
def clean_similarities(
    dataset_name: str,
    threshold: float = Query(
        0.8,
        ge=0.5,
        le=1.0,
        # Lower, nearly every pair counts as a duplicate and gets deleted.
        description="Similarity threshold to detect duplicates (0.5-1.0)",
    ),
    user: User = Depends(get_current_user),
):
    """Remove near-duplicate questions from one of your datasets (deletes pairs)."""
    try:
        return clean_similarities_view(user.id, dataset_name, threshold)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        raise internal_error("Cleaning the duplicates") from None


@router.post(
    "/dataset/{dataset_name}/resolve-pair",
    response_model=ResolvePairResponse,
)
def resolve_pair(
    dataset_name: str,
    body: ResolvePairRequest,
    user: User = Depends(get_current_user),
):
    """Arbitrate a single duplicate pair: delete the given record, keep the other.

    Accepts the full item id or the 8-char prefix returned by
    analyze-similarities.
    """
    try:
        return resolve_similarity_pair(user.id, dataset_name, body.remove_id)
    except AmbiguousRecordError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        raise internal_error("Resolving the pair") from None


@router.delete(
    "/dataset/{dataset_name}",
    response_model=DeleteDatasetResponse,
)
def delete_dataset(dataset_name: str, user: User = Depends(get_current_user)):
    """Delete one of your datasets and its Q/A pairs."""
    try:
        return delete_dataset_view(user.id, dataset_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        raise internal_error(f"Deleting {dataset_name}") from None
