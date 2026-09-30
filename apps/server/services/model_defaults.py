"""Default model per role, persisted in ``model_defaults`` and set on /models.

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
    return {role: normalize_ref(ref) if ref else "" for role, ref in raw.items()}


def get_model_defaults() -> Dict[str, str]:
    """Stored defaults over the env ones. Never raises: generation must not
    fail because the table is missing or the DB unreachable."""
    defaults = env_defaults()
    try:
        with get_scoped_db() as db:
            for row in db.query(ModelDefault).all():
                if row.role in defaults:
                    defaults[row.role] = row.model_ref
    except Exception as exc:  # noqa: BLE001 — degrade to env defaults
        logger.warning("Could not read model defaults, using env: %s", exc)
    return defaults


def resolve_model(role: str, override: Optional[str] = None) -> str:
    """The reference a call should use: the request's own, else the role default."""
    if override:
        return normalize_ref(override)
    return get_model_defaults().get(role, "")


def update_model_defaults(changes: Dict[str, str]) -> Dict[str, str]:
    """Upsert the given roles. ValueError for an unknown role or model."""
    validated = {}
    for role, ref in changes.items():
        if role not in ROLES:
            raise ValueError(f"Unknown role '{role}'. Roles: {', '.join(ROLES)}")
        validated[role] = validate_ref(ref)

    with get_scoped_db() as db:
        for role, ref in validated.items():
            row = db.get(ModelDefault, role)
            if row is None:
                row = ModelDefault(role=role, model_ref=ref)
                db.add(row)
            row.model_ref = ref
            row.updated_at = datetime.now(timezone.utc)
        db.commit()
    return get_model_defaults()
