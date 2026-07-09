import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from server.services.dataset_reads import get_dataset_view
from server.services.langfuse import (
    LangfuseUnavailableError,
    create_langfuse_dataset_with_items,
    get_dataset_items,
    normalize_dataset_name,
    list_dataset_runs,
    list_datasets,
    is_langfuse_configured,
)

router = APIRouter(
    prefix="/langfuse",
    tags=["langfuse"],
)


def _get_dataset_or_404(dataset_name: str) -> None:
    """Ensure a dataset exists in Langfuse, or raise a 404 listing what's available."""
    if get_dataset_view(dataset_name) is None:
        available_datasets = [d.get("name") for d in list_datasets()]
        raise HTTPException(
            status_code=404,
            detail=f"Dataset '{dataset_name}' not found. Available datasets: {available_datasets}",
        )


def _active_dataset_items(dataset_name: str) -> list[Dict[str, Any]]:
    """Active (non-archived) items of a Langfuse dataset, in export/preview shape."""
    return [
        {
            "input": item.get("input") or {},
            "id": item["id"],
            **(
                {"expected_output": item["expected_output"]}
                if item.get("expected_output")
                else {}
            ),
            **({"metadata": item["metadata"]} if item.get("metadata") else {}),
        }
        for item in get_dataset_items(dataset_name)
        if (item.get("status") or "ACTIVE") == "ACTIVE"
    ]


@router.get("/preview")
async def preview_dataset_transformation(
    dataset_name: str = Query(..., description="Dataset name in Langfuse"),
):
    """Preview the dataset transformation for Langfuse without sending it"""
    try:
        _get_dataset_or_404(dataset_name)
        data_list = _active_dataset_items(dataset_name)

        if not data_list:
            raise HTTPException(
                status_code=404, detail=f"No QA data found for dataset '{dataset_name}'"
            )

        # Return a preview of the first items
        preview_items = data_list[:3]

        return {
            "sample_items": preview_items,
            "total_items": len(data_list),
            "preview_note": f"Showing {len(preview_items)} items out of {len(data_list)} total",
        }

    except HTTPException:
        raise
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logging.exception("Error during preview")
        raise HTTPException(status_code=500, detail=f"Error during preview: {str(e)}")


@router.get("/datasets")
async def list_langfuse_datasets():
    """List every dataset present in Langfuse (newest first).

    Powers the /datasets page so it reflects what actually lives in Langfuse,
    rather than only the local database.
    """
    if not is_langfuse_configured():
        raise HTTPException(status_code=503, detail="Langfuse is not configured")
    try:
        datasets = list_datasets()
    except Exception as e:
        logging.exception("Error listing Langfuse datasets")
        raise HTTPException(
            status_code=502, detail=f"Could not fetch datasets from Langfuse: {e}"
        )
    return {"total": len(datasets), "datasets": datasets}


@router.get("/versions/{dataset}")
async def list_dataset_versions(dataset: str):
    """List the version/run history (newest first) of a dataset in Langfuse.

    Each generation records a versioned run (``v1``, ``v2``, …). This exposes
    that DVC-like history so the UI can show how a dataset evolved.
    """
    if not is_langfuse_configured():
        raise HTTPException(status_code=503, detail="Langfuse is not configured")
    try:
        versions = list_dataset_runs(dataset)
    except Exception as e:
        logging.exception("Error listing Langfuse dataset versions")
        raise HTTPException(
            status_code=502, detail=f"Could not fetch versions from Langfuse: {e}"
        )
    return {"dataset_name": dataset, "total": len(versions), "versions": versions}


@router.post("/export")
async def export_dataset(
    dataset_name: str = Query(..., description="Dataset name in Langfuse"),
    langfuse_dataset_name: Optional[str] = Query(
        None, description="Custom name for the dataset in Langfuse"
    ),
):
    """Duplicate a Langfuse dataset's items into a new (or renamed) Langfuse dataset."""
    if not is_langfuse_configured():
        raise HTTPException(
            status_code=503,
            detail="Langfuse is not configured. Set LANGFUSE_SECRET_KEY, "
            "LANGFUSE_PUBLIC_KEY and LANGFUSE_HOST (or LANGFUSE_BASE_URL) "
            "in your .env.",
        )
    try:
        # Verify that the dataset exists
        _get_dataset_or_404(dataset_name)

        # Retrieve its QA pairs from Langfuse
        data_list = _active_dataset_items(dataset_name)

        if not data_list:
            raise HTTPException(
                status_code=404, detail=f"No QA data found for dataset '{dataset_name}'"
            )

        # Resolve dataset name for Langfuse
        langfuse_name = (
            langfuse_dataset_name
            if langfuse_dataset_name
            else normalize_dataset_name(dataset_name)
        )

        # Create the dataset in Langfuse with the data
        dataset_config = {
            "name": langfuse_name,
            "description": f"Dataset {langfuse_name} exported from the application",
        }
        result = create_langfuse_dataset_with_items(dataset_config, data_list)

        logging.info(
            f"Dataset {dataset_name} successfully exported to Langfuse as {langfuse_name}"
        )

        return {
            "message": "Dataset exported successfully",
            "dataset_name": dataset_name,
            "langfuse_dataset_name": langfuse_name,
            **result,
        }

    except HTTPException:
        raise
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logging.exception("Error exporting to Langfuse")
        raise HTTPException(
            status_code=500, detail=f"Error exporting to Langfuse: {str(e)}"
        )
