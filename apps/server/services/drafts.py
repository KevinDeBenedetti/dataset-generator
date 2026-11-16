"""Drafts of file and URL generations: reviewed, then published to the Hub.

A generation from an uploaded file or a web page runs in the request, as it
always did; with a target Hugging Face dataset, its pairs are kept as a
*draft run* (a ``job_runs`` row, like a recipe's draft) instead of a local
dataset. The same review page lists it, and publishing merges the reviewed
pairs into the dataset's rows, wherever its repo keeps them
(:func:`publish_generation_draft`, through services/hub_repo.py).

The run is inserted finished (``succeeded``): there is nothing for a worker
to do, so the one-active-run-per-job rule never applies to it.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select

from server.core.database import get_scoped_db
from server.models.job_run import JobRun
from server.services.credentials import Credentials
from server.services.hub_repo import (
    DatasetMoved,
    HubRepoError,
    HubTokenRejected,
    open_repo,
)

logger = logging.getLogger(__name__)

# The job kind of these drafts (jobs/registry.py), off the Jobs page.
GENERATION_JOB_ID = "generation-draft"
# What GET /jobs/drafts lists: the drafts still waiting for a review.
DRAFT_JOBS = (GENERATION_JOB_ID, "github-recipe", "resume-qa")


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
    size read, so the review shows what publishing would add to. The pairs are
    already paid for: only a missing token (``HubTokenMissing``), or a bare
    repo name no namespace can complete (``HubTokenRejected``), stops the
    draft. Anything else the Hub says is left for the publication to report.
    """
    kept = 0
    try:
        repo = open_repo(creds, target_repo)
    except HubTokenRejected:
        if "/" not in target_repo:
            raise
        repo_id = target_repo.strip()
        logger.warning("Hugging Face refused the token: %s is not counted", repo_id)
    else:
        repo_id = repo.repo_id
        try:
            kept = len(repo.read().rows)
        except HubRepoError as exc:  # a count only: the draft still stands
            logger.warning("Could not count the pairs of %s: %s", repo_id, exc)
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


# The fields of a published pair, in the file's column order. The draft's
# ``category`` (file or web page) is a filter of the review page only.
_PUBLISHED_FIELDS = (
    "id",
    "question",
    "answer",
    "context",
    "source_url",
    "confidence",
    "created_at",
)


def _reviewed_pairs(
    draft: Dict[str, Any], exclude: Sequence[str], edits: Dict[str, Dict[str, str]]
) -> List[Dict[str, Any]]:
    """The draft's pairs as the reviewer left them: left out, rewritten."""
    left_out = set(exclude)
    pairs: List[Dict[str, Any]] = []
    for pair in draft.get("pairs") or []:
        if not isinstance(pair, dict) or pair.get("id") in left_out:
            continue
        published = {name: pair.get(name) for name in _PUBLISHED_FIELDS}
        change = edits.get(str(pair.get("id")))
        if change:
            published["question"] = change["question"].strip()
            published["answer"] = change["answer"].strip()
        pairs.append(published)
    return pairs


def _merged(
    rows: Sequence[Dict[str, Any]], new: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """``rows`` as they are, a row replaced where a new pair has its id, the
    other new pairs after them."""
    by_id = {str(pair["id"]): pair for pair in new}
    merged = [by_id.pop(str(row["id"]), row) if row.get("id") else row for row in rows]
    return merged + list(by_id.values())


def publish_generation_draft(
    creds: Credentials,
    draft: Dict[str, Any],
    exclude: Sequence[str],
    edits: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    """Merge a reviewed file or web page draft into its dataset, in one commit.

    The dataset is read as it is now — it may have changed since the draft was
    made — and every row it holds stays as stored; a draft pair replaces the
    row with its id and joins the others. If the dataset moves again between
    that read and the commit, it is read and merged once more; a second move
    raises :class:`~server.services.hub_repo.DatasetMoved`.

    Raises ValueError when every pair was left out, and the Hub dataset repo's
    own errors (:class:`~server.services.hub_repo.HubRepoError`).
    """
    from server.services.huggingface import dataset_card

    new = _reviewed_pairs(draft, exclude, edits)
    if not new:
        raise ValueError("Nothing to publish: every pair of the draft was left out")
    repo = open_repo(creds, str(draft["repo_id"]))
    title = str(draft.get("title") or repo.repo_id.split("/")[-1])
    message = f"Add {len(new)} Q/A pair(s) from {draft.get('source') or title}"

    for attempt in (1, 2):
        base = repo.read()
        rows = _merged(base.rows, new)
        sources = sorted({str(r["source_url"]) for r in rows if r.get("source_url")})
        # A Q&A job's dataset keeps the card its job wrote: the next run
        # rewrites it with these rows counted.
        card = (
            dataset_card(
                title, len(rows), draft.get("language"), sources, base.pairs_path
            ).decode("utf-8")
            if base.manifest is None
            else None
        )
        try:
            published = repo.publish(base, rows, card=card, message=message)
        except DatasetMoved:
            if attempt == 2:
                raise
            logger.info("%s moved during the publication: merging again", repo.repo_id)
            continue
        return {
            "repo_id": repo.repo_id,
            "url": published.url,
            "pairs": len(rows),
            "new": len(new),
        }
    raise AssertionError("unreachable")  # pragma: no cover


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
