"""add pg_trgm index and state column for BM25 channel

Adds trigram index for fuzzy text matching alongside existing tsvector GIN
index. Adds state column for filtering superseded nodes from search results.

Revision ID: 0017
Revises: 42f64ba6df17
Create Date: 2026-06-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str = "42f64ba6df17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_nodes_content_trgm
        ON nodes USING GIN (content gin_trgm_ops)
    """)

    op.add_column(
        "nodes",
        sa.Column("state", sa.Text(), server_default="ACTIVE", nullable=False),
    )
    op.create_index("ix_nodes_state", "nodes", ["state"])


def downgrade() -> None:
    op.drop_index("ix_nodes_state", table_name="nodes")
    op.drop_column("nodes", "state")
    op.execute("DROP INDEX IF EXISTS ix_nodes_content_trgm")
