"""Persisted quality rules applied to generated Q&A pairs.

One global config row (see :class:`server.models.quality_rules.QualityRules`).
The pipeline reads the rules once per run and passes them to
:class:`server.services.qa.QAService`, which enforces them only when
``auto_reject_enabled`` is true.
"""

import logging
from typing import Any, Dict, Optional

from server.core.database import get_scoped_db
from server.models.quality_rules import QualityRules

logger = logging.getLogger(__name__)

# Fallback when the row doesn't exist yet (or the DB is unreachable):
# enforcement off, thresholds prefilled with the model defaults.
DEFAULT_RULES: Dict[str, Any] = {
    "min_answer_words": 12,
    "reject_below_confidence": 0.8,
    "auto_reject_enabled": False,
    "updated_at": None,
}


def _to_dict(row: QualityRules) -> Dict[str, Any]:
    return {
        "min_answer_words": row.min_answer_words,
        "reject_below_confidence": row.reject_below_confidence,
        "auto_reject_enabled": row.auto_reject_enabled,
        "updated_at": row.updated_at,
    }


def get_quality_rules() -> Dict[str, Any]:
    """The current rules, or the defaults when never configured.

    Never raises: generation must not fail because the rules table is
    missing/unreachable — it falls back to enforcement-off defaults.
    """
    try:
        with get_scoped_db() as db:
            row = db.get(QualityRules, "default")
            return _to_dict(row) if row else dict(DEFAULT_RULES)
    except Exception as exc:  # noqa: BLE001 — degrade to defaults
        logger.warning("Could not read quality rules, using defaults: %s", exc)
        return dict(DEFAULT_RULES)


def update_quality_rules(
    *,
    min_answer_words: Optional[int] = None,
    reject_below_confidence: Optional[float] = None,
    auto_reject_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """Upsert the singleton row, changing only the provided fields."""
    from datetime import datetime, timezone

    with get_scoped_db() as db:
        row = db.get(QualityRules, "default")
        if row is None:
            row = QualityRules(id="default")
            db.add(row)
        if min_answer_words is not None:
            row.min_answer_words = min_answer_words
        if reject_below_confidence is not None:
            row.reject_below_confidence = reject_below_confidence
        if auto_reject_enabled is not None:
            row.auto_reject_enabled = auto_reject_enabled
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return _to_dict(row)


def rejection_reason(
    answer: str, confidence: Any, rules: Dict[str, Any]
) -> Optional[str]:
    """Why a generated pair should be rejected, or None to keep it.

    No-op unless ``auto_reject_enabled`` is set in ``rules``. A confidence
    that isn't a real number (unscored pair) skips the confidence check
    rather than rejecting.
    """
    if not rules.get("auto_reject_enabled"):
        return None
    min_words = rules.get("min_answer_words") or 0
    if min_words and len(answer.split()) < min_words:
        return f"answer shorter than {min_words} words"
    threshold = rules.get("reject_below_confidence") or 0.0
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        return None
    if conf < threshold:
        return f"confidence {conf:.2f} below {threshold:.2f}"
    return None
