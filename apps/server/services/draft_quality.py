"""Quality checks of a draft, shown on its review page before it is published.

The pairs checked are the ones the review decides on: a recipe draft's new
and held-out pairs, every pair of a file or web page draft. Two checks:

* near-duplicates, by question and answer text (the Quality page's analysis,
  ``services.datasets._similar_pairs``);
* the user's quality rules (``services.quality_rules.rejection_reason``),
  evaluated even when auto-reject is off: the review reports, it doesn't
  reject.
"""

from typing import Any, Dict, List

from server.core.database import get_scoped_db
from server.models.job_run import JobRun
from server.services.datasets import _similar_pairs
from server.services.drafts import GENERATION_JOB_ID
from server.services.jobs import RunConflictError, _owned_row
from server.services.quality_rules import get_quality_rules, rejection_reason

# The duplicate check compares every pair with every other: bounded so a big
# draft answers in seconds. The pairs beyond it are not compared.
MAX_CHECKED = 400


def review_pairs(row: JobRun) -> List[Dict[str, Any]]:
    """The pairs of a draft that the review decides on."""
    draft = row.draft or {}
    if row.job_id == GENERATION_JOB_ID:
        return [p for p in draft.get("pairs") or [] if isinstance(p, dict)]
    dataset = draft.get("dataset") or {}
    new_ids = set(dataset.get("new_ids") or [])
    new = [
        p
        for p in dataset.get("pairs") or []
        if isinstance(p, dict) and p.get("id") in new_ids
    ]
    return new + [p for p in dataset.get("review") or [] if isinstance(p, dict)]


def check_draft(owner_id: str, run_id: str, threshold: float) -> Dict[str, Any]:
    """Near-duplicate pairs and rule failures of the owner's draft.

    Raises ``UnknownRunError`` (another user's run looks unknown) and
    ``RunConflictError`` for a run without a draft.
    """
    with get_scoped_db() as db:
        row = _owned_row(db, owner_id, run_id)
        if row.draft is None:
            raise RunConflictError("This run has no draft to check")
        pairs = [p for p in review_pairs(row) if p.get("id")]

    checked = pairs[:MAX_CHECKED]
    texts = [
        {"question": str(p.get("question", "")), "answer": str(p.get("answer", ""))}
        for p in checked
    ]
    duplicates = [
        {
            "first": checked[i]["id"],
            "second": checked[j]["id"],
            "similarity": round(ratio, 3),
        }
        for i, j, ratio in _similar_pairs(texts, threshold)
    ]

    rules = {**get_quality_rules(owner_id), "auto_reject_enabled": True}
    flagged: Dict[str, str] = {}
    for pair in pairs:
        reason = rejection_reason(
            str(pair.get("answer", "")), pair.get("confidence"), rules
        )
        if reason:
            flagged[str(pair["id"])] = reason
    return {
        "threshold": threshold,
        "checked": len(checked),
        "total": len(pairs),
        "duplicates": duplicates,
        "flagged": flagged,
    }
