"""dataset recipes: the saved selection a GitHub-fed dataset is generated from

Revision ID: 3b4c5d6e7f80
Revises: 2a3b4c5d6e7f
Create Date: 2026-11-04

One row per user and recipe: the target Hugging Face repo, whether the
profile facts are included, and the selected repos with their README and
``docs/`` files (JSON). Deleting the user deletes their recipes.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3b4c5d6e7f80"
down_revision: Union[str, Sequence[str], None] = "2a3b4c5d6e7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dataset_recipes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("target_repo", sa.String(), nullable=False),
        sa.Column(
            "include_profile",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("model_ref", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_dataset_recipes_owner_name"),
    )
    op.create_index(
        "ix_dataset_recipes_owner_id", "dataset_recipes", ["owner_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_recipes_owner_id", table_name="dataset_recipes")
    op.drop_table("dataset_recipes")
