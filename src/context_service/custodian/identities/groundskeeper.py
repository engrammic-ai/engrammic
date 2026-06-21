from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from context_service.config.logging import get_logger
from context_service.retention.dead_letter import enqueue_failed_delete

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.engine.qdrant_store import EngineQdrantStore

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
    decay_config: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    """Find Memory-layer nodes past their hard_delete threshold."""
    expired = []
    now = datetime.now(UTC)

    for decay_class, config in decay_config.items():
        if config is None:
            continue
        hard_delete_days_val = config.get("hard_delete_days", 9999)
        hard_delete_days = (
            float(str(hard_delete_days_val)) if hard_delete_days_val is not None else 9999.0
        )
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
    decay_config: dict[str, dict[str, object]]
    qdrant_store: EngineQdrantStore | None = field(default=None)

    async def _delete_qdrant_vectors(self, node_ids: list[str]) -> int:
        """Delete vectors from Qdrant. Returns count of failures (dead-lettered)."""
        if self.qdrant_store is None:
            return 0

        failed = 0
        for node_id in node_ids:
            try:
                node_uuid = UUID(node_id)
            except ValueError:
                logger.warning("groundskeeper.invalid_node_id", node_id=node_id)
                failed += 1
                continue

            last_error = ""
            for attempt in range(3):
                try:
                    await self.qdrant_store.delete(
                        node_id=node_uuid,
                        silo_id=self.silo_id,
                    )
                    last_error = ""
                    break
                except Exception as exc:
                    last_error = str(exc)
                    logger.warning(
                        "groundskeeper.qdrant_delete_retry",
                        node_id=node_id,
                        attempt=attempt + 1,
                        error=last_error,
                    )

            if last_error:
                await enqueue_failed_delete(self.silo_id, node_id, last_error)
                failed += 1

        return failed

    async def run_gc(self) -> dict[str, object]:
        """Run garbage collection for expired Memory nodes (T9).

        Deletes from Qdrant first (with retry + dead letter), then Memgraph.
        """
        expired = await get_expired_memory_nodes(self.store, self.silo_id, self.decay_config)

        if not expired:
            return {"deleted": 0, "qdrant_failed": 0, "silo_id": self.silo_id}

        node_ids = [str(r["node_id"]) for r in expired]

        # Delete from Qdrant first (failures go to dead letter queue)
        qdrant_failed = await self._delete_qdrant_vectors(node_ids)

        # Delete from Memgraph
        await self.store.execute_write(
            DELETE_NODES_QUERY,
            {"node_ids": node_ids, "silo_id": self.silo_id},
        )

        logger.info(
            "groundskeeper.gc_complete",
            silo_id=self.silo_id,
            deleted=len(node_ids),
            qdrant_failed=qdrant_failed,
            identity="groundskeeper",
        )

        return {"deleted": len(node_ids), "qdrant_failed": qdrant_failed, "silo_id": self.silo_id}

    async def run_hyperedge_dedup(self) -> dict[str, object]:
        """Deduplicate exact-match hyperedges. Lossless."""
        # TODO: Implement content-addressed dedup via MERGE
        return {"deduped": 0, "silo_id": self.silo_id}
