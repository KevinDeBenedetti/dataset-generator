from fastapi import APIRouter, HTTPException, Query

import logging
from typing import Optional

from server.services.dataset_reads import get_qa_view
from server.services.langfuse import LangfuseUnavailableError
from server.schemas.q_a import QAListResponse

router = APIRouter(
    prefix="/q_a",
    tags=["q_a"],
)


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
