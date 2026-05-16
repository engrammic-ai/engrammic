"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-15 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # silo_tag_configs
    op.create_table(
        "silo_tag_configs",
        sa.Column("silo_id", sa.Uuid(), nullable=False),
        sa.Column(
            "core_tags",
            postgresql.ARRAY(sa.String()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "dynamic_tags",
            postgresql.ARRAY(sa.String()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("silo_id"),
    )

    # org_preferences
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

    # silo_config (FK to org_preferences)
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

    # reasoning_chain_steps (FK to silo_config)
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

    # orphaned_chains (dead-letter, no FK)
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

    # events (FK to silo_config)
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

    # audit_events (FK to silo_config)
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

    # skills
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("allowed_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="user"),
        sa.Column("version", sa.String(20), nullable=False, server_default="1.0.0"),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skills_name_silo", "skills", ["name", "silo_id"], unique=True)
    op.create_index("ix_skills_silo_id", "skills", ["silo_id"], unique=False)

    # chain_delivery
    op.create_table(
        "chain_delivery",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column(
            "delivered_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_chain_delivery_session_id", "chain_delivery", ["session_id"])
    op.create_index("ix_chain_delivery_delivered_at", "chain_delivery", ["delivered_at"])

    # chain_feedback
    op.create_table(
        "chain_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_chain_feedback_chain_id", "chain_feedback", ["chain_id"])

    # session_step_embedding
    op.create_table(
        "session_step_embedding",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hypothesis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_session_step_embedding_session_id",
        "session_step_embedding",
        ["session_id"],
    )
    op.create_index(
        "ix_session_step_embedding_hypothesis_id",
        "session_step_embedding",
        ["hypothesis_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_session_step_embedding_hypothesis_id", table_name="session_step_embedding")
    op.drop_index("ix_session_step_embedding_session_id", table_name="session_step_embedding")
    op.drop_table("session_step_embedding")

    op.drop_index("ix_chain_feedback_chain_id", table_name="chain_feedback")
    op.drop_table("chain_feedback")

    op.drop_index("ix_chain_delivery_delivered_at", table_name="chain_delivery")
    op.drop_index("ix_chain_delivery_session_id", table_name="chain_delivery")
    op.drop_table("chain_delivery")

    op.drop_index("ix_skills_silo_id", table_name="skills")
    op.drop_index("ix_skills_name_silo", table_name="skills")
    op.drop_table("skills")

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
    op.drop_table("silo_tag_configs")
