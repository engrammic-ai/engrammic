"""add preset column to silo_config

Revision ID: 0002_add_silo_config_preset
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_silo_config_preset"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "silo_config",
        sa.Column("preset", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("silo_config", "preset")
