"""add session step embedding table

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-05-12 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6g7h8"
down_revision: str | None = "b2c3d4e5f6g7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    op.drop_index(
        "ix_session_step_embedding_hypothesis_id",
        table_name="session_step_embedding",
    )
    op.drop_index(
        "ix_session_step_embedding_session_id",
        table_name="session_step_embedding",
    )
    op.drop_table("session_step_embedding")
