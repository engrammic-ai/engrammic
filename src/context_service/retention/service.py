"""Retention service: find candidates, tombstone, hard delete."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

from context_service.retention.policy import RetentionPolicy
from context_service.retention.queries import (
    FIND_EXCESS_META_OBSERVATIONS,
    FIND_HARD_DELETE_CANDIDATES,
    FIND_ORPHANED_SUMMARIES,
    FIND_TOMBSTONE_CANDIDATES,
    HARD_DELETE_NODE,
    MARK_HEAT_DIRTY,
    TOMBSTONE_NODE,
)

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


class RetentionService:
    """Orchestrates retention sweeps for a silo."""

    def __init__(
        self,
        store: HyperGraphStore,
        policy: RetentionPolicy | None = None,
    ) -> None:
        self._store = store
        self._policy = policy or RetentionPolicy()

    async def find_tombstone_candidates(
        self,
        silo_id: str,
        now: datetime | None = None,
    ) -> list[str]:
        """Find nodes eligible for tombstoning."""
        if now is None:
            now = datetime.now(UTC)

        rows: list[dict[str, Any]] = await self._store.execute_query(
            FIND_TOMBSTONE_CANDIDATES,
            {"silo_id": silo_id},
        )

        eligible_ids: list[str] = []
        for row in rows:
            raw = row.get("created_at")
            if isinstance(raw, str):
                created_at: datetime = datetime.fromisoformat(raw)
            elif isinstance(raw, datetime):
                created_at = raw
            else:
                logger.warning("skipping_node_missing_created_at", node_id=row.get("id"))
                continue

            if self._policy.is_eligible_for_tombstone(
                decay_class=row["decay_class"],
                created_at=created_at,
                heat_score=row["heat_score"],
                now=now,
            ):
                eligible_ids.append(row["id"])

        return eligible_ids

    async def tombstone_nodes(
        self,
        node_ids: list[str],
        silo_id: str,
        run_id: str,
    ) -> int:
        """Tombstone nodes by setting tombstoned_at timestamp."""
        now = datetime.now(UTC)
        count = 0
        tombstoned_ids: list[str] = []

        for node_id in node_ids:
            result = await self._store.execute_query(
                TOMBSTONE_NODE,
                {
                    "id": node_id,
                    "silo_id": silo_id,
                    "tombstoned_at": now.isoformat(),
                    "run_id": run_id,
                },
            )
            if result:
                count += 1
                tombstoned_ids.append(node_id)

        if tombstoned_ids:
            await self._store.execute_query(
                MARK_HEAT_DIRTY,
                {"silo_id": silo_id, "node_ids": tombstoned_ids},
            )

        logger.info("tombstoned_nodes", silo_id=silo_id, count=count, run_id=run_id)
        return count

    async def find_hard_delete_candidates(self, silo_id: str) -> list[str]:
        """Find tombstoned nodes past grace period."""
        grace_cutoff = datetime.now(UTC) - timedelta(days=self._policy.grace_period_days)

        rows: list[dict[str, Any]] = await self._store.execute_query(
            FIND_HARD_DELETE_CANDIDATES,
            {"silo_id": silo_id, "grace_cutoff": grace_cutoff.isoformat()},
        )

        return [row["id"] for row in rows]

    async def hard_delete_nodes(self, node_ids: list[str], silo_id: str) -> int:
        """Permanently delete tombstoned nodes."""
        count = 0
        for node_id in node_ids:
            result = await self._store.execute_query(
                HARD_DELETE_NODE,
                {"id": node_id, "silo_id": silo_id},
            )
            if result:
                count += 1

        logger.info("hard_deleted_nodes", silo_id=silo_id, count=count)
        return count

    async def tombstone_excess_meta_observations(
        self,
        silo_id: str,
        run_id: str,
    ) -> int:
        """Tombstone MetaObservation nodes beyond max count."""
        rows: list[dict[str, Any]] = await self._store.execute_query(
            FIND_EXCESS_META_OBSERVATIONS,
            {"silo_id": silo_id, "keep_count": self._policy.meta_observation_max_count},
        )

        excess_ids = [row["id"] for row in rows]
        if excess_ids:
            return await self.tombstone_nodes(excess_ids, silo_id, run_id)
        return 0

    async def tombstone_orphaned_summaries(self, silo_id: str, run_id: str) -> int:
        """Tombstone Event summaries whose source chains are gone."""
        rows: list[dict[str, Any]] = await self._store.execute_query(
            FIND_ORPHANED_SUMMARIES,
            {"silo_id": silo_id},
        )
        orphan_ids = [row["id"] for row in rows]
        if orphan_ids:
            return await self.tombstone_nodes(orphan_ids, silo_id, run_id)
        return 0

    async def run_sweep(self, silo_id: str) -> dict[str, Any]:
        """Run full retention sweep: tombstone eligible, hard delete expired."""
        run_id = str(uuid4())

        candidates = await self.find_tombstone_candidates(silo_id)
        tombstoned = await self.tombstone_nodes(candidates, silo_id, run_id)

        meta_tombstoned = await self.tombstone_excess_meta_observations(silo_id, run_id)

        orphan_tombstoned = await self.tombstone_orphaned_summaries(silo_id, run_id)

        delete_candidates = await self.find_hard_delete_candidates(silo_id)
        deleted = await self.hard_delete_nodes(delete_candidates, silo_id)

        return {
            "tombstoned": tombstoned,
            "meta_tombstoned": meta_tombstoned,
            "orphan_tombstoned": orphan_tombstoned,
            "deleted": deleted,
            "run_id": run_id,
        }
