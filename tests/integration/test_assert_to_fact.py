"""Integration test: assert_claim -> promote_claim_to_fact end-to-end."""

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
class TestAssertToFact:
    """Verify that assert_claim + promote_claim_to_fact writes :Claim:Fact label."""

    async def test_authoritative_claim_promotes_to_fact(
        self,
        memgraph_client: MemgraphClient,
        unique_org_id: str,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """assert_claim with authoritative source_tier + high confidence yields :Claim:Fact."""
        scope = ScopeContext(org_id=unique_org_id, silo_id=unique_silo_id)
        silo_id_str = str(unique_silo_id)
        service = _make_service(memgraph_client)

        node = await service.assert_claim(
            scope=scope,
            claim="The capital of France is Paris",
            evidence=["node:ref-1"],
            source_type="document",
            confidence=0.85,
            metadata={"source_tier": "authoritative"},
        )
        claim_id = str(node.id)

        promoted = await service.promote_claim_to_fact(
            silo_id=silo_id_str,
            claim_id=claim_id,
            evidence_count=1,
        )

        assert promoted is not None, "Expected promotion for authoritative high-confidence claim"

        rows = await memgraph_client.execute_query(
            "MATCH (c:Claim:Fact {id: $claim_id, silo_id: $silo_id}) RETURN properties(c) AS props",
            {"claim_id": claim_id, "silo_id": silo_id_str},
        )
        assert rows, "Node must carry both :Claim and :Fact labels"

        props = dict(rows[0]["props"])
        assert "promoted_at" in props
        assert props.get("promotion_rule") in ("R1", "R2")
        assert props.get("source_tier") == "authoritative"
        assert float(props.get("confidence", 0)) == pytest.approx(0.85)

    async def test_low_confidence_claim_not_promoted(
        self,
        memgraph_client: MemgraphClient,
        unique_org_id: str,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """A claim with confidence < 0.7 is not promoted even with authoritative tier."""
        scope = ScopeContext(org_id=unique_org_id, silo_id=unique_silo_id)
        silo_id_str = str(unique_silo_id)
        service = _make_service(memgraph_client)

        node = await service.assert_claim(
            scope=scope,
            claim="The sky is green",
            evidence=["node:ref-2"],
            source_type="document",
            confidence=0.5,
            metadata={"source_tier": "authoritative"},
        )
        claim_id = str(node.id)

        result = await service.promote_claim_to_fact(
            silo_id=silo_id_str,
            claim_id=claim_id,
            evidence_count=1,
        )
        assert result is None, "Low-confidence claim should not be promoted"

        rows = await memgraph_client.execute_query(
            "MATCH (c:Claim:Fact {id: $claim_id, silo_id: $silo_id}) RETURN c",
            {"claim_id": claim_id, "silo_id": silo_id_str},
        )
        assert not rows, ":Fact label must not be present"

    async def test_promote_auto_counts_derived_from_edges(
        self,
        memgraph_client: MemgraphClient,
        unique_org_id: str,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """When evidence_count is omitted, the count query must include DERIVED_FROM.

        Regression: assert_claim writes DERIVED_FROM edges; an earlier version of
        promote_claim_to_fact only counted REFERENCES, so auto-evidence-counting
        always returned 0 and nothing promoted.
        """
        scope = ScopeContext(org_id=unique_org_id, silo_id=unique_silo_id)
        silo_id_str = str(unique_silo_id)
        service = _make_service(memgraph_client)

        # Pre-create the evidence node so DERIVED_FROM has a target to MATCH.
        ev_id = f"ev-{uuid.uuid4().hex[:8]}"
        await memgraph_client.execute_write(
            "CREATE (n:Document {id: $id, silo_id: $silo_id})",
            {"id": ev_id, "silo_id": silo_id_str},
        )

        node = await service.assert_claim(
            scope=scope,
            claim="Berlin is in Germany",
            evidence=[f"node:{ev_id}"],
            source_type="document",
            confidence=0.85,
            metadata={"source_tier": "authoritative"},
        )
        claim_id = str(node.id)

        # Omit evidence_count — promote_claim_to_fact must auto-count via the
        # REFERENCES|DERIVED_FROM Cypher and find the DERIVED_FROM edge.
        result = await service.promote_claim_to_fact(
            silo_id=silo_id_str,
            claim_id=claim_id,
        )
        assert result is not None, "Auto-count must include DERIVED_FROM edges"

        rows = await memgraph_client.execute_query(
            "MATCH (c:Claim:Fact {id: $claim_id, silo_id: $silo_id}) RETURN c",
            {"claim_id": claim_id, "silo_id": silo_id_str},
        )
        assert rows, ":Fact label must be present after auto-counted promotion"

    async def test_promote_is_idempotent(
        self,
        memgraph_client: MemgraphClient,
        unique_org_id: str,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """Calling promote_claim_to_fact twice is safe and returns existing props."""
        scope = ScopeContext(org_id=unique_org_id, silo_id=unique_silo_id)
        silo_id_str = str(unique_silo_id)
        service = _make_service(memgraph_client)

        node = await service.assert_claim(
            scope=scope,
            claim="Paris is in France",
            evidence=["node:ev-1"],
            source_type="document",
            confidence=0.85,
            metadata={"source_tier": "authoritative"},
        )
        claim_id = str(node.id)

        first = await service.promote_claim_to_fact(
            silo_id=silo_id_str,
            claim_id=claim_id,
            evidence_count=1,
        )
        second = await service.promote_claim_to_fact(
            silo_id=silo_id_str,
            claim_id=claim_id,
            evidence_count=1,
        )

        assert first is not None, "First promotion should succeed"
        assert second is not None, "Second call should return existing props without error"
