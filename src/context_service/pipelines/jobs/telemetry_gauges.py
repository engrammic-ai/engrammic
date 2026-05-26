"""Dagster job for periodic storage gauge snapshots."""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg

_LIST_SILOS = "SELECT DISTINCT silo_id FROM silo_config"

_COUNT_NODES = """
MATCH (n)
WHERE n.silo_id = $silo_id
RETURN
    sum(CASE WHEN n:Passage OR n:Utterance OR n:Event THEN 1 ELSE 0 END) AS memory,
    sum(CASE WHEN n:Claim THEN 1 ELSE 0 END) AS knowledge,
    sum(CASE WHEN n:Belief OR n:Commitment THEN 1 ELSE 0 END) AS wisdom
"""

_COUNT_EDGES = """
MATCH ()-[r]->()
WHERE r.silo_id = $silo_id OR startNode(r).silo_id = $silo_id
RETURN count(r) AS edges
"""


@dg.op(required_resource_keys={"postgres", "memgraph", "qdrant"})
def snapshot_storage_gauges(context) -> dict[str, Any]:
    """Snapshot storage metrics for all silos."""
    from context_service.pipelines.resources import (
        MemgraphResource,
        PostgresResource,
        QdrantResource,
    )

    postgres: PostgresResource = context.resources.postgres
    memgraph: MemgraphResource = context.resources.memgraph
    qdrant: QdrantResource = context.resources.qdrant

    async def _run() -> dict[str, int]:
        store = await memgraph.store()
        qd_client = qdrant.client()

        with postgres.get_pool() as pool:
            async with pool.acquire() as conn:
                rows = await conn.fetch(_LIST_SILOS)
                silo_ids = [str(row["silo_id"]) for row in rows]

            total = 0
            for silo_id in silo_ids:
                # Query Memgraph for node counts
                try:
                    node_rows = await store.execute_query(_COUNT_NODES, {"silo_id": silo_id})
                    node_row = node_rows[0] if node_rows else {}
                except Exception:
                    node_row = {}
                    context.log.warning(f"telemetry_gauges: memgraph query failed for silo={silo_id}")

                try:
                    edge_rows = await store.execute_query(_COUNT_EDGES, {"silo_id": silo_id})
                    edge_count = edge_rows[0].get("edges", 0) if edge_rows else 0
                except Exception:
                    edge_count = 0

                # Query Qdrant for collection stats
                try:
                    collection_info = await qd_client.get_collection(f"silo_{silo_id}")
                    qd_points = collection_info.points_count or 0
                except Exception:
                    qd_points = 0

                # Insert gauge
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO service_gauges (
                            silo_id,
                            node_count_memory, node_count_knowledge, node_count_wisdom,
                            edge_count, qdrant_point_count
                        ) VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        silo_id,
                        node_row.get("memory", 0),
                        node_row.get("knowledge", 0),
                        node_row.get("wisdom", 0),
                        edge_count,
                        qd_points,
                    )

                context.log.info(f"telemetry_gauges: silo={silo_id}")
                total += 1

            return {"silos_processed": total}

    return asyncio.run(_run())


@dg.job(name="telemetry_gauges", tags={"schedule_type": "maintenance"})
def telemetry_gauges_job() -> None:
    """Hourly storage gauge snapshots."""
    snapshot_storage_gauges()
