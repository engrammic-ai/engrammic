"""add tx7 fields to reasoning_chain_steps

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: str = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reasoning_chain_steps",
        sa.Column("conclusion", sa.String(), nullable=True),
    )
    op.add_column(
        "reasoning_chain_steps",
        sa.Column("conclusion_embedding", postgresql.ARRAY(sa.Float()), nullable=True),
    )
    op.add_column(
        "reasoning_chain_steps",
        sa.Column("agent_id", sa.String(), nullable=True),
    )
    op.add_column(
        "reasoning_chain_steps",
        sa.Column("source_hypothesis_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "reasoning_chain_steps",
        sa.Column("traced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reasoning_chain_steps", "traced_at")
    op.drop_column("reasoning_chain_steps", "source_hypothesis_id")
    op.drop_column("reasoning_chain_steps", "agent_id")
    op.drop_column("reasoning_chain_steps", "conclusion_embedding")
    op.drop_column("reasoning_chain_steps", "conclusion")
