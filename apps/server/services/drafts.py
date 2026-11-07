"""Drafts of file and URL generations: reviewed, then published to the Hub.

A generation from an uploaded file or a web page runs in the request, as it
always did; with a target Hugging Face dataset, its pairs are kept as a
*draft run* (a ``job_runs`` row, like a recipe's draft) instead of a local
dataset. The same review page lists it, and publishing merges the reviewed
pairs into the dataset's ``data/train.jsonl`` (services/huggingface.py).

The run is inserted finished (``succeeded``): there is nothing for a worker
to do, so the one-active-run-per-job rule never applies to it.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from server.core.database import get_scoped_db
from server.models.job_run import JobRun
from server.services.credentials import Credentials

logger = logging.getLogger(__name__)

# The job kind of these drafts (jobs/registry.py), off the Jobs page.
GENERATION_JOB_ID = "generation-draft"
# What GET /jobs/drafts lists: the drafts still waiting for a review.
DRAFT_JOBS = (GENERATION_JOB_ID, "github-recipe")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record(item: Dict[str, Any], kind: str, created_at: str) -> Dict[str, Any]:
    """A pipeline item as published, plus what the review page filters on."""
    return {
        "id": item.get("id"),
        "question": item.get("question", ""),
        "answer": item.get("answer", ""),
        "context": item.get("context", ""),
        "source_url": item.get("source_url"),
        "confidence": item.get("confidence"),
        "created_at": created_at,
        "category": kind,
    }


def create_generation_draft(
    owner_id: str,
    creds: Credentials,
    target_repo: str,
    items: List[Dict[str, Any]],
    *,
    title: str,
    source: str,
    kind: str,
    language: Optional[str],
    model_ref: Optional[str],
) -> str:
    """Store a generation's pairs as a draft run; returns the run id.

    The target repo is completed with the caller's namespace, and its current
    size read, so the review shows what publishing would add to. Raises
    ``HuggingFaceNotConfiguredError`` without a Hugging Face token.
    """
    from server.services.huggingface import existing_pairs, qualify_repo_id

    repo_id = qualify_repo_id(creds, target_repo)
    try:
        kept = len(existing_pairs(creds, repo_id))
    except Exception as exc:  # noqa: BLE001 — a count only: the draft still stands
        logger.warning("Could not count the pairs of %s: %s", repo_id, exc)
        kept = 0
    created_at = _now().isoformat()
    pairs = [_record(i, kind, created_at) for i in items if i.get("id")]
    with get_scoped_db() as db:
        row = JobRun(
            owner_id=owner_id,
            job_id=GENERATION_JOB_ID,
            status="succeeded",
            options={"title": title, "target_repo": repo_id, "source": source},
            model_ref=model_ref,
            finished_at=_now(),
            result={
                "dry_run": True,
                "url": None,
                "metrics": [["New", len(pairs)], ["In the dataset", kept]],
                "errors": [],
            },
            draft={
                "repo_id": repo_id,
                "title": title,
                "source": source,
                "language": language,
                "kept": kept,
                "pairs": pairs,
            },
        )
        db.add(row)
        db.commit()
        return row.id


def list_drafts(owner_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """The caller's drafts waiting for a review, newest first."""
    with get_scoped_db() as db:
        rows = db.scalars(
            select(JobRun)
            .where(
                JobRun.owner_id == owner_id,
                JobRun.job_id.in_(DRAFT_JOBS),
                JobRun.status == "succeeded",
                JobRun.draft.is_not(None),
            )
            .order_by(JobRun.started_at.desc())
            .limit(limit)
        )
        out = []
        for row in rows:
            options = row.options or {}
            recipe = options.get("recipe")
            recipe_name = recipe.get("name") if isinstance(recipe, dict) else None
            draft = row.draft or {}
            out.append(
                {
                    "id": row.id,
                    "job": row.job_id,
                    "title": options.get("title") or recipe_name or row.job_id,
                    "target_repo": draft.get("repo_id") or options.get("target_repo"),
                    "created_at": row.started_at,
                    "new": len(
                        draft.get("pairs") or []
                        if row.job_id == GENERATION_JOB_ID
                        else (draft.get("dataset") or {}).get("new_ids") or []
                    ),
                }
            )
        return out
