"""Integration tests for scripts/migrate_belongs_to.py."""

from __future__ import annotations

import uuid

import pytest

from context_service.stores import MemgraphClient
from scripts.migrate_belongs_to import migrate_silo

from .conftest import docker_available

_SEED_CLUSTER = """
MERGE (c:Cluster {id: $cluster_id, silo_id: $silo_id})
"""

_SEED_BELONGS_TO = """
MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})
MERGE (n:Passage {id: $node_id, silo_id: $silo_id})-[:BELONGS_TO {weight: 0.5, created_at: datetime()}]->(c)
"""

_COUNT_BELONGS_TO = """
MATCH (n)-[r:BELONGS_TO]->(c:Cluster {silo_id: $silo_id})
RETURN count(r) AS cnt
"""

_COUNT_MEMBER_OF = """
MATCH (n)-[r:MEMBER_OF]->(c:Cluster {silo_id: $silo_id})
RETURN count(r) AS cnt
"""


async def _seed_silo(
    client: MemgraphClient,
    silo_id: str,
    *,
    edge_count: int = 2,
) -> str:
    cluster_id = f"cluster-{uuid.uuid4().hex[:8]}"
    await client.execute_write(_SEED_CLUSTER, {"cluster_id": cluster_id, "silo_id": silo_id})
    for i in range(edge_count):
        await client.execute_write(
            _SEED_BELONGS_TO,
            {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "node_id": f"node-{i}-{uuid.uuid4().hex[:6]}",
            },
        )
    return cluster_id


async def _count(client: MemgraphClient, query: str, silo_id: str) -> int:
    rows = await client.execute_query(query, {"silo_id": silo_id})
    return int(rows[0]["cnt"]) if rows else 0


@docker_available
@pytest.mark.integration
class TestMigrateBelongsTo:
    async def test_migrate_silo_converts_legacy_edges(
        self,
        memgraph_client: MemgraphClient,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """BELONGS_TO edges are replaced by MEMBER_OF with migrated_from set."""
        silo_id = str(unique_silo_id)
        await _seed_silo(memgraph_client, silo_id, edge_count=2)

        assert await _count(memgraph_client, _COUNT_BELONGS_TO, silo_id) == 2

        await migrate_silo(memgraph_client, silo_id)

        assert await _count(memgraph_client, _COUNT_BELONGS_TO, silo_id) == 0
        assert await _count(memgraph_client, _COUNT_MEMBER_OF, silo_id) == 2

        rows = await memgraph_client.execute_query(
            "MATCH (n)-[r:MEMBER_OF]->(c:Cluster {silo_id: $silo_id}) RETURN r.migrated_from AS mf",
            {"silo_id": silo_id},
        )
        assert all(row["mf"] == "BELONGS_TO" for row in rows)

    async def test_migrate_idempotent(
        self,
        memgraph_client: MemgraphClient,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """Re-running migration produces no errors and no duplicate edges."""
        silo_id = str(unique_silo_id)
        await _seed_silo(memgraph_client, silo_id, edge_count=2)

        await migrate_silo(memgraph_client, silo_id)
        await migrate_silo(memgraph_client, silo_id)

        assert await _count(memgraph_client, _COUNT_BELONGS_TO, silo_id) == 0
        assert await _count(memgraph_client, _COUNT_MEMBER_OF, silo_id) == 2

    async def test_dry_run_does_not_mutate(
        self,
        memgraph_client: MemgraphClient,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """dry_run=True reports count without touching the graph."""
        silo_id = str(unique_silo_id)
        await _seed_silo(memgraph_client, silo_id, edge_count=2)

        would_migrate = await migrate_silo(memgraph_client, silo_id, dry_run=True)

        assert would_migrate == 2
        assert await _count(memgraph_client, _COUNT_BELONGS_TO, silo_id) == 2
        assert await _count(memgraph_client, _COUNT_MEMBER_OF, silo_id) == 0
