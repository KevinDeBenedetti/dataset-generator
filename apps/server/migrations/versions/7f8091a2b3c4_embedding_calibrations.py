"""embedding calibrations: the checks' thresholds measured per user and model

Revision ID: 7f8091a2b3c4
Revises: 6e7f8091a2b3
Create Date: 2026-11-11

One row per user and embedding model: the duplicate, grounding and coverage
thresholds measured on the built-in test set (services/calibration.py), and
the measurement's report. The model a user's checks embed with is their
``model_defaults`` row of role ``embedding``. Deleting the user deletes them.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f8091a2b3c4"
down_revision: Union[str, Sequence[str], None] = "6e7f8091a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "embedding_calibrations",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("model_ref", sa.String(), nullable=False),
        sa.Column("dedup", sa.Float(), nullable=False),
        sa.Column("grounding", sa.Float(), nullable=False),
        sa.Column("uncovered", sa.Float(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("measured_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "model_ref"),
    )


def downgrade() -> None:
    op.drop_table("embedding_calibrations")
