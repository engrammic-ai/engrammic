"""hybrid storage tables

Revision ID: a1b2c3d4e5f6
Revises: 4e1253256b87
Create Date: 2026-05-05 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "4e1253256b87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # org_preferences — root table, no FK dependencies
    op.create_table(
        "org_preferences",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "default_llm",
            sa.String(64),
            server_default="claude-haiku-4-5-20251001",
            nullable=False,
        ),
        sa.Column(
            "embedding_model",
            sa.String(64),
            server_default="jina-embeddings-v3",
            nullable=False,
        ),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("org_id"),
    )

    # silo_config — FK to org_preferences
    op.create_table(
        "silo_config",
        sa.Column("silo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "quotas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "feature_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["org_preferences.org_id"]),
        sa.PrimaryKeyConstraint("silo_id"),
    )

    # reasoning_chain_steps — FK to silo_config
    op.create_table(
        "reasoning_chain_steps",
        sa.Column("chain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("silo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "steps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["silo_id"], ["silo_config.silo_id"]),
        sa.PrimaryKeyConstraint("chain_id"),
    )
    op.create_index(
        "ix_reasoning_chain_steps_silo_id",
        "reasoning_chain_steps",
        ["silo_id"],
    )

    # orphaned_chains — dead-letter table, no FK (intentionally disconnected)
    op.create_table(
        "orphaned_chains",
        sa.Column("chain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("silo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "failed_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("chain_id"),
    )

    # events — FK to silo_config
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("silo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("source_chain_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.String(255), nullable=True),
        sa.Column("step_count", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["silo_id"], ["silo_config.silo_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_events_silo_type_created",
        "events",
        ["silo_id", "event_type", "created_at"],
    )
    op.create_index(
        "ix_events_expires_at_partial",
        "events",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )

    # audit_events — FK to silo_config; immutable compliance log
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("silo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["silo_id"], ["silo_config.silo_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_silo_created",
        "audit_events",
        ["silo_id", "created_at"],
    )
    op.create_index(
        "ix_audit_events_actor_created",
        "audit_events",
        ["actor_id", "created_at"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order.
    op.drop_index("ix_audit_events_actor_created", table_name="audit_events")
    op.drop_index("ix_audit_events_silo_created", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_events_expires_at_partial", table_name="events")
    op.drop_index("ix_events_silo_type_created", table_name="events")
    op.drop_table("events")

    op.drop_table("orphaned_chains")

    op.drop_index("ix_reasoning_chain_steps_silo_id", table_name="reasoning_chain_steps")
    op.drop_table("reasoning_chain_steps")

    op.drop_table("silo_config")
    op.drop_table("org_preferences")
