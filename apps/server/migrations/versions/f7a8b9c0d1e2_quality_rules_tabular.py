"""quality rules: the rules of tabular drafts

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-11-27

A user's quality-rule set gains a ``tabular`` section (minimum rows, largest
empty share, required columns, unmasked personal data), read by the quality
report of every tabular draft (review/tabular_quality.py). Null = the defaults.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("quality_rules", sa.Column("tabular", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("quality_rules", "tabular")
