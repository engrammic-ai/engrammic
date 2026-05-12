"""add chain feedback tables

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-12 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6g7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    op.create_index(
        "ix_chain_delivery_session_id", "chain_delivery", ["session_id"]
    )
    op.create_index(
        "ix_chain_delivery_delivered_at", "chain_delivery", ["delivered_at"]
    )

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


def downgrade() -> None:
    op.drop_index("ix_chain_feedback_chain_id", table_name="chain_feedback")
    op.drop_table("chain_feedback")
    op.drop_index("ix_chain_delivery_delivered_at", table_name="chain_delivery")
    op.drop_index("ix_chain_delivery_session_id", table_name="chain_delivery")
    op.drop_table("chain_delivery")
