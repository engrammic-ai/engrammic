"""Edge access event emission for the edge_heat asset.

Each graph traversal (depth > 0) calls ``emit_edge_access_event`` when an edge
is followed. Events land on a per-silo Redis stream which the edge_heat Dagster
asset drains to compute decay-weighted heat scores for edges.

Best-effort: Redis errors are logged and swallowed so broken Redis never blocks reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import NAMESPACE_DNS, uuid5

import structlog

if TYPE_CHECKING:
    from context_service.stores import RedisClient

logger = structlog.get_logger(__name__)

EDGE_ACCESS_STREAM_MAXLEN = 100_000


def edge_access_stream_key(silo_id: str) -> str:
    """Build the per-silo edge access event stream key."""
    return f"silo:{silo_id}:edge_access_events"


def edge_id(from_node: str, to_node: str, edge_type: str) -> str:
    """Deterministic edge ID from sorted node pair and edge type.

    Sorting ensures the same ID regardless of traversal direction.
    """
    pair = tuple(sorted([from_node, to_node]))
    return str(uuid5(NAMESPACE_DNS, f"{pair[0]}:{pair[1]}:{edge_type}"))


async def emit_edge_access_event(
    redis: RedisClient,
    silo_id: str,
    from_node: str,
    to_node: str,
    edge_type: str,
    traversal_context: str = "recall",
) -> None:
    """Append an edge access event to the silo stream. Best-effort, never raises.

    Failures are logged and swallowed so callers in MCP read paths do not need
    a try/except around every emit.

    Args:
        redis: Redis client for stream operations.
        silo_id: Silo the edge belongs to.
        from_node: Source node ID.
        to_node: Target node ID.
        edge_type: Edge type label (e.g. "RELATED_TO").
        traversal_context: Context hint ("recall", "provenance", "graph").
    """
    try:
        eid = edge_id(from_node, to_node, edge_type)
        await redis.xadd(
            edge_access_stream_key(silo_id),
            {
                "edge_id": eid,
                "from_node": from_node,
                "to_node": to_node,
                "edge_type": edge_type,
                "context": traversal_context,
            },
            maxlen=EDGE_ACCESS_STREAM_MAXLEN,
            approximate=True,
        )
    except Exception as exc:
        logger.warning(
            "edge_access_event_emit_failed",
            silo_id=silo_id,
            from_node=from_node,
            to_node=to_node,
            edge_type=edge_type,
            error=str(exc),
        )


__all__ = [
    "EDGE_ACCESS_STREAM_MAXLEN",
    "edge_access_stream_key",
    "edge_id",
    "emit_edge_access_event",
]
