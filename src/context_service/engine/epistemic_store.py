# src/context_service/engine/epistemic_store.py
"""MemgraphEpistemicStore - CITE-domain operations over HyperGraphStore."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from context_service.engine import queries

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

log = structlog.get_logger(__name__)


class MemgraphEpistemicStore:
    """EpistemicStore implementation backed by Memgraph via HyperGraphStore."""

    def __init__(self, graph_store: HyperGraphStore) -> None:
        self._store = graph_store

    async def get_fact_cluster(
        self, silo_id: str, cluster_id: str
    ) -> list[dict[str, Any]]:
        """Get all facts in a cluster."""
        return await self._store.execute_query(
            queries.EPISTEMIC_GET_FACT_CLUSTER,
            {"silo_id": silo_id, "cluster_id": cluster_id},
        )

    async def get_unclustered_facts(
        self, silo_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get facts not yet assigned to any cluster."""
        return await self._store.execute_query(
            queries.EPISTEMIC_GET_UNCLUSTERED_FACTS,
            {"silo_id": silo_id, "limit": limit},
        )

    async def create_belief_with_links(
        self,
        silo_id: str,
        content: str,
        fact_ids: list[str],
        confidence: float,
        reasoning: str | None = None,
    ) -> str:
        """Atomically create a belief and link it to source facts."""
        async with self._store.transaction() as tx:
            # Create belief node
            result = await tx.execute_write(
                queries.EPISTEMIC_CREATE_BELIEF,
                {
                    "silo_id": silo_id,
                    "content": content,
                    "confidence": confidence,
                    "reasoning": reasoning,
                },
            )
            belief_id = result[0]["id"]

            # Link to facts
            await tx.execute_write(
                queries.EPISTEMIC_LINK_BELIEF_TO_FACTS,
                {"belief_id": belief_id, "fact_ids": fact_ids, "silo_id": silo_id},
            )
            return str(belief_id)

    async def update_belief_centroid(
        self,
        silo_id: str,
        belief_id: str,
        embedding_client: Any | None = None,
    ) -> None:
        """Update belief's centroid embedding. No-op if embedding_client is None."""
        if embedding_client is None:
            return

        # Fetch belief content
        belief = await self._store.execute_query(
            queries.EPISTEMIC_GET_BELIEF,
            {"silo_id": silo_id, "belief_id": belief_id},
        )
        if not belief:
            log.warning("belief_not_found_for_centroid", belief_id=belief_id)
            return

        # Compute and store embedding
        embedding = await embedding_client.embed(belief[0]["content"])
        await self._store.execute_write(
            queries.EPISTEMIC_UPDATE_BELIEF_CENTROID,
            {"belief_id": belief_id, "centroid": embedding},
        )

    async def find_similar_beliefs(
        self, silo_id: str, content: str, threshold: float = 0.8
    ) -> list[dict[str, Any]]:
        """Find beliefs similar to the given content."""
        return await self._store.execute_query(
            queries.EPISTEMIC_FIND_SIMILAR_BELIEFS,
            {"silo_id": silo_id, "content": content, "threshold": threshold},
        )

    async def check_belief_coverage(
        self, silo_id: str, fact_ids: list[str]
    ) -> dict[str, Any]:
        """Check which facts are covered by existing beliefs."""
        rows = await self._store.execute_query(
            queries.EPISTEMIC_CHECK_BELIEF_COVERAGE,
            {"silo_id": silo_id, "fact_ids": fact_ids},
        )
        return {"coverage": rows}

    async def merge_beliefs(
        self,
        silo_id: str,
        source_belief_ids: list[str],
        merged_content: str,
        fact_ids: list[str],
    ) -> str:
        """Atomically merge beliefs: create merged, link facts, mark sources stale."""
        async with self._store.transaction() as tx:
            # Create merged belief
            result = await tx.execute_write(
                queries.EPISTEMIC_CREATE_MERGED_BELIEF,
                {"silo_id": silo_id, "content": merged_content},
            )
            merged_id = result[0]["id"]

            # Link to facts
            await tx.execute_write(
                queries.EPISTEMIC_LINK_BELIEF_TO_FACTS,
                {"belief_id": merged_id, "fact_ids": fact_ids, "silo_id": silo_id},
            )

            # Link to source beliefs
            await tx.execute_write(
                queries.EPISTEMIC_LINK_MERGED_FROM_SOURCES,
                {"merged_id": merged_id, "source_ids": source_belief_ids},
            )

            # Mark source beliefs as stale
            for source_id in source_belief_ids:
                await tx.execute_write(
                    queries.EPISTEMIC_MARK_BELIEF_STALE,
                    {
                        "belief_id": source_id,
                        "silo_id": silo_id,
                        "reason": f"merged_into:{merged_id}",
                    },
                )

            return str(merged_id)

    async def mark_belief_stale(
        self, silo_id: str, belief_id: str, reason: str
    ) -> None:
        """Mark a belief as stale with a reason."""
        await self._store.execute_write(
            queries.EPISTEMIC_MARK_BELIEF_STALE,
            {"silo_id": silo_id, "belief_id": belief_id, "reason": reason},
        )
