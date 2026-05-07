"""Heat cursor: a :HeatCursor singleton per silo in Memgraph.

Tracks the last Redis stream entry ID consumed by the heat Dagster asset so
each hourly run only processes new access events (not the full stream).

The cursor is stored as a Memgraph node rather than Redis so it survives
Redis flushes and is co-located with the heat_score properties it governs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from neo4j import AsyncTransaction

    from context_service.engine.raw_cypher import RawCypherMixin

logger = structlog.get_logger(__name__)

_INITIAL_CURSOR = "0-0"

_FETCH_OR_INIT_CURSOR = """
MERGE (c:HeatCursor {silo_id: $silo_id})
ON CREATE SET c.last_id = $initial_id, c.created_at = $now
RETURN c.last_id AS last_id
"""

_ADVANCE_CURSOR = """
MATCH (c:HeatCursor {silo_id: $silo_id})
SET c.last_id = $last_id, c.updated_at = $now
"""


async def fetch_or_init_heat_cursor(
    memgraph: RawCypherMixin,
    silo_id: str,
) -> str:
    """Return the cursor's last-consumed stream entry ID, creating it if absent.

    On first call for a silo the cursor is initialised to ``'0-0'``, which
    causes the heat asset to read from the beginning of the stream.

    Args:
        memgraph: HyperGraphStore instance.
        silo_id: Silo to look up.

    Returns:
        Redis stream entry ID string (e.g. ``'1234567890-0'`` or ``'0-0'``).
    """
    now = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = await memgraph.execute_query(
        _FETCH_OR_INIT_CURSOR,
        {"silo_id": silo_id, "initial_id": _INITIAL_CURSOR, "now": now},
    )
    last_id: str = rows[0]["last_id"] if rows else _INITIAL_CURSOR
    logger.debug("heat_cursor_fetched", silo_id=silo_id, last_id=last_id)
    return last_id


async def advance_heat_cursor(
    memgraph: RawCypherMixin,
    silo_id: str,
    new_cursor: str,
    *,
    tx: AsyncTransaction | None = None,
) -> None:
    """Atomically advance the :HeatCursor to ``new_cursor``.

    When ``tx`` is provided the write is folded into that transaction so the
    cursor advance and the heat-score writes commit together. When ``tx`` is
    None a standalone write is issued via ``memgraph.execute_write``.

    Args:
        memgraph: HyperGraphStore instance.
        silo_id: Silo whose cursor to advance.
        new_cursor: New last-consumed stream entry ID.
        tx: Optional bound transaction (AsyncTransaction). The tx path calls
            tx.run() directly, which is outside the HyperGraphStore protocol.
            DEBT: callers currently never pass tx; if this path is ever
            activated, migrate to store.transaction() instead.
    """
    now = datetime.now(UTC).isoformat()
    params: dict[str, Any] = {"silo_id": silo_id, "last_id": new_cursor, "now": now}
    if tx is not None:
        # DEBT(protocol-migration): tx.run() is a raw neo4j call, not on
        # HyperGraphStore. Migrate to store.transaction() when this path is
        # activated. Tracked in context/plans/v1.2b-protocol-migration.md.
        result = await tx.run(_ADVANCE_CURSOR, params)
        await result.consume()
    else:
        await memgraph.execute_write(_ADVANCE_CURSOR, params)
    logger.debug("heat_cursor_advanced", silo_id=silo_id, new_cursor=new_cursor)


__all__ = ["advance_heat_cursor", "fetch_or_init_heat_cursor"]
