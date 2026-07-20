"""create quality_rules

Revision ID: a7b8c9d0e1f2
Revises: e2f3a4b5c6d7
Create Date: 2026-07-16

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "quality_rules",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "min_answer_words", sa.Integer(), nullable=False, server_default="12"
        ),
        sa.Column(
            "reject_below_confidence",
            sa.Float(),
            nullable=False,
            server_default="0.8",
        ),
        sa.Column(
            "auto_reject_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("quality_rules")
