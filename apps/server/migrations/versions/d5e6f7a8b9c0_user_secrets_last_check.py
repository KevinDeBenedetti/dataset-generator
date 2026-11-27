"""user secrets: when the provider last confirmed or refused one

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-11-27

The Hugging Face token is re-checked before each publication and once a day
(auth/hf_token.py): the result is kept on the secret, so a revoked token
pauses its owner's schedules and the daily sweep picks the oldest checks.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_secrets", sa.Column("last_checked_at", sa.DateTime(), nullable=True)
    )
    op.add_column("user_secrets", sa.Column("last_state", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_secrets", "last_state")
    op.drop_column("user_secrets", "last_checked_at")
