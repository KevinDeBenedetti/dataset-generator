"""Reviewing a recipe run's tabular draft (services/tabular_review.py).

Owner-scoped: another user's run answers 404, like an unknown one
(tests/api/test_tenant_isolation.py).
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server.api.deps import get_credentials
from server.core.database import get_db
from server.services.credentials import Credentials
from server.models.user import User
from server.services import tabular_review as review
from server.services.auth import get_current_user

router = APIRouter(prefix="/runs", tags=["review"])


class ReviewOut(BaseModel):
    decision: str
    comment: Optional[str] = None
    created_at: Optional[datetime] = None
    status: Optional[str] = None
    published_url: Optional[str] = None


class TabularDraftOut(BaseModel):
    run_id: str
    status: str
    kind: str = "table"
    recipe_id: Optional[str] = None
    data_source_id: Optional[str] = None
    target_repo: Optional[str] = None
    visibility: Optional[str] = None
    provenance: Dict[str, Any]
    rows: int
    source_rows: int
    schema_: List[Dict[str, Any]] = Field(alias="schema")
    profile: Dict[str, Any]
    quality_report: Dict[str, Any]
    blocking: List[Dict[str, Any]]
    step_rows: List[int]
    steps: List[Dict[str, Any]]
    warnings: List[str] = Field(default_factory=list)
    changes: Optional[Dict[str, Any]] = None
    review: Optional[ReviewOut] = None
    published_url: Optional[str] = None
    public_refusal: Optional[str] = Field(
        None, description="Why the draft can't be public (its licence), if so"
    )

    model_config = {"populate_by_name": True}


class DraftRowsOut(BaseModel):
    total: int
    offset: int
    limit: int
    columns: List[str]
    rows: List[Dict[str, Any]]


class ReviewIn(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: Optional[str] = Field(None, max_length=2000)


class RecipeRunOut(BaseModel):
    run_id: str
    status: str
    recipe_id: Optional[str] = None
    recipe_name: Optional[str] = None
    rows: Optional[int] = None
    started_at: Optional[datetime] = None
    error: Optional[str] = None
    published_url: Optional[str] = None
    to_review: bool
    kind: Optional[str] = Field(None, description="table or qa: which review page")


class RecipeRunsOut(BaseModel):
    runs: List[RecipeRunOut]


@router.get("", response_model=RecipeRunsOut, summary="Your recipe runs")
def list_runs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Your 50 latest recipe runs; ``to_review`` marks the drafts that wait."""
    return {"runs": review.list_runs(db, user.id)}


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get(
    "/{run_id}/draft",
    response_model=TabularDraftOut,
    response_model_by_alias=True,
    summary="A tabular draft, to review",
)
def get_draft(
    run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Provenance, schema (with the original names), profile, quality report,
    row counts, the changes against the published version, the last review."""
    try:
        return review.get_draft(db, user.id, run_id)
    except review.DraftNotFound as exc:
        raise _not_found(exc) from exc


@router.get(
    "/{run_id}/draft/rows", response_model=DraftRowsOut, summary="A page of rows"
)
async def get_rows(
    run_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=review.MAX_PAGE),
    sort: Optional[str] = Query(None, max_length=200),
    desc: bool = False,
    filter_column: Optional[str] = Query(None, max_length=200),
    filter_value: Optional[str] = Query(None, max_length=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rows read from the draft's Parquet file (500 at most a page), sorted by
    one column, filtered on one column containing some text."""
    try:
        return await run_in_threadpool(
            review.get_rows,
            db,
            user.id,
            run_id,
            offset=offset,
            limit=limit,
            sort=sort,
            descending=desc,
            filter_column=filter_column,
            filter_value=filter_value,
        )
    except review.DraftNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def hub_backend() -> Any:
    """The Hub publications go to: None is the real one (tests override it)."""
    return None


@router.post("/{run_id}/review", response_model=ReviewOut, summary="Approve or reject")
async def post_review(
    run_id: str,
    body: ReviewIn,
    request: Request,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
    db: Session = Depends(get_db),
    backend: Any = Depends(hub_backend),
):
    """An approval publishes the draft to its Hub dataset repo (one commit:
    Parquet, app card, manifest), then records the review. It is refused (409)
    while a blocking rule of the quality report fails, or for a public draft
    whose licence doesn't allow it; a rejection marks the run rejected."""
    from server.services.hub_repo import (
        DatasetMoved,
        HubRepoError,
        HubTokenMissing,
        HubTokenRejected,
        HubUnavailable,
    )

    ip = request.client.host if request.client else None
    try:
        return await run_in_threadpool(
            review.decide,
            db,
            user,
            run_id,
            body.decision,
            body.comment,
            ip,
            creds=creds,
            backend=backend,
        )
    except review.DraftNotFound as exc:
        raise _not_found(exc) from exc
    except (HubTokenMissing, HubTokenRejected) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HubUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatasetMoved as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HubRepoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except review.ReviewRefused as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "rules": exc.rules} if exc.rules else str(exc),
        ) from exc
