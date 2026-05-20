"""add erasure_audit_log table for GDPR compliance

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-21

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erasure_audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("silo_id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("requester_type", sa.Text(), nullable=False),
        sa.Column("requester_id", sa.Text(), nullable=True),
        sa.Column(
            "node_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "cascade_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "error_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_erasure_audit_log_silo_id", "erasure_audit_log", ["silo_id"])
    op.create_index("ix_erasure_audit_log_request_id", "erasure_audit_log", ["request_id"])
    op.create_index("ix_erasure_audit_log_requested_at", "erasure_audit_log", ["requested_at"])


def downgrade() -> None:
    op.drop_index("ix_erasure_audit_log_requested_at", table_name="erasure_audit_log")
    op.drop_index("ix_erasure_audit_log_request_id", table_name="erasure_audit_log")
    op.drop_index("ix_erasure_audit_log_silo_id", table_name="erasure_audit_log")
    op.drop_table("erasure_audit_log")
