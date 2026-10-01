"""Default model per role and user, persisted in ``model_defaults``, set on /models.

Roles:

* ``cleaning`` — tidies scraped/extracted text before QA generation;
* ``qa`` — generates the question/answer pairs;
* ``vision`` — transcribes uploaded PDF/image pages;
* ``jobs`` — the scheduled dataset jobs (server/jobs), when run from the UI.

A role without a row falls back to the environment, so a fresh install and
the DB-free CI behave exactly as before providers existed.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from server.core.config import config
from server.core.database import get_scoped_db
from server.models.model_defaults import ModelDefault
from server.services.credentials import Credentials
from server.services.providers import normalize_ref, validate_ref

logger = logging.getLogger(__name__)

ROLES = ("cleaning", "qa", "vision", "jobs")


def env_defaults() -> Dict[str, str]:
    """What each role uses when nothing is stored (bare ids → ``openai:``)."""
    raw = {
        "cleaning": config.model_cleaning,
        "qa": config.model_qa,
        "vision": config.openai_vlm_model,
        "jobs": config.qa_job_model,
    }
    defaults = {role: normalize_ref(ref) if ref else "" for role, ref in raw.items()}
    return _without_unavailable(defaults)


def _without_unavailable(defaults: Dict[str, str]) -> Dict[str, str]:
    """Outside development/CI the Claude provider doesn't exist: a ``claude:``
    default (from the env or saved during development) falls back to the qa model."""
    if config.claude_provider_available:
        return defaults
    fallback = normalize_ref(config.model_qa) if config.model_qa else ""
    return {
        role: fallback if ref.startswith("claude:") else ref
        for role, ref in defaults.items()
    }


def get_model_defaults(user_id: Optional[str] = None) -> Dict[str, str]:
    """``user_id``'s stored defaults over the env ones (env only without a user —
    the system/CI path). Never raises: generation must not fail because the
    table is missing or the DB unreachable."""
    defaults = env_defaults()
    if not user_id:
        return defaults
    try:
        with get_scoped_db() as db:
            rows = db.query(ModelDefault).filter(ModelDefault.user_id == user_id)
            for row in rows:
                if row.role in defaults:
                    defaults[row.role] = row.model_ref
    except Exception as exc:  # noqa: BLE001 — degrade to env defaults
        logger.warning("Could not read model defaults, using env: %s", exc)
    return _without_unavailable(defaults)


def resolve_model(
    role: str, override: Optional[str] = None, user_id: Optional[str] = None
) -> str:
    """The reference a call should use: the request's own, else the role default."""
    if override:
        return normalize_ref(override)
    return get_model_defaults(user_id).get(role, "")


def update_model_defaults(
    user_id: str, changes: Dict[str, str], creds: Credentials
) -> Dict[str, str]:
    """Upsert the given roles for ``user_id``. ValueError for an unknown role or model."""
    validated = {}
    for role, ref in changes.items():
        if role not in ROLES:
            raise ValueError(f"Unknown role '{role}'. Roles: {', '.join(ROLES)}")
        validated[role] = validate_ref(ref, creds)

    with get_scoped_db() as db:
        for role, ref in validated.items():
            row = db.get(ModelDefault, {"user_id": user_id, "role": role})
            if row is None:
                row = ModelDefault(user_id=user_id, role=role, model_ref=ref)
                db.add(row)
            row.model_ref = ref
            row.updated_at = datetime.now(timezone.utc)
        db.commit()
    return get_model_defaults(user_id)
