"""Integration test: retention sweep tombstones old ephemeral nodes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from context_service.retention.policy import RetentionPolicy
from context_service.retention.service import RetentionService
from context_service.stores import MemgraphClient

from .conftest import docker_available


@docker_available
@pytest.mark.integration
class TestRetentionSweep:
    """Verify RetentionService.run_sweep tombstones eligible nodes against live Memgraph."""

    async def test_tombstones_old_ephemeral_node(
        self,
        memgraph_client: MemgraphClient,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """Old ephemeral nodes are tombstoned by run_sweep."""
        silo_id_str = str(unique_silo_id)
        node_id = f"test-ephemeral-{uuid.uuid4().hex[:8]}"
        old_time = (datetime.now(UTC) - timedelta(hours=25)).isoformat()

        await memgraph_client.execute_write(
            """
            CREATE (n:Memory {
                id: $id,
                silo_id: $silo_id,
                decay_class: 'ephemeral',
                heat_score: 0.0,
                created_at: $created_at
            })
            """,
            {"id": node_id, "silo_id": silo_id_str, "created_at": old_time},
        )

        service = RetentionService(store=memgraph_client, policy=RetentionPolicy())
        result = await service.run_sweep(silo_id_str)

        assert result["tombstoned"] >= 1

        rows = await memgraph_client.execute_query(
            "MATCH (n {id: $id}) RETURN n.tombstoned_at AS ts",
            {"id": node_id},
        )
        assert rows, "Node should still exist after tombstoning"
        assert rows[0]["ts"] is not None, "tombstoned_at should be set"

    async def test_fresh_ephemeral_node_not_tombstoned(
        self,
        memgraph_client: MemgraphClient,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """A recently created ephemeral node is not tombstoned."""
        silo_id_str = str(unique_silo_id)
        node_id = f"test-ephemeral-fresh-{uuid.uuid4().hex[:8]}"
        recent_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

        await memgraph_client.execute_write(
            """
            CREATE (n:Memory {
                id: $id,
                silo_id: $silo_id,
                decay_class: 'ephemeral',
                heat_score: 0.0,
                created_at: $created_at
            })
            """,
            {"id": node_id, "silo_id": silo_id_str, "created_at": recent_time},
        )

        service = RetentionService(store=memgraph_client, policy=RetentionPolicy())
        await service.run_sweep(silo_id_str)

        rows = await memgraph_client.execute_query(
            "MATCH (n {id: $id}) RETURN n.tombstoned_at AS ts",
            {"id": node_id},
        )
        assert rows, "Node should still exist"
        assert rows[0]["ts"] is None, "Fresh node should not be tombstoned"

    async def test_permanent_node_never_tombstoned(
        self,
        memgraph_client: MemgraphClient,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """Nodes with decay_class=permanent are never tombstoned regardless of age."""
        silo_id_str = str(unique_silo_id)
        node_id = f"test-permanent-{uuid.uuid4().hex[:8]}"
        very_old_time = (datetime.now(UTC) - timedelta(days=365)).isoformat()

        await memgraph_client.execute_write(
            """
            CREATE (n:Memory {
                id: $id,
                silo_id: $silo_id,
                decay_class: 'permanent',
                heat_score: 0.0,
                created_at: $created_at
            })
            """,
            {"id": node_id, "silo_id": silo_id_str, "created_at": very_old_time},
        )

        service = RetentionService(store=memgraph_client, policy=RetentionPolicy())
        result = await service.run_sweep(silo_id_str)

        rows = await memgraph_client.execute_query(
            "MATCH (n {id: $id}) RETURN n.tombstoned_at AS ts",
            {"id": node_id},
        )
        assert rows, "Permanent node should still exist"
        assert rows[0]["ts"] is None, "Permanent node must not be tombstoned"
        _ = result  # sweep ran without error
