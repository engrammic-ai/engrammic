"""add skills table

Revision ID: 385b53d0c0c0
Revises: a1b2c3d4e5f6
Create Date: 2026-05-08 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "385b53d0c0c0"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("allowed_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="user"),
        sa.Column("version", sa.String(20), nullable=False, server_default="1.0.0"),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_skills_name"), "skills", ["name"], unique=True)
    op.create_index(op.f("ix_skills_silo_id"), "skills", ["silo_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_skills_silo_id"), table_name="skills")
    op.drop_index(op.f("ix_skills_name"), table_name="skills")
    op.drop_table("skills")
