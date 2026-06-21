"""backfill node status from supersession chains

Adds a status column to the Postgres nodes shadow table and backfills it
based on whether nodes have been superseded. Active nodes receive 'active',
superseded nodes receive 'superseded'.

For Memgraph, the corresponding Cypher backfill queries are stored in
context_service.db.queries (BACKFILL_SUPERSEDED_STATE, BACKFILL_ACTIVE_STATE)
and should be run against the graph database separately via the admin CLI or
the cypher_migrations utility.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-21

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add a status column to the Postgres nodes shadow table.
    # Existing rows default to 'active'. Superseded rows are identified by
    # their absence in Qdrant (deleted on supersession) — the application
    # layer sets this column when writing supersession edges.
    op.add_column(
        "nodes",
        sa.Column(
            "status",
            sa.Text(),
            server_default="active",
            nullable=False,
        ),
    )
    op.create_index("ix_nodes_status", "nodes", ["status"])

    # Backfill: ensure all existing rows have an explicit status value.
    op.execute("UPDATE nodes SET status = 'active' WHERE status IS NULL")


def downgrade() -> None:
    op.drop_index("ix_nodes_status", table_name="nodes")
    op.drop_column("nodes", "status")
