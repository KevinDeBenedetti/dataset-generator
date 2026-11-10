"""one LLM: fold the per-step model defaults into one, drop the Claude secrets

Revision ID: 5d6e7f8091a2
Revises: 4c5d6e7f8091
Create Date: 2026-11-09

The models of the cleaning, Q&A, vision and jobs steps are now one LLM: each
user keeps a single ``model_defaults`` row, role ``llm``, taken from their Q&A
default (else jobs, cleaning, vision), a ``claude:`` one excepted — the Claude
subscription provider is gone. Its secrets (``claude_token``,
``anthropic_api_key``) are deleted from ``user_secrets``.

The downgrade copies the ``llm`` row back into the four roles; the deleted
secrets can't come back, their owners save them again.
"""

from datetime import datetime, timezone
from typing import Dict, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5d6e7f8091a2"
down_revision: Union[str, Sequence[str], None] = "4c5d6e7f8091"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_ROLES = ("qa", "jobs", "cleaning", "vision")  # most telling first
_GONE_SECRET_KINDS = ("claude_token", "anthropic_api_key")


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT user_id, role, model_ref FROM model_defaults")
    ).fetchall()
    chosen: Dict[str, str] = {}
    for role in _OLD_ROLES:
        for user_id, row_role, ref in rows:
            if (
                row_role == role
                and user_id not in chosen
                and not ref.startswith("claude:")
            ):
                chosen[user_id] = ref
    conn.execute(sa.text("DELETE FROM model_defaults"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for user_id, ref in chosen.items():
        conn.execute(
            sa.text(
                "INSERT INTO model_defaults (user_id, role, model_ref, updated_at) "
                "VALUES (:user_id, 'llm', :ref, :now)"
            ),
            {"user_id": user_id, "ref": ref, "now": now},
        )
    for kind in _GONE_SECRET_KINDS:
        conn.execute(
            sa.text("DELETE FROM user_secrets WHERE kind = :kind"), {"kind": kind}
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT user_id, model_ref, updated_at FROM model_defaults "
            "WHERE role = 'llm'"
        )
    ).fetchall()
    conn.execute(sa.text("DELETE FROM model_defaults"))
    for user_id, ref, updated_at in rows:
        for role in _OLD_ROLES:
            conn.execute(
                sa.text(
                    "INSERT INTO model_defaults (user_id, role, model_ref, updated_at) "
                    "VALUES (:user_id, :role, :ref, :updated_at)"
                ),
                {
                    "user_id": user_id,
                    "role": role,
                    "ref": ref,
                    "updated_at": updated_at,
                },
            )
