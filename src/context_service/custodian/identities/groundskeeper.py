from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import TYPE_CHECKING

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = get_logger(__name__)

EXPIRED_MEMORY_QUERY = """
MATCH (n:Passage|Utterance|Event {silo_id: $silo_id})
WHERE n.decay_class = $decay_class
  AND n.created_at < $cutoff
RETURN n.id AS node_id, n.decay_class AS decay_class, n.created_at AS created_at
LIMIT 1000
"""

DELETE_NODES_QUERY = """
MATCH (n)
WHERE n.id IN $node_ids AND n.silo_id = $silo_id
DETACH DELETE n
"""


async def get_expired_memory_nodes(
    store: HyperGraphStore,
    silo_id: str,
    decay_config: dict[str, dict],
) -> list[dict]:
    """Find Memory-layer nodes past their hard_delete threshold."""
    expired = []
    now = datetime.now(UTC)

    for decay_class, config in decay_config.items():
        if config is None:
            continue
        hard_delete_days = config.get("hard_delete_days", 9999)
        cutoff = now - timedelta(days=hard_delete_days)

        rows = await store.execute_query(
            EXPIRED_MEMORY_QUERY,
            {"silo_id": silo_id, "decay_class": decay_class, "cutoff": cutoff.isoformat()},
        )
        expired.extend(rows)

    return expired


@dataclass
class GroundskeeperIdentity:
    """Memory lifecycle management. No LLM - deterministic operations."""

    store: HyperGraphStore
    silo_id: str
    decay_config: dict[str, dict]

    async def run_gc(self) -> dict:
        """Run garbage collection for expired Memory nodes (T9)."""
        expired = await get_expired_memory_nodes(
            self.store, self.silo_id, self.decay_config
        )

        if not expired:
            return {"deleted": 0, "silo_id": self.silo_id}

        node_ids = [r["node_id"] for r in expired]
        await self.store.execute_write(
            DELETE_NODES_QUERY,
            {"node_ids": node_ids, "silo_id": self.silo_id},
        )

        logger.info(
            "groundskeeper.gc_complete",
            silo_id=self.silo_id,
            deleted=len(node_ids),
            identity="groundskeeper",
        )

        return {"deleted": len(node_ids), "silo_id": self.silo_id}

    async def run_hyperedge_dedup(self) -> dict:
        """Deduplicate exact-match hyperedges. Lossless."""
        # TODO: Implement content-addressed dedup via MERGE
        return {"deduped": 0, "silo_id": self.silo_id}
