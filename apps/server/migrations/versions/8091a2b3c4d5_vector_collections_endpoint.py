"""vector collections: the endpoint a collection was built on

Revision ID: 8091a2b3c4d5
Revises: 7f8091a2b3c4
Create Date: 2026-11-16

An endpoint collection names its model by the endpoint's id for it
(``openai:<id>``), which says nothing of the endpoint itself. ``endpoint`` is
the host of the one that embedded the points, recorded by each build, so a
collection whose owner now uses another endpoint can ask to be built again
instead of searching another vector space. Null for a collection built before.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8091a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "7f8091a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vector_collections", sa.Column("endpoint", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("vector_collections", "endpoint")
