"""external identities, audit log, login bookkeeping

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-09-30

* ``identities``: one row per external sign-in (Infomaniak, GitHub), unique on
  ``(provider, subject)``. Existing Infomaniak links (``users.oidc_sub``) are
  copied over; the column stays, unused, for one release (expand/contract).
* ``audit_log``: security events (sign-up, link, role change…).
* ``users.last_login_at`` and ``users.sessions_valid_after`` ("sign out
  everywhere"), and a CHECK on ``users.role``.
"""

from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "identities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "subject", name="uq_identities_provider_subject"
        ),
    )
    op.create_index("ix_identities_user_id", "identities", ["user_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("actor_label", sa.String(), nullable=True),
        sa.Column("target_user_id", sa.String(), nullable=True),
        sa.Column("target_label", sa.String(), nullable=True),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_target_user_id", "audit_log", ["target_user_id"])

    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users", sa.Column("sessions_valid_after", sa.DateTime(), nullable=True)
    )
    op.create_check_constraint("ck_users_role", "users", "role IN ('user', 'admin')")

    # Existing Infomaniak links become identities. The email only counts as
    # verified when it is a real one (not the "<sub>@oidc.local" placeholder).
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, email, oidc_sub FROM users WHERE oidc_sub IS NOT NULL")
    ).all()
    for user_id, email, sub in rows:
        placeholder = email.endswith("@oidc.local")
        bind.execute(
            sa.text(
                "INSERT INTO identities (id, user_id, provider, subject, email, "
                "email_verified, created_at) VALUES (:id, :user_id, 'infomaniak', "
                ":sub, :email, :verified, (NOW() AT TIME ZONE 'UTC'))"
            ),
            {
                "id": str(uuid4()),
                "user_id": user_id,
                "sub": sub,
                "email": None if placeholder else email,
                "verified": not placeholder,
            },
        )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "sessions_valid_after")
    op.drop_column("users", "last_login_at")
    op.drop_table("audit_log")
    op.drop_index("ix_identities_user_id", table_name="identities")
    op.drop_table("identities")
