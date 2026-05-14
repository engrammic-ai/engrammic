"""merge_skills_and_chain_feedback_branches

Revision ID: 138ad226813b
Revises: 385b53d0c0c0, c3d4e5f6g7h8
Create Date: 2026-05-12 11:33:34.466667

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '138ad226813b'
down_revision: str | Sequence[str] | None = ('385b53d0c0c0', 'c3d4e5f6g7h8')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
