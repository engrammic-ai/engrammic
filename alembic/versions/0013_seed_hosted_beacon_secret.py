"""seed hosted beacon secret

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-23

Seeds the beacon secret for the hosted Engrammic service.
The secret value comes from HOSTED_BEACON_SECRET env var (set by Pulumi).
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0013"
down_revision: str = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOSTED_SILO_ID = "engrammic-hosted"


def upgrade() -> None:
    secret = os.environ.get("HOSTED_BEACON_SECRET")
    if not secret:
        print("NOTE: HOSTED_BEACON_SECRET not set, skipping beacon secret seed")
        return

    connection = op.get_bind()

    # Upsert: insert or update if exists
    connection.execute(
        text("""
            INSERT INTO beacon_secrets (silo_id, secret)
            VALUES (:silo_id, :secret)
            ON CONFLICT (silo_id) DO UPDATE SET secret = :secret
        """),
        {"silo_id": HOSTED_SILO_ID, "secret": secret},
    )
    print(f"Seeded beacon secret for {HOSTED_SILO_ID}")


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        text("DELETE FROM beacon_secrets WHERE silo_id = :silo_id"),
        {"silo_id": HOSTED_SILO_ID},
    )
