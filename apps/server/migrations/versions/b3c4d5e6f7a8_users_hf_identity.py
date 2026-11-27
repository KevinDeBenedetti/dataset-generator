"""users: the Hugging Face account a user signs in with

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-11-27

Users sign in with their Hugging Face username and token (ADR 0002): the
account is keyed on the Hub's stable account id (``hf_id``), never the
username, which can change. The Hub may not return an email, so ``email``
becomes nullable; its unique index stays (Postgres treats NULLs as distinct).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("hf_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("hf_username", sa.String(), nullable=True))
    op.add_column("users", sa.Column("hf_avatar_url", sa.String(), nullable=True))
    op.create_index("ix_users_hf_id", "users", ["hf_id"], unique=True)
    op.alter_column("users", "email", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # An account without an email can't go back: give it a reserved address.
    op.execute(
        "UPDATE users SET email = 'hf-' || id || '@hf-account.invalid' "
        "WHERE email IS NULL"
    )
    op.alter_column("users", "email", existing_type=sa.String(), nullable=False)
    op.drop_index("ix_users_hf_id", table_name="users")
    op.drop_column("users", "hf_avatar_url")
    op.drop_column("users", "hf_username")
    op.drop_column("users", "hf_id")
