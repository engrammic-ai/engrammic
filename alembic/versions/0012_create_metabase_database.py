"""create metabase database

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-23

Note: This migration creates a separate database for Metabase app state.
The main engrammic database user needs CREATEDB privilege, or this must
be run by a superuser. In production, the metabase database may be
created via Pulumi/Terraform instead.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0012"
down_revision: str = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create metabase database if it doesn't exist
    # Note: This requires connecting to postgres database, not engrammic
    # In Cloud SQL, we handle this via Pulumi/gcloud instead
    connection = op.get_bind()

    # Check if we can create databases (won't work in most managed envs)
    try:
        # Use raw connection to check for database
        result = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'metabase'")
        )
        if result.fetchone() is None:
            # Can't create database from within a transaction
            # Log instruction for manual creation
            print("NOTE: Create metabase database manually:")
            print("  CREATE DATABASE metabase OWNER context;")
    except Exception:
        print("NOTE: Create metabase database manually:")
        print("  CREATE DATABASE metabase OWNER context;")


def downgrade() -> None:
    # Don't drop the database - too dangerous
    print("NOTE: Drop metabase database manually if needed:")
    print("  DROP DATABASE metabase;")
