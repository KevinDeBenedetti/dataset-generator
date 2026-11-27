"""Reviewing a tabular draft (ADR 0006): read it whole, page through its rows,
approve or reject it.

The draft is a recipe run's (``job_id="recipe"``): its metadata is in
``job_runs.draft``, its rows in ``<owner>/<run_id>/data.parquet``, read by
DuckDB in the run's sandbox — a reviewer pages through any number of rows
without the browser ever loading them. Every decision is a ``reviews`` row and
an audit entry. An approval is refused (409) while a blocking rule of the
quality report fails; a rejection marks the run ``rejected`` and leaves the
recipe as it is, to be fixed and run again.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.engine.session import EngineError, session
from server.models.data_source import Review, ReviewDecision
from server.models.job_run import JobRun
from server.models.user import User
from server.review.tabular_quality import blocking_rules
from server.services import audit

MAX_PAGE = 500
# The statuses a tabular draft can be reviewed in.
REVIEWABLE = ("succeeded",)


class DraftNotFound(LookupError):
    """No tabular draft with that run id among the caller's."""


class ReviewRefused(ValueError):
    """The decision can't be taken: ``rules`` holds the blocking ones, if any."""

    def __init__(self, message: str, rules: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.rules = rules or []


def _run(db: Session, owner_id: str, run_id: str) -> JobRun:
    run = db.get(JobRun, run_id)
    if (
        run is None
        or run.owner_id != owner_id
        or run.job_id != "recipe"
        or not isinstance(run.draft, dict)
        or run.draft.get("kind") not in ("table", "corpus")
    ):
        raise DraftNotFound(f"Unknown draft '{run_id}'")
    return run


def _published_before(db: Session, run: JobRun) -> Optional[Dict[str, Any]]:
    """The draft of the recipe's last published run before this one."""
    recipe_id = (run.options or {}).get("recipe_id")
    rows = db.scalars(
        select(JobRun)
        .where(
            JobRun.owner_id == run.owner_id,
            JobRun.job_id == "recipe",
            JobRun.status == "published",
            JobRun.id != run.id,
        )
        .order_by(JobRun.started_at.desc())
    )
    for other in rows:
        if (other.options or {}).get("recipe_id") == recipe_id and other.draft:
            return other.draft
    return None


def _diff(
    draft: Dict[str, Any], published: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    if not published:
        return None
    before = {c["name"]: c["type"] for c in published.get("schema") or []}
    after = {c["name"]: c["type"] for c in draft.get("schema") or []}
    return {
        "added": [c for c in after if c not in before],
        "removed": [c for c in before if c not in after],
        "retyped": [
            {"column": c, "from": before[c], "to": after[c]}
            for c in after
            if c in before and before[c] != after[c]
        ],
        "rows_before": published.get("rows"),
        "rows_after": draft.get("rows"),
    }


def _latest_review(db: Session, run_id: str) -> Optional[Dict[str, Any]]:
    row = db.scalars(
        select(Review).where(Review.run_id == run_id).order_by(Review.created_at.desc())
    ).first()
    if row is None:
        return None
    return {
        "decision": row.decision,
        "comment": row.comment,
        "created_at": row.created_at,
    }


def get_draft(db: Session, owner_id: str, run_id: str) -> Dict[str, Any]:
    run = _run(db, owner_id, run_id)
    draft = run.draft or {}
    source_names = {
        c["name"]: c.get("original", c["name"])
        for c in draft.get("source_schema") or []
    }
    schema = [
        {**c, "original": source_names.get(c["name"], c["name"])}
        for c in draft.get("schema") or []
    ]
    report = draft.get("quality_report") or {}
    from server.services.tabular_publish import public_allowed

    return {
        "public_refusal": public_allowed(draft),
        "run_id": run.id,
        "status": run.status,
        "kind": draft.get("kind") or "table",
        "recipe_id": draft.get("recipe_id"),
        "data_source_id": draft.get("data_source_id"),
        "target_repo": draft.get("target_repo"),
        "visibility": draft.get("visibility"),
        "provenance": draft.get("provenance") or {},
        "rows": draft.get("rows", 0),
        "source_rows": draft.get("source_rows", 0),
        "schema": schema,
        "profile": draft.get("profile") or {},
        "quality_report": report,
        "blocking": blocking_rules(report),
        "step_rows": draft.get("step_rows") or [],
        "steps": draft.get("steps") or [],
        "warnings": draft.get("warnings") or [],
        "changes": _diff(draft, _published_before(db, run)),
        "review": _latest_review(db, run.id),
        "published_url": run.published_url,
    }


def get_rows(
    db: Session,
    owner_id: str,
    run_id: str,
    *,
    offset: int = 0,
    limit: int = 100,
    sort: Optional[str] = None,
    descending: bool = False,
    filter_column: Optional[str] = None,
    filter_value: Optional[str] = None,
) -> Dict[str, Any]:
    """A page of the draft's rows, read from its Parquet file."""
    from server.engine.profile import page_parquet
    from server.services.draft_store import get_store

    run = _run(db, owner_id, run_id)
    names = [c["name"] for c in (run.draft or {}).get("schema") or []]
    for column in (sort, filter_column):
        if column is not None and column not in names:
            raise ValueError(f"Unknown column '{column}'")
    limit = max(1, min(int(limit), MAX_PAGE))
    offset = max(0, int(offset))
    store = get_store()
    run_dir = store.run_dir(owner_id, run_id)
    data = run_dir / "data.parquet"
    if not data.is_file():
        raise DraftNotFound(
            "The draft's rows are gone (published, or kept past retention)"
        )
    with session(run_dir, timeout_s=30) as s:
        return page_parquet(
            s,
            data,
            offset=offset,
            limit=limit,
            sort=sort,
            descending=descending,
            filter_column=filter_column,
            filter_value=filter_value,
        )


def decide(
    db: Session,
    reviewer: User,
    run_id: str,
    decision: str,
    comment: Optional[str] = None,
    ip: Optional[str] = None,
    *,
    creds: Any = None,
    backend: Any = None,
) -> Dict[str, Any]:
    """Record ``decision`` on the draft; the review row as served. An approval
    publishes the draft first (services/tabular_publish.py, with ``creds``):
    the review is recorded only once the publication is in."""
    if decision not in ReviewDecision.ALL:
        raise ReviewRefused(f"Unknown decision '{decision}'")
    run = _run(db, reviewer.id, run_id)
    if run.status not in REVIEWABLE:
        raise ReviewRefused(f"This draft can't be reviewed now (it is {run.status})")
    report = (run.draft or {}).get("quality_report") or {}
    blocking = blocking_rules(report)
    if decision == ReviewDecision.APPROVED and blocking:
        raise ReviewRefused("A blocking rule of the quality report fails", blocking)
    published: Optional[Dict[str, Any]] = None
    if decision == ReviewDecision.APPROVED:
        from server.services.tabular_publish import PublishRefused, publish

        try:
            published = publish(db, creds, run, backend=backend)
        except PublishRefused as exc:
            raise ReviewRefused(str(exc)) from None
    review = Review(
        owner_id=reviewer.id,
        run_id=run.id,
        reviewer_id=reviewer.id,
        decision=decision,
        comment=(comment or "").strip() or None,
    )
    db.add(review)
    if decision == ReviewDecision.REJECTED:
        run.status = "rejected"
    audit.record(
        db,
        f"recipe.review.{decision}",
        actor=reviewer,
        target=reviewer,
        ip=ip,
        detail={
            "run_id": run.id,
            "recipe_id": (run.options or {}).get("recipe_id"),
            "rows": (run.draft or {}).get("rows"),
            **(
                {"repo_id": published["repo_id"], "commit": published["commit"]}
                if published
                else {}
            ),
        },
        commit=False,
    )
    db.commit()
    return {
        "decision": review.decision,
        "comment": review.comment,
        "created_at": review.created_at,
        "status": run.status,
        "published_url": run.published_url,
    }


__all__ = [
    "DraftNotFound",
    "EngineError",
    "ReviewRefused",
    "decide",
    "get_draft",
    "get_rows",
]


def list_runs(db: Session, owner_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """The owner's recipe runs, newest first, with what the review needs."""
    from server.models.data_source import Recipe

    rows = list(
        db.scalars(
            select(JobRun)
            .where(JobRun.owner_id == owner_id, JobRun.job_id == "recipe")
            .order_by(JobRun.started_at.desc())
            .limit(limit)
        )
    )
    recipe_ids = {(r.options or {}).get("recipe_id") for r in rows}
    names = {
        r.id: r.name
        for r in db.scalars(
            select(Recipe).where(Recipe.id.in_([i for i in recipe_ids if i]))
        )
    }
    return [
        {
            "run_id": r.id,
            "status": r.status,
            "recipe_id": (r.options or {}).get("recipe_id"),
            "recipe_name": names.get((r.options or {}).get("recipe_id")),
            "rows": (r.draft or {}).get("rows") if isinstance(r.draft, dict) else None,
            "started_at": r.started_at,
            "error": r.error,
            "published_url": r.published_url,
            "to_review": r.status == "succeeded" and isinstance(r.draft, dict),
            "kind": (r.draft or {}).get("kind") if isinstance(r.draft, dict) else None,
        }
        for r in rows
    ]
