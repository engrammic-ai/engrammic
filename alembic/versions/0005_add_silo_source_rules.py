"""add silo_source_rules table

Revision ID: 0005_add_silo_source_rules
Revises: 0004_add_user_and_tool_usage
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_add_silo_source_rules"
down_revision: str | None = "0004_add_user_and_tool_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "silo_source_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("silo_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "tier IN ('authoritative', 'validated', 'community')",
            name="ck_silo_source_rules_tier",
        ),
        sa.ForeignKeyConstraint(["silo_id"], ["silo_config.silo_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("silo_id", "pattern", name="uq_silo_source_rules_silo_pattern"),
    )
    op.create_index("idx_source_rules_silo", "silo_source_rules", ["silo_id"])
    op.create_index(
        "idx_source_rules_priority",
        "silo_source_rules",
        [sa.text("priority DESC")],
    )
    op.execute(
        """
        INSERT INTO silo_source_rules (silo_id, pattern, tier, reason, priority)
        VALUES
            (NULL, 'https://*.gov/*', 'authoritative', 'Government domains', 100),
            (NULL, 'https://*.gov.*/*', 'authoritative', 'Government country TLDs', 100),
            (NULL, 'https://eur-lex.europa.eu/*', 'authoritative', 'EU law', 100),
            (NULL, 'https://*.europa.eu/*', 'authoritative', 'EU institutions', 95),
            (NULL, 'https://courtlistener.com/*', 'authoritative', 'US court records', 90),
            (NULL, 'sec://*', 'authoritative', 'SEC filings', 90),
            (NULL, 'https://*.edu/*', 'validated', 'Educational institutions', 80),
            (NULL, 'pitchbook://*', 'validated', 'PitchBook', 80),
            (NULL, 'bloomberg://*', 'validated', 'Bloomberg', 80),
            (NULL, 'crunchbase://*', 'validated', 'Crunchbase', 75),
            (NULL, 'https://arxiv.org/*', 'validated', 'arXiv preprints', 70),
            (NULL, 'https://linkedin.com/*', 'community', 'LinkedIn (self-reported)', 50),
            (NULL, 'https://medium.com/*', 'community', 'Medium articles', 50),
            (NULL, 'wikipedia://*', 'community', 'Wikipedia', 50)
        """
    )


def downgrade() -> None:
    op.drop_index("idx_source_rules_priority", table_name="silo_source_rules")
    op.drop_index("idx_source_rules_silo", table_name="silo_source_rules")
    op.drop_table("silo_source_rules")
