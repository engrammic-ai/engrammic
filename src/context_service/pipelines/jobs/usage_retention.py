# src/context_service/pipelines/jobs/usage_retention.py
"""ToolUsage retention Dagster job.

Deletes ToolUsage rows older than the configured retention period.
Disabled by default; enable via settings.usage.retention_enabled.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from dagster import job, op, schedule
from sqlalchemy import delete
from sqlalchemy.engine import CursorResult

from context_service.config.settings import get_settings
from context_service.db.postgres import get_session
from context_service.models.postgres.usage import ToolUsage

log = structlog.get_logger(__name__)


@op
def delete_old_usage(context) -> dict[str, object]:
    """Delete ToolUsage rows older than retention period."""
    settings = get_settings()
    usage_cfg = settings.usage

    if not usage_cfg.retention_enabled:
        context.log.info("Usage retention disabled, skipping")
        return {"deleted": 0, "skipped": True}

    retention_days = usage_cfg.retention_days
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    async def _delete() -> int:
        async with get_session() as session:
            cursor: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
                delete(ToolUsage).where(ToolUsage.called_at < cutoff)
            )
            await session.commit()
            return cursor.rowcount

    deleted = asyncio.run(_delete())
    log.info("usage_retention_completed", deleted=deleted, retention_days=retention_days)
    context.log.info(f"Deleted {deleted} ToolUsage rows older than {retention_days} days")
    return {"deleted": deleted, "skipped": False}


@job
def usage_retention_job():
    """Delete old ToolUsage rows based on retention config."""
    delete_old_usage()


@schedule(cron_schedule="0 3 * * *", job=usage_retention_job)
def usage_retention_schedule(context):
    """Daily at 3am; job checks if retention is enabled before acting."""
    return {}
