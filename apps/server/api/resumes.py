"""Your resumes on Reactive Resume (services/reactive_resume.py).

Admins only: the API key is a server secret of the operator's own account, so
no user reads through it. ``async def``: the client is asynchronous.
"""

import logging
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Path

from server.api.errors import internal_error
from server.schemas.resumes import ResumeOut, ResumesOut
from server.services import reactive_resume as rr
from server.services.auth import require_admin

router = APIRouter(
    prefix="/resumes", tags=["resumes"], dependencies=[Depends(require_admin)]
)
logger = logging.getLogger(__name__)


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
async def get_resume(
    resume_id: str = Path(..., max_length=64, description="Its id, from GET /resumes"),
):
    """Its basics, summary and visible sections, the rich text as plain text."""
    return await _call(lambda: rr.get_resume(resume_id), "the resume")
