"""Access-event emission for the heat asset.

Each MCP read tool calls ``emit_access_event`` after a node is resolved into
user-visible output. Events land on a per-silo Redis stream which the Phase-2
heat Dagster asset drains hourly to compute decay-weighted heat scores.

This is a best-effort signal: Redis errors are logged and swallowed so a
broken Redis never blocks reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from context_service.stores import RedisClient

logger = structlog.get_logger(__name__)

# Stream cap. Approximate trim — at the default cadence (~1h between heat
# asset runs), 100k entries permits ~28 events/sec sustained without loss.
ACCESS_STREAM_MAXLEN = 100_000


def access_stream_key(silo_id: str) -> str:
    """Build the per-silo access-event stream key."""
    return f"silo:{silo_id}:access_events"


async def emit_access_event(
    redis: RedisClient,
    silo_id: str,
    node_id: str,
) -> None:
    """Append an access event to the silo's stream. Best-effort.

    Failures are logged and swallowed — never raised — so callers in MCP read
    paths don't need a try/except around every emit.
    """
    try:
        await redis.xadd(
            access_stream_key(silo_id),
            {"node_id": str(node_id)},
            maxlen=ACCESS_STREAM_MAXLEN,
            approximate=True,
        )
    except Exception as exc:
        logger.warning(
            "access_event_emit_failed",
            silo_id=silo_id,
            node_id=str(node_id),
            error=str(exc),
        )


__all__ = ["ACCESS_STREAM_MAXLEN", "access_stream_key", "emit_access_event"]
