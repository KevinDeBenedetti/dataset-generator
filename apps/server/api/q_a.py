from fastapi import APIRouter, HTTPException, Query

import logging
from typing import Optional

from server.services.dataset_reads import get_qa_stats_view, get_qa_view
from server.services.langfuse import LangfuseUnavailableError
from server.schemas.q_a import QAListResponse, QAStatsResponse

router = APIRouter(
    prefix="/q_a",
    tags=["q_a"],
)


@router.get("/{dataset_name}/stats", response_model=QAStatsResponse)
async def get_qa_stats(
    dataset_name: str,
    score_threshold: float = Query(
        0.8, ge=0.0, le=1.0, description="Validated/below split threshold"
    ),
) -> QAStatsResponse:
    """Aggregated confidence-score stats over the whole dataset (server-side).

    Avoids the client having to page through /q_a/{dataset_name} to compute
    averages and distributions — accurate even on large datasets.
    """
    try:
        return QAStatsResponse(
            **get_qa_stats_view(dataset_name, score_threshold=score_threshold)
        )
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error computing Q&A stats for '{dataset_name}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{dataset_name}", response_model=QAListResponse)
async def get_qa_by_dataset(
    dataset_name: str,
    limit: Optional[int] = Query(
        10, ge=1, le=1000, description="Limit number of results"
    ),
    offset: Optional[int] = Query(0, ge=0, description="Pagination offset"),
) -> QAListResponse:
    """Retrieve a dataset's Q&A items from Langfuse (keyed by dataset name)."""
    try:
        return QAListResponse(
            **get_qa_view(dataset_name, limit=limit, offset=offset or 0)
        )
    except LangfuseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error fetching Q&A for dataset '{dataset_name}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
