"""add oauth tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # oauth_authorization_requests: PKCE state storage
    op.create_table(
        "oauth_authorization_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("state", sa.String(255), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column(
            "code_challenge_method",
            sa.String(10),
            server_default=sa.text("'S256'"),
            nullable=False,
        ),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("workos_state", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state"),
    )
    op.create_index("ix_oauth_auth_requests_workos_state", "oauth_authorization_requests", ["workos_state"])

    # oauth_authorization_codes: single-use authorization codes
    op.create_table(
        "oauth_authorization_codes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("code", sa.String(255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "authorization_request_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["authorization_request_id"], ["oauth_authorization_requests.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    # oauth_tokens: access and refresh tokens (stored as hashes)
    op.create_table(
        "oauth_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_token_hash", sa.String(64), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("client_name", sa.String(255), nullable=True),
        sa.Column(
            "access_token_expires_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oauth_tokens_user_id", "oauth_tokens", ["user_id"])
    op.create_index(
        "ix_oauth_tokens_access_token_hash", "oauth_tokens", ["access_token_hash"]
    )
    op.create_index(
        "ix_oauth_tokens_refresh_token_hash", "oauth_tokens", ["refresh_token_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_oauth_tokens_refresh_token_hash", table_name="oauth_tokens")
    op.drop_index("ix_oauth_tokens_access_token_hash", table_name="oauth_tokens")
    op.drop_index("ix_oauth_tokens_user_id", table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_authorization_codes")
    op.drop_index("ix_oauth_auth_requests_workos_state", table_name="oauth_authorization_requests")
    op.drop_table("oauth_authorization_requests")
