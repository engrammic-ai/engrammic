"""add beacon tables

Revision ID: 0006
Revises: 0005_add_silo_source_rules
Create Date: 2026-05-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str = "0005_add_silo_source_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # beacon_secrets: maps shared secrets to silos
    op.create_table(
        "beacon_secrets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column("secret", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("silo_id"),
        sa.UniqueConstraint("secret"),
    )
    op.create_index("idx_beacon_secrets_secret", "beacon_secrets", ["secret"])

    # beacon_events: stores received telemetry
    op.create_table(
        "beacon_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_beacon_silo_time", "beacon_events", ["silo_id", "received_at"])


def downgrade() -> None:
    op.drop_index("idx_beacon_silo_time", table_name="beacon_events")
    op.drop_table("beacon_events")
    op.drop_index("idx_beacon_secrets_secret", table_name="beacon_secrets")
    op.drop_table("beacon_secrets")
