from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session

import logging
from typing import Optional

from server.models.dataset import Dataset, QASource
from server.core.database import get_db
from server.services.dataset_reads import get_qa_view
from server.services.langfuse import LangfuseUnavailableError
from server.schemas.q_a import QAListResponse, QAResponse

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


@router.get("/id/{qa_id}", response_model=QAResponse)
async def get_qa_by_id(qa_id: str, db: Session = Depends(get_db)) -> QAResponse:
    """Retrieve a specific Q&A item by its ID"""
    try:
        qa_record = db.query(QASource).filter(QASource.id == qa_id).first()

        if not qa_record:
            raise HTTPException(
                status_code=404, detail=f"Q&A with ID '{qa_id}' not found"
            )

        # Retrieve the associated dataset information
        dataset = db.query(Dataset).filter(Dataset.id == qa_record.dataset_id).first()

        return QAResponse(
            id=qa_record.id,
            question=qa_record.input.get("question", ""),
            answer=qa_record.expected_output.get("answer", ""),
            context=qa_record.input.get("context", ""),
            source_url=qa_record.input.get("source_url", ""),
            confidence=qa_record.expected_output.get("confidence", 0.0),
            created_at=qa_record.created_at,
            updated_at=qa_record.updated_at,
            metadata=qa_record.qa_metadata,
            dataset={
                "id": dataset.id if dataset else None,
                "name": dataset.name if dataset else None,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error fetching Q&A '{qa_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
