"""Your resumes on Reactive Resume (services/reactive_resume.py), and the Q&A
dataset each can be generated into (jobs/resume_qa.py).

Admins only: the API key is a server secret of the operator's own account, so
no user reads through it. ``async def``: the client is asynchronous.

A resume's dataset settings — the Hugging Face repo, the language, the model
and the preset that regenerates it by itself — are one job schedule per
resume (services/schedules.py). A run you start here stops at a draft to
review (``/drafts``); a scheduled one publishes what passes the checks and
keeps the rest for review.
"""

import logging
from typing import Any, Awaitable, Callable, Dict

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server.api.deps import get_credentials
from server.api.errors import internal_error
from server.core.database import get_db
from server.jobs.resume_qa import RESUME_JOB_ID
from server.models.user import User
from server.schemas.jobs import JobRunOut
from server.schemas.resumes import (
    ResumeDatasetIn,
    ResumeDatasetOut,
    ResumeOut,
    ResumeRunRequest,
    ResumesOut,
)
from server.services import reactive_resume as rr
from server.services import schedules
from server.services.auth import require_admin
from server.services.credentials import Credentials
from server.services.jobs import QuotaExceededError, RunConflictError, start_run
from server.services.providers import validate_ref

router = APIRouter(
    prefix="/resumes", tags=["resumes"], dependencies=[Depends(require_admin)]
)
logger = logging.getLogger(__name__)

_RESUME_ID = Path(..., max_length=64, description="Its id, from GET /resumes")


async def _call(fn: Callable[[], Awaitable[Any]], what: str) -> Any:
    """Run a read, mapping its errors to HTTP answers. The messages say what to
    fix (a variable, the key's rights) and never carry the key."""
    try:
        return await fn()
    except rr.ResumeNotConfiguredError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except rr.ResumeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except rr.ResumeUnavailableError as e:
        logger.warning("Reactive Resume: reading %s failed: %s", what, e)
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception:
        raise internal_error(f"Reading {what}", 502) from None


@router.get("", response_model=ResumesOut, summary="Your resumes")
async def get_resumes():
    """Every resume the server's Reactive Resume key can read, newest change first."""
    return await _call(rr.list_resumes, "your resumes")


@router.get("/{resume_id}", response_model=ResumeOut, summary="One resume, as text")
async def get_resume(resume_id: str = _RESUME_ID):
    """Its basics, summary and visible sections, the rich text as plain text."""
    return await _call(lambda: rr.get_resume(resume_id), "the resume")


# --- its dataset ----------------------------------------------------------------


def _dataset(schedule: Dict[str, Any]) -> Dict[str, Any]:
    options = schedule["options"]
    return {
        "resume_id": schedule["scope"],
        "title": options.get("title") or "",
        "target_repo": options["target_repo"],
        "language": options.get("language") or "auto",
        "model_ref": schedule["model_ref"],
        "every": schedule["every"],
        "at_hour": schedule["at_hour"],
        "at_minute": schedule["at_minute"],
        "publish": schedule["publish"],
        "next_run_at": schedule["next_run_at"],
        "latest_run": schedule["last_run"],
        "updated_at": schedule["updated_at"],
    }


def _not_saved(resume_id: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail=f"No dataset settings for resume '{resume_id}' yet"
    )


@router.get(
    "/{resume_id}/dataset",
    response_model=ResumeDatasetOut,
    summary="The resume's dataset settings",
)
def get_resume_dataset(
    resume_id: str = _RESUME_ID,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Where the resume's Q&A dataset publishes, its language, model and
    preset, with the next and the latest run. 404 until saved."""
    try:
        return _dataset(schedules.get_schedule(db, user.id, RESUME_JOB_ID, resume_id))
    except schedules.ScheduleNotFoundError:
        raise _not_saved(resume_id) from None


@router.put(
    "/{resume_id}/dataset",
    response_model=ResumeDatasetOut,
    summary="Save the resume's dataset settings",
)
async def put_resume_dataset(
    body: ResumeDatasetIn,
    resume_id: str = _RESUME_ID,
    user: User = Depends(require_admin),
    creds: Credentials = Depends(get_credentials),
    db: Session = Depends(get_db),
):
    """Save them (the resume is read first: it must exist). A preset set or
    moved runs first at its next time, then every day, week or month."""
    resume = await _call(lambda: rr.get_resume(resume_id), "the resume")
    if body.model_ref:
        try:
            validate_ref(body.model_ref, creds)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    options = {
        "resume_id": resume_id,
        "title": resume.get("name") or "",
        "target_repo": body.target_repo,
        "language": body.language,
    }
    try:
        saved = await run_in_threadpool(
            schedules.upsert_schedule,
            db,
            user.id,
            RESUME_JOB_ID,
            resume_id,
            options=options,
            model_ref=body.model_ref,
            every=body.every,
            at_hour=body.at_hour,
            at_minute=body.at_minute,
            publish=body.publish,
        )
    except schedules.ScheduleInputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _dataset(saved)


@router.delete(
    "/{resume_id}/dataset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Forget the resume's dataset settings",
)
def delete_resume_dataset(
    resume_id: str = _RESUME_ID,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """The schedule stops; the dataset on Hugging Face stays."""
    try:
        schedules.delete_schedule(db, user.id, RESUME_JOB_ID, resume_id)
    except schedules.ScheduleNotFoundError:
        raise _not_saved(resume_id) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{resume_id}/dataset/run",
    response_model=JobRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a draft from the resume",
)
async def run_resume_dataset(
    body: ResumeRunRequest,
    resume_id: str = _RESUME_ID,
    user: User = Depends(require_admin),
    creds: Credentials = Depends(get_credentials),
    db: Session = Depends(get_db),
):
    """Queue a generation with the saved settings (a worker runs it): poll
    GET /jobs/runs/{id}, review the draft, then POST /jobs/runs/{id}/publish."""
    try:
        saved = await run_in_threadpool(
            schedules.get_schedule, db, user.id, RESUME_JOB_ID, resume_id
        )
    except schedules.ScheduleNotFoundError:
        raise _not_saved(resume_id) from None
    options = {**saved["options"], "full_refresh": body.full_refresh, "publish": False}
    try:
        run = await start_run(
            user.id, creds, RESUME_JOB_ID, options, saved["model_ref"]
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_url=False)) from e
    except RunConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    # An unusable model reference. After ValidationError, which subclasses it.
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await run_in_threadpool(
        schedules.record_run, db, user.id, RESUME_JOB_ID, resume_id, run["id"]
    )
    return JobRunOut(**run)
