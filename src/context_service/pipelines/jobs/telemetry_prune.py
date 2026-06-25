"""Dagster job for telemetry data retention pruning."""

from __future__ import annotations

import asyncio

import asyncpg
import dagster as dg


async def _prune_table(database_url: str, query: str) -> int:
    """Execute a DELETE query and return row count."""
    # ponytail: fresh connection per query - these run daily, no need for pool complexity
    conn = await asyncpg.connect(database_url)
    try:
        result = await conn.execute(query)
        return int(result.split()[-1]) if result else 0
    finally:
        await conn.close()


@dg.op(required_resource_keys={"postgres"})
def prune_service_metrics(context) -> int:
    """Delete service_metrics older than 90 days."""
    deleted = asyncio.run(
        _prune_table(
            context.resources.postgres.database_url,
            "DELETE FROM service_metrics WHERE bucket < now() - INTERVAL '90 days'",
        )
    )
    context.log.info(f"prune_service_metrics: deleted={deleted}")
    return deleted


@dg.op(required_resource_keys={"postgres"})
def prune_service_errors(context) -> int:
    """Delete expired service_errors."""
    deleted = asyncio.run(
        _prune_table(
            context.resources.postgres.database_url,
            "DELETE FROM service_errors WHERE expires_at < now()",
        )
    )
    context.log.info(f"prune_service_errors: deleted={deleted}")
    return deleted


@dg.op(required_resource_keys={"postgres"})
def prune_service_gauges(context) -> int:
    """Delete service_gauges older than 1 year."""
    deleted = asyncio.run(
        _prune_table(
            context.resources.postgres.database_url,
            "DELETE FROM service_gauges WHERE measured_at < now() - INTERVAL '1 year'",
        )
    )
    context.log.info(f"prune_service_gauges: deleted={deleted}")
    return deleted


@dg.op(required_resource_keys={"postgres"})
def prune_beacon_events(context) -> int:
    """Delete beacon_events older than 90 days."""
    deleted = asyncio.run(
        _prune_table(
            context.resources.postgres.database_url,
            "DELETE FROM beacon_events WHERE received_at < now() - INTERVAL '90 days'",
        )
    )
    context.log.info(f"prune_beacon_events: deleted={deleted}")
    return deleted


@dg.job(name="telemetry_prune", tags={"schedule_type": "maintenance"})
def telemetry_prune_job() -> None:
    """Daily retention pruning for telemetry tables."""
    prune_service_metrics()
    prune_service_errors()
    prune_service_gauges()
    prune_beacon_events()
