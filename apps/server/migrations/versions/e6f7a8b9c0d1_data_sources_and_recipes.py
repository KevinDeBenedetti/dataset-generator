"""data sources, recipes, reviews and publications

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-11-27

The generic path of the open-data redesign (ADR 0001, 0004): a data source
feeds a recipe; a recipe run is a job_runs row (job_id "recipe") whose draft is
reviewed, then published. Tabular draft rows are Parquet files in the draft
store, never rows here.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _owner() -> sa.Column:
    return sa.Column(
        "owner_id",
        sa.String(),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(), primary_key=True),
        _owner(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("connector", sa.String(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("secret_kind", sa.String(), nullable=True),
        sa.Column("licence", sa.String(), nullable=True),
        sa.Column("last_fingerprint", sa.String(), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="uq_data_sources_owner_name"),
    )
    op.create_index("ix_data_sources_owner_id", "data_sources", ["owner_id"])

    op.create_table(
        "recipes",
        sa.Column("id", sa.String(), primary_key=True),
        _owner(),
        sa.Column(
            "data_source_id",
            sa.String(),
            sa.ForeignKey("data_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("output_kind", sa.String(), nullable=False),
        sa.Column("output_options", sa.JSON(), nullable=False),
        sa.Column("target_repo", sa.String(), nullable=False),
        sa.Column("visibility", sa.String(), nullable=False),
        sa.Column("model_ref", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="uq_recipes_owner_name"),
        sa.CheckConstraint(
            "output_kind IN ('table', 'qa', 'corpus')", name="ck_recipes_output_kind"
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'public')", name="ck_recipes_visibility"
        ),
    )
    op.create_index("ix_recipes_owner_id", "recipes", ["owner_id"])
    op.create_index("ix_recipes_data_source_id", "recipes", ["data_source_id"])

    op.create_table(
        "reviews",
        sa.Column("id", sa.String(), primary_key=True),
        _owner(),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("job_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("row_decisions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')", name="ck_reviews_decision"
        ),
    )
    op.create_index("ix_reviews_owner_id", "reviews", ["owner_id"])
    op.create_index("ix_reviews_run_id", "reviews", ["run_id"])

    op.create_table(
        "publications",
        sa.Column("id", sa.String(), primary_key=True),
        _owner(),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("job_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recipe_id",
            sa.String(),
            sa.ForeignKey("recipes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=True),
        sa.Column("pr_url", sa.String(), nullable=True),
        sa.Column("visibility", sa.String(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('private', 'public')", name="ck_publications_visibility"
        ),
    )
    op.create_index("ix_publications_owner_id", "publications", ["owner_id"])
    op.create_index("ix_publications_run_id", "publications", ["run_id"])
    op.create_index("ix_publications_recipe_id", "publications", ["recipe_id"])


def downgrade() -> None:
    op.drop_table("publications")
    op.drop_table("reviews")
    op.drop_table("recipes")
    op.drop_table("data_sources")
