"""Conclusion consolidation for multi-writer reasoning chains.

When multiple agents reach conclusions for the same query context hash, this
module merges them into a single canonical conclusion, applying an agreement
confidence boost and creating CONSOLIDATES graph edges.

Redis locks prevent races when multiple custodian workers process the same
silo concurrently. The consolidate_by_hash method is idempotent: if any
conclusion in the group already has status='consolidated', the pass is skipped.

repair_orphaned_consolidations handles the crash-recovery case where a
canonical was written but the mark-consolidated step was interrupted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = get_logger(__name__)


class ConclusionStore(Protocol):
    """Subset of HyperGraphStore covering Conclusion operations.

    Defined here so consolidation.py can be type-checked without requiring
    the full HyperGraphStore protocol to declare Conclusion methods.
    Implementors (MemgraphStore) must satisfy this interface.
    """

    async def get_conclusions_by_hash(
        self, silo_id: str, query_context_hash: str
    ) -> list[dict[str, Any]]: ...

    async def upsert_conclusion(
        self,
        *,
        id: str,
        silo_id: str,
        query_context_hash: str,
        content: str,
        confidence: float,
        status: str,
        created_by_agent_id: str,
    ) -> None: ...

    async def create_consolidates_edge(
        self, canonical_id: str, original_id: str
    ) -> None: ...

    async def mark_conclusion_consolidated(self, conclusion_id: str) -> None: ...

    async def find_orphaned_active_conclusions(
        self, silo_id: str
    ) -> list[str]: ...

_LOCK_TTL_SECONDS = 10
_AGREEMENT_BOOST_PER_EXTRA = 0.02
_MAX_AGREEMENT_BOOST = 0.1


class ConclusionConsolidator:
    """Consolidates multiple :Conclusion nodes into canonical form.

    Arguments:
        memgraph: HyperGraphStore providing Conclusion read/write methods.
        redis: Redis client used to acquire per-(silo, hash) locks.
    """

    def __init__(self, memgraph: ConclusionStore, redis: Redis) -> None:
        self._mg = memgraph
        self._redis = redis

    async def consolidate_by_hash(
        self, silo_id: str, query_context_hash: str
    ) -> str | None:
        """Consolidate conclusions with matching (silo_id, query_context_hash).

        Returns the canonical conclusion ID when consolidation occurred, or
        None when there was nothing to consolidate.

        The method acquires a Redis lock keyed to (silo_id, hash) to prevent
        concurrent workers from producing duplicate canonicals.
        """
        lock_key = f"consolidation:{silo_id}:{query_context_hash}"

        async with self._redis.lock(lock_key, timeout=_LOCK_TTL_SECONDS):
            conclusions = await self._mg.get_conclusions_by_hash(
                silo_id, query_context_hash
            )

            # Idempotency guard: skip if consolidation was already started.
            if any(c.get("status") == "consolidated" for c in conclusions):
                log.info(
                    "consolidation_skipped_idempotent",
                    silo_id=silo_id,
                    hash=query_context_hash,
                )
                return None

            active = [c for c in conclusions if c.get("status") == "active"]

            if len(active) < 2:
                return None

            return await self._create_canonical(silo_id, query_context_hash, active)

    async def _create_canonical(
        self,
        silo_id: str,
        query_context_hash: str,
        originals: list[dict[str, Any]],
    ) -> str:
        """Create a canonical conclusion from a set of active originals.

        Confidence is the average of the originals plus an agreement boost
        (capped at 1.0) that rewards convergence: more originals agreeing
        yields a higher boost, up to _MAX_AGREEMENT_BOOST.
        """
        canonical_id = str(uuid4())

        avg_confidence = sum(c["confidence"] for c in originals) / len(originals)
        agreement_boost = min(
            _MAX_AGREEMENT_BOOST,
            _AGREEMENT_BOOST_PER_EXTRA * len(originals),
        )
        merged_confidence = min(1.0, avg_confidence + agreement_boost)

        best = max(originals, key=lambda c: c["confidence"])

        await self._mg.upsert_conclusion(
            id=canonical_id,
            silo_id=silo_id,
            query_context_hash=query_context_hash,
            content=best["content"],
            confidence=merged_confidence,
            status="active",
            created_by_agent_id="custodian:consolidation",
        )

        for orig in originals:
            await self._mg.create_consolidates_edge(canonical_id, orig["id"])
            await self._mg.mark_conclusion_consolidated(orig["id"])

        log.info(
            "consolidation_complete",
            canonical_id=canonical_id,
            original_count=len(originals),
            merged_confidence=merged_confidence,
        )

        return canonical_id

    async def repair_orphaned_consolidations(self, silo_id: str) -> int:
        """Find and repair active conclusions with CONSOLIDATES edges.

        This handles crash-recovery: the canonical was written but the
        mark-consolidated step was interrupted mid-loop.

        Returns the count of repaired (re-marked) conclusions.
        """
        orphaned_ids: list[str] = await self._mg.find_orphaned_active_conclusions(
            silo_id
        )

        for conclusion_id in orphaned_ids:
            await self._mg.mark_conclusion_consolidated(conclusion_id)

        if orphaned_ids:
            log.info(
                "orphan_repair_complete",
                silo_id=silo_id,
                repaired=len(orphaned_ids),
            )

        return len(orphaned_ids)


__all__ = ["ConclusionConsolidator"]
