"""Dagster job for telemetry data retention pruning."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Callable
from typing import Any, TypeVar

import dagster as dg

_T = TypeVar("_T")


def _run_async(coro_fn: Callable[[], Any]) -> Any:
    """Run async function, handling both sync and async contexts."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_fn())

    # Already in async context - run in thread to avoid nested run()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        f = pool.submit(lambda: asyncio.run(coro_fn()))
        return f.result(timeout=60)


@dg.op(required_resource_keys={"postgres"})
def prune_service_metrics(context) -> int:
    """Delete service_metrics older than 90 days."""
    from context_service.pipelines.resources import PostgresResource

    postgres: PostgresResource = context.resources.postgres

    async def _run() -> int:
        with postgres.get_pool() as pool:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM service_metrics WHERE bucket < now() - INTERVAL '90 days'"
                )
                count = int(result.split()[-1]) if result else 0
                return count

    deleted: int = _run_async(_run)
    context.log.info(f"prune_service_metrics: deleted={deleted}")
    return deleted


@dg.op(required_resource_keys={"postgres"})
def prune_service_errors(context) -> int:
    """Delete expired service_errors."""
    from context_service.pipelines.resources import PostgresResource

    postgres: PostgresResource = context.resources.postgres

    async def _run() -> int:
        with postgres.get_pool() as pool:
            async with pool.acquire() as conn:
                result = await conn.execute("DELETE FROM service_errors WHERE expires_at < now()")
                count = int(result.split()[-1]) if result else 0
                return count

    deleted: int = _run_async(_run)
    context.log.info(f"prune_service_errors: deleted={deleted}")
    return deleted


@dg.op(required_resource_keys={"postgres"})
def prune_service_gauges(context) -> int:
    """Delete service_gauges older than 1 year."""
    from context_service.pipelines.resources import PostgresResource

    postgres: PostgresResource = context.resources.postgres

    async def _run() -> int:
        with postgres.get_pool() as pool:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM service_gauges WHERE measured_at < now() - INTERVAL '1 year'"
                )
                count = int(result.split()[-1]) if result else 0
                return count

    deleted: int = _run_async(_run)
    context.log.info(f"prune_service_gauges: deleted={deleted}")
    return deleted


@dg.op(required_resource_keys={"postgres"})
def prune_beacon_events(context) -> int:
    """Delete beacon_events older than 90 days."""
    from context_service.pipelines.resources import PostgresResource

    postgres: PostgresResource = context.resources.postgres

    async def _run() -> int:
        with postgres.get_pool() as pool:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM beacon_events WHERE received_at < now() - INTERVAL '90 days'"
                )
                count = int(result.split()[-1]) if result else 0
                return count

    deleted: int = _run_async(_run)
    context.log.info(f"prune_beacon_events: deleted={deleted}")
    return deleted


@dg.job(name="telemetry_prune", tags={"schedule_type": "maintenance"})
def telemetry_prune_job() -> None:
    """Daily retention pruning for telemetry tables."""
    prune_service_metrics()
    prune_service_errors()
    prune_service_gauges()
    prune_beacon_events()
