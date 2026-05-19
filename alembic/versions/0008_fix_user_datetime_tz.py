"""Fix User model datetime columns to use timezone-aware types.

Revision ID: 0008
Revises: 0007_add_oauth_tables
Create Date: 2026-05-19

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE
        USING created_at AT TIME ZONE 'UTC'
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ALTER COLUMN last_active_at TYPE TIMESTAMP WITH TIME ZONE
        USING last_active_at AT TIME ZONE 'UTC'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ALTER COLUMN last_active_at TYPE TIMESTAMP WITHOUT TIME ZONE
        """
    )
