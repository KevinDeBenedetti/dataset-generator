"""Each user's LLM, persisted in ``model_defaults``, set on /models.

One model runs every step — cleaning, Q&A generation, the pages of an uploaded
PDF or image, the dataset jobs. A user who saved none gets OPENAI_LLM_MODEL.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from server.core.config import config
from server.core.database import get_scoped_db
from server.models.model_defaults import ModelDefault
from server.services.credentials import Credentials
from server.services.providers import normalize_ref, validate_ref

logger = logging.getLogger(__name__)

# The one row a user keeps (the table's role column predates the merge of the
# per-step models into one; migration 5d6e7f8091a2 folded them into this).
LLM_ROLE = "llm"


def env_default() -> str:
    """OPENAI_LLM_MODEL as a reference ("" when unset)."""
    return normalize_ref(config.openai_llm_model) if config.openai_llm_model else ""


def get_default_model(user_id: Optional[str] = None) -> str:
    """``user_id``'s saved LLM, else OPENAI_LLM_MODEL. Never raises: generation
    must not fail because the table is missing or the database unreachable."""
    if user_id:
        try:
            with get_scoped_db() as db:
                row = db.get(ModelDefault, {"user_id": user_id, "role": LLM_ROLE})
                if row is not None and row.model_ref:
                    return normalize_ref(row.model_ref)
        except Exception as exc:  # noqa: BLE001 — degrade to the env default
            logger.warning("Could not read the saved model, using env: %s", exc)
    return env_default()


def resolve_model(override: Optional[str] = None, user_id: Optional[str] = None) -> str:
    """The reference a call should use: the request's own, else the default."""
    if override:
        return normalize_ref(override)
    return get_default_model(user_id)


def set_default_model(user_id: str, ref: str, creds: Credentials) -> str:
    """Save ``user_id``'s LLM. ValueError for an unknown or unusable model."""
    validated = validate_ref(ref, creds)
    with get_scoped_db() as db:
        row = db.get(ModelDefault, {"user_id": user_id, "role": LLM_ROLE})
        if row is None:
            row = ModelDefault(user_id=user_id, role=LLM_ROLE, model_ref=validated)
            db.add(row)
        row.model_ref = validated
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
    return get_default_model(user_id)
