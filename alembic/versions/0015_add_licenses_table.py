"""add licenses table for self-hosted license management

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: str = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "licenses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("customer_id", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="active",
        ),
        sa.Column("tier", sa.Text(), nullable=False, server_default="self-hosted"),
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("subscription_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_renewal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("renewal_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'revoked', 'expired')",
            name="ck_licenses_status",
        ),
    )
    op.create_index("ix_licenses_customer_id", "licenses", ["customer_id"], unique=True)
    op.create_index("ix_licenses_status", "licenses", ["status"])


def downgrade() -> None:
    op.drop_index("ix_licenses_status", table_name="licenses")
    op.drop_index("ix_licenses_customer_id", table_name="licenses")
    op.drop_table("licenses")
