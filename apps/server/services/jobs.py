"""Trigger the scheduled GitHub → Hugging Face jobs (``server.jobs``) on demand.

The jobs themselves are the same code the ``dataset-sync.yml`` /
``qa-dataset-sync.yml`` GitHub Actions run on a Monday cron — this module just
wires them to an HTTP request so an admin can run one from the dashboard
instead of waiting for the schedule or driving ``gh workflow run``.
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from starlette.concurrency import run_in_threadpool

from server.core.config import _env
from server.jobs import corpus as corpus_job
from server.jobs import qa_dataset as qa_dataset_job

logger = logging.getLogger(__name__)


def _has_claude_credentials() -> bool:
    return bool(_env("CLAUDE_CODE_OAUTH_TOKEN") or _env("ANTHROPIC_API_KEY"))


def jobs_status() -> Dict[str, Any]:
    """Which server-side env vars each job needs are set — booleans only,
    never the values, so this is safe to serve to the dashboard."""
    github_username = bool(_env("GITHUB_USERNAME"))
    github_token = bool(_env("GITHUB_TOKEN"))
    hf_token = bool(_env("HF_TOKEN"))
    hf_dataset_repo = bool(_env("HF_DATASET_REPO"))
    hf_qa_dataset_repo = bool(_env("HF_QA_DATASET_REPO"))
    claude_credentials = _has_claude_credentials()

    return {
        "corpus": {
            "configured": github_username and hf_token and hf_dataset_repo,
            "github_username": github_username,
            "github_token": github_token,
            "hf_token": hf_token,
            "hf_dataset_repo": hf_dataset_repo,
        },
        "qa_dataset": {
            "configured": (
                github_username
                and claude_credentials
                and hf_token
                and hf_qa_dataset_repo
            ),
            "github_username": github_username,
            "github_token": github_token,
            "claude_credentials": claude_credentials,
            "hf_token": hf_token,
            "hf_qa_dataset_repo": hf_qa_dataset_repo,
        },
    }


async def run_corpus_sync(
    sources: Optional[List[str]], dry_run: bool
) -> Dict[str, Any]:
    """Build the requested corpus splits and, unless ``dry_run``, publish them.

    Raises :class:`corpus_job.JobError` for anything the caller can act on:
    an unknown source, missing server configuration, or a truncated/rejected
    export.
    """
    username = _env("GITHUB_USERNAME")
    if not username:
        raise corpus_job.JobError("GITHUB_USERNAME is not configured on the server")

    chosen = sources or list(corpus_job.KNOWN_SOURCES)
    unknown = [s for s in chosen if s not in corpus_job.KNOWN_SOURCES]
    if unknown:
        raise corpus_job.JobError(
            f'unknown source "{unknown[0]}"; known sources: '
            f"{', '.join(corpus_job.KNOWN_SOURCES)}"
        )

    hf_repo = _env("HF_DATASET_REPO")
    token = _env("GITHUB_TOKEN") or None

    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        manifest = await corpus_job.export_corpus(
            directory, chosen, username, token, hf_repo or ""
        )
        if dry_run:
            return {"manifest": manifest, "url": None, "dry_run": True}

        if not hf_repo:
            raise corpus_job.JobError("HF_DATASET_REPO is not configured on the server")
        url = await run_in_threadpool(corpus_job.push_corpus, directory, hf_repo)
        return {"manifest": manifest, "url": url, "dry_run": False}


async def run_qa_dataset_sync(
    max_repos: Optional[int], dry_run: bool
) -> Dict[str, Any]:
    """Generate the Q&A dataset and, unless ``dry_run``, publish it.

    Raises :class:`qa_dataset_job.JobError` for missing server configuration
    or a Hugging Face rejection.
    """
    return await qa_dataset_job.run(max_repos=max_repos, dry_run=dry_run)
