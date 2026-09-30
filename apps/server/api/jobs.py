import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from server.jobs.registry import JOB_ERRORS
from server.schemas.jobs import JobRunOut, JobRunRequest, JobsResponse, PublishRequest
from server.services.auth import require_admin
from server.services.jobs import (
    RunConflictError,
    UnknownJobError,
    UnknownRunError,
    get_run,
    list_jobs,
    publish_run,
    start_run,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


@router.get("", response_model=JobsResponse)
async def get_jobs() -> JobsResponse:
    """The dataset job catalogue, with each job's options, status and latest run."""
    return JobsResponse(jobs=list_jobs())


@router.post(
    "/{job_id}/run",
    response_model=JobRunOut,
    status_code=202,
    # Publishes outside the app and may spend model quota — admin only.
    dependencies=[Depends(require_admin)],
)
async def post_job_run(job_id: str, body: JobRunRequest) -> JobRunOut:
    """Start a run in the background — poll GET /jobs/runs/{id} for its state.

    The same code the job's workflow runs on a schedule. A draft job
    (github-personal) stops at a draft: review it, then POST .../publish.
    """
    try:
        return JobRunOut(**await start_run(job_id, body.options, body.model_ref))
    except UnknownJobError:
        raise HTTPException(status_code=404, detail=f"Unknown job '{job_id}'")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_url=False))
    except RunConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    # An unusable model reference. After ValidationError, which subclasses it.
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/runs/{run_id}", response_model=JobRunOut)
async def get_job_run(run_id: str) -> JobRunOut:
    """A run's state: live progress while running, then its result and draft."""
    try:
        return JobRunOut(**get_run(run_id))
    except UnknownRunError:
        raise HTTPException(status_code=404, detail=f"Unknown run '{run_id}'")


@router.post(
    "/runs/{run_id}/publish",
    response_model=JobRunOut,
    dependencies=[Depends(require_admin)],
)
async def post_publish_run(run_id: str, body: PublishRequest) -> JobRunOut:
    """Publish a run's reviewed draft to Hugging Face, as reviewed."""
    try:
        return JobRunOut(**await publish_run(run_id, body.exclude, body.promote))
    except UnknownRunError:
        raise HTTPException(status_code=404, detail=f"Unknown run '{run_id}'")
    except RunConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except JOB_ERRORS as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Publishing run %s failed", run_id)
        raise HTTPException(status_code=502, detail=f"Publishing failed: {e}")
