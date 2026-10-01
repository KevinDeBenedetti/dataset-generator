"""platform-wide switches set from the backoffice

Revision ID: 1f2e3d4c5b6a
Revises: c0d1e2f3a4b5
Create Date: 2026-10-01

Purely additive: a switch without a row keeps its env-var default.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1f2e3d4c5b6a"
down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
