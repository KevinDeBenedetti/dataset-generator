"""platform settings: the sign-up policy speaks in Hugging Face terms

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-11-27

``allow_signup`` (a bool) becomes ``signup_policy``: ``open`` when it was on,
``closed`` when it was off. ``allowed_email_domains`` is dropped: emails are no
longer the identity (ADR 0002); the domains dropped are logged. Without a row,
nothing changes: the default still follows ENVIRONMENT.
"""

import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_settings = sa.table(
    "platform_settings",
    sa.column("key", sa.String()),
    sa.column("value", sa.JSON()),
    sa.column("updated_at", sa.DateTime()),
)


def _value(conn, key):
    row = conn.execute(
        sa.select(_settings.c.value).where(_settings.c.key == key)
    ).first()
    # The JSON column hands back the decoded value: "open" is already a str.
    return None if row is None else row[0]


def _replace(conn, old: str, new: str, value) -> None:
    conn.execute(sa.delete(_settings).where(_settings.c.key == old))
    conn.execute(
        sa.insert(_settings).values(key=new, value=value, updated_at=sa.func.now())
    )


def upgrade() -> None:
    conn = op.get_bind()
    allow = _value(conn, "allow_signup")
    if allow is not None:
        _replace(conn, "allow_signup", "signup_policy", "open" if allow else "closed")
    domains = _value(conn, "allowed_email_domains")
    if domains:
        logger.warning("Sign-up email domains dropped: %s", ", ".join(domains))
    conn.execute(sa.delete(_settings).where(_settings.c.key == "allowed_email_domains"))


def downgrade() -> None:
    conn = op.get_bind()
    policy = _value(conn, "signup_policy")
    if policy is not None:
        _replace(conn, "signup_policy", "allow_signup", policy == "open")
    conn.execute(
        sa.delete(_settings).where(
            _settings.c.key.in_(("signup_orgs", "signup_usernames"))
        )
    )
