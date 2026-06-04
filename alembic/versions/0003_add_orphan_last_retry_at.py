"""add orphan last_retry_at

Revision ID: 0003_add_orphan_last_retry_at
Revises: 0002_add_silo_config_preset
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_add_orphan_last_retry_at"
down_revision: str | None = "0002_add_silo_config_preset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orphaned_chains",
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orphaned_chains", "last_retry_at")
