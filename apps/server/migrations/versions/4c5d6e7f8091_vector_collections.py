"""vector collections: splits of Hub datasets embedded into Qdrant

Revision ID: 4c5d6e7f8091
Revises: 3b4c5d6e7f80
Create Date: 2026-11-07

One row per user and collection: the Hugging Face split it is built from (repo,
commit sha, config, split), the embedded columns and model, the build's state
and the latest retrieval test (JSON). The vectors are in Qdrant only. Deleting
the user deletes their collections' rows (their Qdrant collections are dropped
by services/admin.py).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4c5d6e7f8091"
down_revision: Union[str, Sequence[str], None] = "3b4c5d6e7f80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vector_collections",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("revision", sa.String(), nullable=False),
        sa.Column("config_name", sa.String(), nullable=False),
        sa.Column("split", sa.String(), nullable=False),
        sa.Column("text_columns", sa.JSON(), nullable=False),
        sa.Column("query_column", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("vector_size", sa.Integer(), nullable=True),
        sa.Column("rows_total", sa.Integer(), nullable=True),
        sa.Column("points_count", sa.Integer(), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=True),
        sa.Column("built_at", sa.DateTime(), nullable=True),
        sa.Column("evaluation", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "name", name="uq_vector_collections_owner_name"
        ),
    )
    op.create_index(
        "ix_vector_collections_owner_id",
        "vector_collections",
        ["owner_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_vector_collections_owner_id", table_name="vector_collections")
    op.drop_table("vector_collections")
