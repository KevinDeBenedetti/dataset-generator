"""vector collections: the commit a rebuild is embedding

Revision ID: 91a2b3c4d5e6
Revises: 8091a2b3c4d5
Create Date: 2026-11-17

A rebuild no longer replaces the vectors at its first batch: it fills a new
Qdrant collection and the collection's name is switched to it once complete.
``revision`` therefore stays the commit of the vectors being served, and
``building_revision`` holds the commit the build in flight is embedding.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "91a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "8091a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vector_collections",
        sa.Column("building_revision", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vector_collections", "building_revision")
