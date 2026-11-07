"""Browse your public GitHub data (services/github_browse.py).

Scoped to the GitHub username saved in Settings; read with the caller's own
token when they saved one (it only raises the rate limit). ``async def``:
the GitHub client is asynchronous.
"""

import logging
from typing import Awaitable, Callable, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from server.api.deps import get_credentials
from server.schemas.github import (
    GitHubDocContent,
    GitHubProfileOut,
    GitHubRepoDetail,
    GitHubReposOut,
)
from server.services import github_browse as browse
from server.services.credentials import Credentials

router = APIRouter(prefix="/github", tags=["github"])
logger = logging.getLogger(__name__)

T = TypeVar("T")

Owner = Path(..., max_length=39, description="The account the repo belongs to (yours)")
Repo = Path(..., max_length=100, description="Repository name")


async def _call(fn: Callable[[], Awaitable[T]], what: str) -> T:
    """Run a browse call, mapping its errors to HTTP answers (5xx generic)."""
    try:
        return await fn()
    except browse.GitHubNotConfiguredError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except browse.GitHubNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except browse.GitHubRateLimitError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except browse.GitHubUnavailableError:
        logger.exception("GitHub browse: %s failed", what)
        raise HTTPException(
            status_code=502, detail="GitHub didn't answer. Try again shortly."
        ) from None
    except Exception:
        logger.exception("GitHub browse: %s failed", what)
        raise HTTPException(status_code=502, detail=f"Reading {what} failed") from None


@router.get("/profile", response_model=GitHubProfileOut, summary="Your GitHub account")
async def get_github_profile(creds: Credentials = Depends(get_credentials)):
    """Your public profile and what is left of the API quota."""
    return await _call(lambda: browse.profile(creds), "your GitHub profile")


@router.get("/repos", response_model=GitHubReposOut, summary="Your public repos")
async def get_github_repos(creds: Credentials = Depends(get_credentials)):
    """Every public repo of your account, most recently updated first, with
    whether a generation would take it (not a fork, not archived)."""
    return await _call(lambda: browse.list_repos(creds), "your GitHub repos")


@router.get(
    "/repos/{owner}/{repo}",
    response_model=GitHubRepoDetail,
    summary="A repo as a generation sees it",
)
async def get_github_repo(
    owner: str = Owner,
    repo: str = Repo,
    creds: Credentials = Depends(get_credentials),
):
    """The README cleaned and cut as the model sees it, the ``docs/`` files, the
    detected stack and the exact overview text sent to the model."""
    return await _call(
        lambda: browse.repo_detail(creds, owner, repo), f"{owner}/{repo}"
    )


@router.get(
    "/repos/{owner}/{repo}/doc",
    response_model=GitHubDocContent,
    summary="A docs/ file as the model reads it",
)
async def get_github_doc(
    owner: str = Owner,
    repo: str = Repo,
    path: str = Query(
        ..., max_length=browse.MAX_DOC_PATH_CHARS, description="Path under docs/"
    ),
    creds: Credentials = Depends(get_credentials),
):
    """One Markdown or text file under ``docs/``, cut where a generation cuts it."""
    return await _call(
        lambda: browse.doc_content(creds, owner, repo, path), f"{owner}/{repo}/{path}"
    )
