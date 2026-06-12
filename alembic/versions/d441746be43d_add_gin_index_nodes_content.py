"""add_gin_index_nodes_content

Adds a Postgres shadow table for node content to support BM25 full-text
search via GIN index. Primary node storage remains in Memgraph; this table
is written on store() and read by the BM25 retrieval channel.

Revision ID: d441746be43d
Revises: 0015
Create Date: 2026-06-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d441746be43d"
down_revision: str = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nodes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("silo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("layer", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nodes_silo_id", "nodes", ["silo_id"])
    op.create_index("ix_nodes_layer", "nodes", ["layer"])
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_nodes_content_gin
        ON nodes USING GIN (to_tsvector('english', content))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_nodes_content_gin")
    op.drop_index("ix_nodes_layer", table_name="nodes")
    op.drop_index("ix_nodes_silo_id", table_name="nodes")
    op.drop_table("nodes")
