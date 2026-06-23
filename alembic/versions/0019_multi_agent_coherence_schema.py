"""multi-agent coherence schema additions

Adds agents table, node identity fields, belief_events table, CONTRADICTS
edge resolution fields on edges, and supporting indexes.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1.1 agents table
    op.create_table(
        "agents",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("silo_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("parent_agent_id", sa.Text(), nullable=True),
        sa.Column("trust_score", sa.Float(), server_default=sa.text("0.5"), nullable=True),
        sa.Column("beliefs_validated", sa.Integer(), server_default=sa.text("0"), nullable=True),
        sa.Column("beliefs_contradicted", sa.Integer(), server_default=sa.text("0"), nullable=True),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("silo_id", "id", name="uq_agents_silo_id"),
    )
    op.create_index("idx_agents_silo", "agents", ["silo_id"])

    # 1.2 node identity fields
    op.add_column("nodes", sa.Column("agent_id", sa.Text(), nullable=True))
    op.add_column("nodes", sa.Column("session_id", sa.Text(), nullable=True))
    op.add_column("nodes", sa.Column("owner_id", sa.Text(), nullable=True))
    op.add_column("nodes", sa.Column("model_id", sa.Text(), nullable=True))

    # 1.3 belief_events table
    op.create_table(
        "belief_events",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("silo_id", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_node_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_events_silo_agent",
        "belief_events",
        ["silo_id", "agent_id", "created_at"],
    )
    op.create_index(
        "idx_events_node",
        "belief_events",
        ["target_node_id", "created_at"],
    )

    # 1.4 CONTRADICTS edge resolution fields:
    # Edges live in Memgraph (schemaless) — no Postgres migration needed.
    # The BinaryEdge model in models.py is updated separately.

    # 1.5 node identity indexes
    op.create_index("idx_nodes_agent", "nodes", ["silo_id", "agent_id"])
    op.create_index("idx_nodes_session", "nodes", ["silo_id", "session_id"])

    # 1.6 backfill existing nodes with 'legacy' agent_id
    op.execute("UPDATE nodes SET agent_id = 'legacy' WHERE agent_id IS NULL")

    # Insert 'legacy' agent for each existing silo that has nodes.
    # Uses INSERT ... ON CONFLICT DO NOTHING so it's idempotent.
    op.execute(
        """
        INSERT INTO agents (id, silo_id, role, first_seen, last_seen)
        SELECT DISTINCT 'legacy', silo_id::text, 'legacy', now(), now()
        FROM nodes
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # Remove node identity indexes
    op.drop_index("idx_nodes_session", table_name="nodes")
    op.drop_index("idx_nodes_agent", table_name="nodes")

    # Remove belief_events table
    op.drop_index("idx_events_node", table_name="belief_events")
    op.drop_index("idx_events_silo_agent", table_name="belief_events")
    op.drop_table("belief_events")

    # Remove node identity fields
    op.drop_column("nodes", "model_id")
    op.drop_column("nodes", "owner_id")
    op.drop_column("nodes", "session_id")
    op.drop_column("nodes", "agent_id")

    # Remove agents table
    op.drop_index("idx_agents_silo", table_name="agents")
    op.drop_table("agents")
