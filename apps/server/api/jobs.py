import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from server.api.errors import internal_error
from server.jobs.registry import JOB_ERRORS, JOBS
from server.schemas.jobs import (
    DraftChecks,
    DraftsOut,
    JobRunOut,
    JobRunRequest,
    JobsResponse,
    PublishRequest,
)
from server.models.user import User
from server.api.deps import get_credentials
from server.services.auth import get_current_user
from server.services.credentials import Credentials
from server.services.jobs import (
    QuotaExceededError,
    RunConflictError,
    UnknownJobError,
    UnknownRunError,
    cancel_run,
    get_run,
    list_jobs,
    publish_run,
    start_run,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


@router.get("", response_model=JobsResponse)
def get_jobs(
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> JobsResponse:
    """The dataset job catalogue, with each job's options, status and latest run."""
    return JobsResponse(jobs=list_jobs(user.id, creds))


@router.post(
    "/{job_id}/run",
    response_model=JobRunOut,
    status_code=202,
)
async def post_job_run(
    job_id: str,
    body: JobRunRequest,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> JobRunOut:
    """Queue a run (a worker executes it) — poll GET /jobs/runs/{id} for its state.

    A draft job (github-personal) stops at a draft: review it, then
    POST .../publish.
    """
    spec = JOBS.get(job_id)
    if spec is not None and not spec.listed:
        # Started from its own page (a recipe runs from POST /recipes/{id}/run).
        raise HTTPException(status_code=404, detail=f"Unknown job '{job_id}'")
    try:
        return JobRunOut(
            **await start_run(user.id, creds, job_id, body.options, body.model_ref)
        )
    except UnknownJobError:
        raise HTTPException(status_code=404, detail=f"Unknown job '{job_id}'") from None
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_url=False)) from e
    except RunConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    # An unusable model reference. After ValidationError, which subclasses it.
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/drafts", response_model=DraftsOut)
def get_drafts(user: User = Depends(get_current_user)) -> DraftsOut:
    """Your drafts waiting for a review (file, web page and recipe runs)."""
    from server.services.drafts import list_drafts

    return DraftsOut(drafts=list_drafts(user.id))


@router.get("/runs/{run_id}", response_model=JobRunOut)
def get_job_run(run_id: str, user: User = Depends(get_current_user)) -> JobRunOut:
    """A run's state: live progress while running, then its result and draft."""
    try:
        return JobRunOut(**get_run(user.id, run_id))
    except UnknownRunError:
        raise HTTPException(status_code=404, detail=f"Unknown run '{run_id}'") from None


@router.get("/runs/{run_id}/checks", response_model=DraftChecks)
def get_draft_checks(
    run_id: str,
    threshold: float = Query(0.85, ge=0.5, le=1.0),
    user: User = Depends(get_current_user),
) -> DraftChecks:
    """Near-duplicate pairs and quality-rule failures of a draft, for its review."""
    from server.services.draft_quality import check_draft

    try:
        return DraftChecks(**check_draft(user.id, run_id, threshold))
    except UnknownRunError:
        raise HTTPException(status_code=404, detail=f"Unknown run '{run_id}'") from None
    except RunConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post(
    "/runs/{run_id}/publish",
    response_model=JobRunOut,
)
async def post_publish_run(
    run_id: str,
    body: PublishRequest,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> JobRunOut:
    """Publish a run's reviewed draft to Hugging Face, as reviewed."""
    try:
        return JobRunOut(
            **await publish_run(
                user.id,
                creds,
                run_id,
                body.exclude,
                body.promote,
                edits={k: v.model_dump() for k, v in body.edits.items()},
            )
        )
    except UnknownRunError:
        raise HTTPException(status_code=404, detail=f"Unknown run '{run_id}'") from None
    except RunConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except JOB_ERRORS as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        raise internal_error("Publishing to Hugging Face", 502) from None


@router.post("/runs/{run_id}/cancel", response_model=JobRunOut)
def post_cancel_run(run_id: str, user: User = Depends(get_current_user)) -> JobRunOut:
    """Cancel a queued run, or ask the worker to stop a running one."""
    try:
        return JobRunOut(**cancel_run(user.id, run_id))
    except UnknownRunError:
        raise HTTPException(status_code=404, detail=f"Unknown run '{run_id}'") from None
    except RunConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
