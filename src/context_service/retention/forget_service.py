"""Agent-driven forget operations with cancel window."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


FORGET_NODE = """
MATCH (n {id: $id, silo_id: $silo_id})
WHERE n.tombstoned_at IS NULL
SET n.tombstoned_at = $tombstoned_at,
    n.forget_requested_at = $forget_requested_at,
    n.heat_dirty = true
WITH n
OPTIONAL MATCH (other)-[]->(n)
WHERE other.tombstoned_at IS NULL
RETURN n.id AS id, count(other) AS downstream_count
"""

CANCEL_FORGET = """
MATCH (n {id: $id, silo_id: $silo_id})
WHERE n.forget_requested_at IS NOT NULL
  AND n.forget_requested_at > $cancel_cutoff
SET n.tombstoned_at = NULL,
    n.forget_requested_at = NULL,
    n.retention_run_id = NULL,
    n.heat_dirty = true
RETURN n.id AS id
"""

CHECK_NODE_EXISTS = """
MATCH (n {id: $id, silo_id: $silo_id})
RETURN n.forget_requested_at AS requested_at
"""


class ForgetService:
    """Handle agent-driven forget operations.

    Tombstones are set in the graph (Memgraph) which is the source of truth.
    Qdrant sync is NOT done here - tombstoned nodes are filtered at query time
    and eventually hard-deleted by the retention GC job.
    """

    def __init__(
        self,
        store: HyperGraphStore,
        cancel_window_hours: int = 1,
    ) -> None:
        self._store = store
        self._cancel_window_hours = cancel_window_hours

    async def forget(
        self,
        node_id: str,
        silo_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Tombstone a node. Returns downstream reference count."""
        now = datetime.now(UTC)
        now_iso = now.isoformat()

        result = await self._store.execute_write(
            FORGET_NODE,
            {
                "id": node_id,
                "silo_id": silo_id,
                "tombstoned_at": now_iso,
                "forget_requested_at": now_iso,
            },
        )

        if not result:
            return {"status": "not_found", "node_id": node_id}

        downstream = result[0].get("downstream_count", 0)

        logger.info(
            "node_forgotten",
            node_id=node_id,
            silo_id=silo_id,
            downstream_references=downstream,
            reason=reason,
        )

        return {
            "status": "tombstoned",
            "node_id": node_id,
            "downstream_references": downstream,
            "tombstoned_at": now.isoformat(),
        }

    async def cancel_forget(
        self,
        node_id: str,
        silo_id: str,
    ) -> dict[str, Any]:
        """Reverse a forget if within cancel window."""
        now = datetime.now(UTC)
        now_micros = int(now.timestamp() * 1_000_000)
        cancel_cutoff = now_micros - (self._cancel_window_hours * 3600 * 1_000_000)

        # First check if node exists at all
        check_result = await self._store.execute_query(
            CHECK_NODE_EXISTS,
            {"id": node_id, "silo_id": silo_id},
        )
        if not check_result:
            return {"status": "not_found", "node_id": node_id}

        result = await self._store.execute_write(
            CANCEL_FORGET,
            {
                "id": node_id,
                "silo_id": silo_id,
                "cancel_cutoff": cancel_cutoff,
            },
        )

        if not result:
            return {"status": "cancel_window_expired", "node_id": node_id}

        logger.info("forget_cancelled", node_id=node_id, silo_id=silo_id)

        return {
            "status": "cancelled",
            "node_id": node_id,
            "cancelled_at": now.isoformat(),
        }
