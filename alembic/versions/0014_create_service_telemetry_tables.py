"""create service telemetry tables

Revision ID: 0014
Revises: 0013_seed_hosted_beacon_secret
Create Date: 2026-05-27

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str = "0013_seed_hosted_beacon_secret"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_metrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_sum_ms", sa.Float, nullable=False, server_default="0"),
        sa.Column("latency_p50_ms", sa.Float, nullable=True),
        sa.Column("latency_p95_ms", sa.Float, nullable=True),
        sa.Column("latency_max_ms", sa.Float, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bucket", "silo_id", "metric_name"),
    )
    op.create_index("idx_service_metrics_bucket", "service_metrics", ["bucket"])
    op.create_index("idx_service_metrics_silo_bucket", "service_metrics", ["silo_id", "bucket"])
    op.create_index("idx_service_metrics_metric_bucket", "service_metrics", ["metric_name", "bucket"])

    op.create_table(
        "service_errors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column("error_type", sa.String(200), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("tool_name", sa.String(100), nullable=True),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now() + INTERVAL '30 days'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_service_errors_occurred", "service_errors", ["occurred_at"])
    op.create_index("idx_service_errors_silo", "service_errors", ["silo_id", "occurred_at"])
    op.create_index("idx_service_errors_type", "service_errors", ["error_type", "occurred_at"])
    op.create_index("idx_service_errors_expires", "service_errors", ["expires_at"])

    op.create_table(
        "service_gauges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "measured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column("node_count_memory", sa.Integer, nullable=True),
        sa.Column("node_count_knowledge", sa.Integer, nullable=True),
        sa.Column("node_count_wisdom", sa.Integer, nullable=True),
        sa.Column("edge_count", sa.Integer, nullable=True),
        sa.Column("qdrant_point_count", sa.Integer, nullable=True),
        sa.Column("qdrant_collection_size_bytes", sa.BigInteger, nullable=True),
        sa.Column("memgraph_vertex_count", sa.Integer, nullable=True),
        sa.Column("memgraph_edge_count", sa.Integer, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("measured_at", "silo_id"),
    )
    op.create_index("idx_service_gauges_silo_time", "service_gauges", ["silo_id", "measured_at"])


def downgrade() -> None:
    op.drop_index("idx_service_gauges_silo_time", table_name="service_gauges")
    op.drop_table("service_gauges")

    op.drop_index("idx_service_errors_expires", table_name="service_errors")
    op.drop_index("idx_service_errors_type", table_name="service_errors")
    op.drop_index("idx_service_errors_silo", table_name="service_errors")
    op.drop_index("idx_service_errors_occurred", table_name="service_errors")
    op.drop_table("service_errors")

    op.drop_index("idx_service_metrics_metric_bucket", table_name="service_metrics")
    op.drop_index("idx_service_metrics_silo_bucket", table_name="service_metrics")
    op.drop_index("idx_service_metrics_bucket", table_name="service_metrics")
    op.drop_table("service_metrics")
