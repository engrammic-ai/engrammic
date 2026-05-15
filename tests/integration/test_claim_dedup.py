"""Integration test: content-hash deduplication in assert_claim."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from context_service.services.context import ContextService
from context_service.services.models import ScopeContext
from context_service.stores import MemgraphClient

from .conftest import docker_available


def _make_service(memgraph_client: MemgraphClient) -> ContextService:
    mock_embedding = AsyncMock()
    mock_embedding.embed_single = AsyncMock(return_value=[0.1] * 1024)
    mock_qdrant = AsyncMock()
    mock_qdrant.upsert = AsyncMock(return_value=None)
    return ContextService(
        memgraph=memgraph_client,
        qdrant=mock_qdrant,
        embedding=mock_embedding,
    )


@docker_available
@pytest.mark.integration
class TestClaimDedup:
    """Verify content-hash deduplication and evidence edge handling."""

    async def test_duplicate_claim_returns_existing_node(
        self,
        memgraph_client: MemgraphClient,
        unique_org_id: str,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """Calling assert_claim twice with same content returns same node."""
        scope = ScopeContext(org_id=unique_org_id, silo_id=unique_silo_id)
        service = _make_service(memgraph_client)

        claim_content = "Dedup test: the sky is blue"

        node1 = await service.assert_claim(
            scope=scope,
            claim=claim_content,
            evidence=["node:ev-1"],
            source_type="document",
            confidence=0.9,
        )

        node2 = await service.assert_claim(
            scope=scope,
            claim=claim_content,
            evidence=["node:ev-2"],
            source_type="document",
            confidence=0.9,
        )

        assert node1.id == node2.id, "Duplicate claim should return same node ID"

    async def test_duplicate_evidence_edge_not_duplicated(
        self,
        memgraph_client: MemgraphClient,
        unique_org_id: str,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """MERGE prevents duplicate DERIVED_FROM edges for same evidence."""
        scope = ScopeContext(org_id=unique_org_id, silo_id=unique_silo_id)
        silo_id_str = str(unique_silo_id)
        service = _make_service(memgraph_client)

        # Create an evidence node first
        ev_node = await service.store(
            scope=scope,
            content="Evidence node for dedup test",
            node_type="Observation",
        )
        ev_ref = f"node:{ev_node.id}"

        claim_content = "Claim with repeated evidence"

        # Assert claim twice with the SAME evidence
        node1 = await service.assert_claim(
            scope=scope,
            claim=claim_content,
            evidence=[ev_ref],
            source_type="document",
            confidence=0.9,
        )

        node2 = await service.assert_claim(
            scope=scope,
            claim=claim_content,
            evidence=[ev_ref],
            source_type="document",
            confidence=0.9,
        )

        assert node1.id == node2.id

        # Count DERIVED_FROM edges - should be exactly 1, not 2
        rows = await memgraph_client.execute_query(
            """
            MATCH (c {id: $claim_id, silo_id: $silo_id})-[r:DERIVED_FROM]->(ev)
            RETURN count(r) AS edge_count
            """,
            {"claim_id": str(node1.id), "silo_id": silo_id_str},
        )

        assert rows[0]["edge_count"] == 1, "MERGE should prevent duplicate edges"

    async def test_different_silo_creates_separate_claim(
        self,
        memgraph_client: MemgraphClient,
        unique_org_id: str,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """Same content in different silos creates separate nodes."""
        silo1 = unique_silo_id
        silo2 = uuid.uuid4()
        service = _make_service(memgraph_client)

        claim_content = "Cross-silo dedup test"

        node1 = await service.assert_claim(
            scope=ScopeContext(org_id=unique_org_id, silo_id=silo1),
            claim=claim_content,
            evidence=[],
            source_type="document",
            confidence=0.9,
        )

        node2 = await service.assert_claim(
            scope=ScopeContext(org_id=unique_org_id, silo_id=silo2),
            claim=claim_content,
            evidence=[],
            source_type="document",
            confidence=0.9,
        )

        assert node1.id != node2.id, "Different silos should have separate claims"
