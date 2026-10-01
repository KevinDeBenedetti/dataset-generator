from fastapi import APIRouter, Depends, HTTPException, Query

import logging
from typing import Optional

from server.models.user import User
from server.api.deps import get_credentials
from server.services.auth import get_current_user
from server.services.credentials import Credentials
from server.services.providers import validate_ref
from server.services.datasets import get_qa_stats_view, get_qa_view
from server.services.scoring import ScoringNotConfiguredError, score_dataset
from server.schemas.q_a import QAListResponse, QAScoreResponse, QAStatsResponse

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
    user: User = Depends(get_current_user),
) -> QAStatsResponse:
    """Aggregated confidence-score stats over the whole dataset (server-side).

    Avoids the client having to page through /q_a/{dataset_name} to compute
    averages and distributions — accurate even on large datasets.
    """
    try:
        return QAStatsResponse(
            **get_qa_stats_view(user.id, dataset_name, score_threshold=score_threshold)
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error computing Q&A stats for '{dataset_name}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{dataset_name}/score",
    response_model=QAScoreResponse,
    # Spends tokens on the caller's own model account.
)
async def score_qa(
    dataset_name: str,
    only_unscored: bool = Query(
        True, description="Score only pairs without a confidence (false: rescore all)"
    ),
    model: Optional[str] = Query(
        None, description="Judge model reference (defaults to your qa model)"
    ),
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> QAScoreResponse:
    """Score a dataset's pairs with an LLM judge and store the confidences.

    For pairs that have no score yet — typically ones imported from the Hub.
    With a context, the judge rates how well it supports the answer (the same
    measure generation reports); without one, the pair's own quality.
    """
    if model:
        try:
            model = validate_ref(model, creds)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    try:
        return QAScoreResponse(
            **await score_dataset(
                user.id,
                dataset_name,
                creds,
                only_unscored=only_unscored,
                model=model,
            )
        )
    except ScoringNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error scoring Q&A for '{dataset_name}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{dataset_name}", response_model=QAListResponse)
async def get_qa_by_dataset(
    dataset_name: str,
    limit: Optional[int] = Query(
        10, ge=1, le=1000, description="Limit number of results"
    ),
    offset: Optional[int] = Query(0, ge=0, description="Pagination offset"),
    user: User = Depends(get_current_user),
) -> QAListResponse:
    """Retrieve a dataset's Q&A pairs (keyed by dataset name)."""
    try:
        return QAListResponse(
            **get_qa_view(user.id, dataset_name, limit=limit, offset=offset or 0)
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error fetching Q&A for dataset '{dataset_name}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
