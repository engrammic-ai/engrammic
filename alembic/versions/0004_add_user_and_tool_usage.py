"""add user and tool_usage tables

Revision ID: 0004_add_user_and_tool_usage
Revises: 0003_add_orphan_last_retry_at
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_add_user_and_tool_usage"
down_revision: str | None = "0003_add_orphan_last_retry_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workos_user_id", sa.String(length=255), nullable=False),
        sa.Column("org_id", sa.String(length=255), nullable=False),
        sa.Column("silo_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workos_user_id"),
    )
    op.create_index("ix_users_workos_user_id", "users", ["workos_user_id"])
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_silo_id", "users", ["silo_id"])

    op.create_table(
        "tool_usage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("silo_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_usage_user_id", "tool_usage", ["user_id"])
    op.create_index("ix_tool_usage_silo_id", "tool_usage", ["silo_id"])
    op.create_index("ix_tool_usage_user_called", "tool_usage", ["user_id", "called_at"])
    op.create_index("ix_tool_usage_silo_called", "tool_usage", ["silo_id", "called_at"])


def downgrade() -> None:
    op.drop_index("ix_tool_usage_silo_called", table_name="tool_usage")
    op.drop_index("ix_tool_usage_user_called", table_name="tool_usage")
    op.drop_index("ix_tool_usage_silo_id", table_name="tool_usage")
    op.drop_index("ix_tool_usage_user_id", table_name="tool_usage")
    op.drop_table("tool_usage")

    op.drop_index("ix_users_silo_id", table_name="users")
    op.drop_index("ix_users_org_id", table_name="users")
    op.drop_index("ix_users_workos_user_id", table_name="users")
    op.drop_table("users")
