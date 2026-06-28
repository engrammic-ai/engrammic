"""E2E tests for reflection storage and retrieval.

Validates that Reflections stored via context_reflect are retrievable
via context_get_reflections with correct properties preserved.
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.conftest import docker_available


@docker_available
@pytest.mark.integration
class TestReflectionRoundTrip:
    """Reflections are stored and retrieved correctly."""

    async def test_reflect_and_retrieve(
        self,
        memgraph_client,
        unique_org_id,
        unique_silo_id,
        cleanup_silo,
    ) -> None:
        """Store reflection, retrieve it, verify properties."""
        silo_id = str(unique_silo_id)
        claim_id = str(uuid.uuid4())

        # 1. Create a claim node to reflect on
        await memgraph_client.execute_write(
            """
            CREATE (c:Claim {
                id: $claim_id,
                silo_id: $silo_id,
                content: 'The sky is blue',
                confidence: 0.9
            })
            """,
            {"claim_id": claim_id, "silo_id": silo_id},
        )

        # 2. Store reflection via service
        from context_service.services.context import ContextService
        from context_service.services.models import ScopeContext

        scope = ScopeContext(org_id=unique_org_id, silo_id=unique_silo_id)
        service = ContextService(memgraph=memgraph_client, qdrant=None)

        reflection_node = await service.reflect(
            scope=scope,
            observation="I noticed this contradicts earlier observation about weather",
            observation_type="contradiction",
            about=[claim_id],
            confidence=0.75,
            agent_id="test-agent",
        )

        assert reflection_node.id is not None

        # 3. Retrieve reflections
        reflections = await service.get_reflections(
            silo_id=silo_id,
            node_id=claim_id,
        )

        # 4. Assert reflection found with correct properties
        assert len(reflections) == 1, f"Expected 1 reflection, got {len(reflections)}"

        r = reflections[0]
        assert r["observation_type"] == "contradiction"
        assert r["confidence"] == 0.75
        assert r["agent_id"] == "test-agent"
        assert "contradicts" in r["content"]

    async def test_multiple_reflections_on_same_node(
        self,
        memgraph_client,
        unique_org_id,
        unique_silo_id,
        cleanup_silo,
    ) -> None:
        """Multiple reflections on same node are all retrievable."""
        silo_id = str(unique_silo_id)
        fact_id = str(uuid.uuid4())

        # Create fact node
        await memgraph_client.execute_write(
            """
            CREATE (f:Fact {
                id: $fact_id,
                silo_id: $silo_id,
                content: 'Water boils at 100C'
            })
            """,
            {"fact_id": fact_id, "silo_id": silo_id},
        )

        from context_service.services.context import ContextService
        from context_service.services.models import ScopeContext

        scope = ScopeContext(org_id=unique_org_id, silo_id=unique_silo_id)
        service = ContextService(memgraph=memgraph_client, qdrant=None)

        # Store multiple reflections
        await service.reflect(
            scope=scope,
            observation="This is a well-established fact",
            observation_type="insight",
            about=[fact_id],
            agent_id="agent-1",
        )

        await service.reflect(
            scope=scope,
            observation="Confidence increased after verification",
            observation_type="confidence_shift",
            about=[fact_id],
            agent_id="agent-2",
        )

        # Retrieve all
        reflections = await service.get_reflections(silo_id=silo_id, node_id=fact_id)

        assert len(reflections) == 2
        types = {r["observation_type"] for r in reflections}
        assert types == {"insight", "confidence_shift"}

    async def test_reflection_isolation_by_silo(
        self,
        memgraph_client,
        unique_org_id,
        unique_silo_id,
        cleanup_silo,
    ) -> None:
        """Reflections from different silos don't leak."""
        silo_id_1 = str(unique_silo_id)
        silo_id_2 = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        # Create same node_id in both silos (edge case)
        for silo_id in [silo_id_1, silo_id_2]:
            await memgraph_client.execute_write(
                "CREATE (n:Claim {id: $node_id, silo_id: $silo_id, content: 'Test'})",
                {"node_id": node_id, "silo_id": silo_id},
            )

        # Create reflection in silo_2 (should not appear in silo_1 queries)
        obs_id = str(uuid.uuid4())
        await memgraph_client.execute_write(
            """
            CREATE (obs:Memory {
                id: $obs_id,
                silo_id: $silo_id_2,
                memory_type: 'reflection',
                content: 'Reflection in silo 2',
                observation_type: 'insight',
                confidence: 0.8
            })
            WITH obs
            MATCH (n:Claim {id: $node_id, silo_id: $silo_id_2})
            CREATE (obs)-[:ABOUT]->(n)
            """,
            {"obs_id": obs_id, "node_id": node_id, "silo_id_2": silo_id_2},
        )

        # Query reflections in silo_1 - should be empty
        from context_service.services.context import ContextService

        service = ContextService(memgraph=memgraph_client, qdrant=None)
        reflections = await service.get_reflections(silo_id=silo_id_1, node_id=node_id)

        assert len(reflections) == 0, "Reflections should not leak across silos"

        # Cleanup silo_2 manually
        await memgraph_client.execute_write(
            "MATCH (n {silo_id: $silo_id}) DETACH DELETE n",
            {"silo_id": silo_id_2},
        )

    async def test_get_reflections_empty_for_unreflected_node(
        self,
        memgraph_client,
        unique_silo_id,
        cleanup_silo,
    ) -> None:
        """Querying reflections on node with none returns empty list."""
        silo_id = str(unique_silo_id)
        node_id = str(uuid.uuid4())

        # Create node without reflections
        await memgraph_client.execute_write(
            "CREATE (n:Claim {id: $node_id, silo_id: $silo_id, content: 'No reflections'})",
            {"node_id": node_id, "silo_id": silo_id},
        )

        from context_service.services.context import ContextService

        service = ContextService(memgraph=memgraph_client, qdrant=None)
        reflections = await service.get_reflections(silo_id=silo_id, node_id=node_id)

        assert reflections == []
