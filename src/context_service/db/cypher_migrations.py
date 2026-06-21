"""Memgraph Cypher migration runner.

Applies Cypher DDL and data backfill statements to Memgraph. These are
separate from Alembic (which manages Postgres only).

Run via the admin CLI or on startup for idempotent DDL.

Usage:
    uv run python -m context_service.db.cypher_migrations
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from context_service.db.queries import (
    BACKFILL_ACTIVE_STATE,
    BACKFILL_SUPERSEDED_STATE,
)

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

# Ordered list of backfill statements: superseded first, then active.
# Running these is safe to repeat — already-set states are unchanged by the
# WHERE predicates in each query.
STATUS_BACKFILL_QUERIES: tuple[str, ...] = (
    BACKFILL_SUPERSEDED_STATE,
    BACKFILL_ACTIVE_STATE,
)


async def apply_status_backfill(client: HyperGraphStore) -> None:
    """Backfill properties.state on Memgraph nodes from SUPERSEDES edges.

    Step 1: nodes targeted by a SUPERSEDES edge that are still ACTIVE become
            SUPERSEDED.
    Step 2: nodes with no state set (NULL) become ACTIVE.

    Both steps are idempotent — safe to rerun.
    """
    logger.info("applying_status_backfill", query_count=len(STATUS_BACKFILL_QUERIES))
    applied = 0
    async with client.session() as session:
        for statement in STATUS_BACKFILL_QUERIES:
            try:
                result = await session.run(statement)
                await result.consume()
                applied += 1
                logger.info("status_backfill_step_applied", step=applied)
            except Exception as exc:
                logger.warning("status_backfill_step_failed", step=applied + 1, error=str(exc))
    logger.info("status_backfill_complete", applied=applied, total=len(STATUS_BACKFILL_QUERIES))


async def _main() -> None:
    """Entry point for running migrations directly."""
    from context_service.config.settings import get_settings
    from context_service.engine.memgraph_store import MemgraphStore

    settings = get_settings()
    bolt_uri = settings.infra.memgraph.bolt_uri
    store = MemgraphStore(bolt_uri)
    await apply_status_backfill(store)


if __name__ == "__main__":
    asyncio.run(_main())
