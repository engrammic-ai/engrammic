"""merge heads 0016 and d441746be43d

Revision ID: 42f64ba6df17
Revises: 0016, d441746be43d
Create Date: 2026-06-12 17:16:42.968601

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '42f64ba6df17'
down_revision: Union[str, Sequence[str], None] = ('0016', 'd441746be43d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
