"""E2E tests for provenance chain integrity.

Validates that after storing documents and creating claims with REFERENCES edges,
the context_provenance tool returns complete chains reaching source documents.
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.conftest import docker_available


@docker_available
@pytest.mark.integration
class TestProvenanceChainIntegrity:
    """Provenance queries return complete chains to source documents."""

    async def test_provenance_reaches_source_document(
        self,
        memgraph_client,
        unique_silo_id,
        cleanup_silo,
    ) -> None:
        """Claim with REFERENCES edge shows Document in provenance chain."""
        silo_id = str(unique_silo_id)
        doc_id = str(uuid.uuid4())
        claim_id = str(uuid.uuid4())

        # 1. Create document
        await memgraph_client.execute_write(
            """
            CREATE (d:Document {
                id: $doc_id,
                silo_id: $silo_id,
                content: 'Alice owns a property in Berlin.',
                committed: true,
                created_at: timestamp()
            })
            """,
            {"doc_id": doc_id, "silo_id": silo_id},
        )

        # 2. Create claim with REFERENCES edge to document
        await memgraph_client.execute_write(
            """
            CREATE (c:Claim {
                id: $claim_id,
                silo_id: $silo_id,
                content: 'Alice is a property owner',
                confidence: 0.85,
                created_at: timestamp()
            })
            """,
            {"claim_id": claim_id, "silo_id": silo_id},
        )

        await memgraph_client.execute_write(
            """
            MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
            MATCH (d:Document {id: $doc_id, silo_id: $silo_id})
            CREATE (c)-[:REFERENCES]->(d)
            """,
            {"claim_id": claim_id, "doc_id": doc_id, "silo_id": silo_id},
        )

        # 3. Query provenance via the actual query
        from context_service.db.queries import PROVENANCE_CHAIN, PROVENANCE_ROOT_SOURCES

        chain_rows = await memgraph_client.execute_query(
            PROVENANCE_CHAIN,
            {"node_id": claim_id, "silo_id": silo_id},
        )

        root_rows = await memgraph_client.execute_query(
            PROVENANCE_ROOT_SOURCES,
            {"node_id": claim_id, "silo_id": silo_id},
        )

        # 4. Assert chain includes document
        chain_layers = [r["layer"] for r in chain_rows]
        assert "Document" in chain_layers, f"Expected Document in chain, got {chain_layers}"

        # 5. Assert root sources contains the document
        root_ids = [r["node_id"] for r in root_rows]
        assert doc_id in root_ids, f"Expected {doc_id} in root sources, got {root_ids}"

    async def test_provenance_multi_hop_chain(
        self,
        memgraph_client,
        unique_silo_id,
        cleanup_silo,
    ) -> None:
        """Provenance traverses multiple edge types: Fact -> Claim -> Document."""
        silo_id = str(unique_silo_id)
        doc_id = str(uuid.uuid4())
        claim_id = str(uuid.uuid4())
        fact_id = str(uuid.uuid4())

        # Create Document -> Claim -> Fact chain
        await memgraph_client.execute_write(
            """
            CREATE (d:Document {id: $doc_id, silo_id: $silo_id, content: 'Source doc', committed: true})
            CREATE (c:Claim {id: $claim_id, silo_id: $silo_id, content: 'Extracted claim', confidence: 0.9})
            CREATE (f:Fact {id: $fact_id, silo_id: $silo_id, content: 'Promoted fact', confidence: 0.95})
            CREATE (c)-[:REFERENCES]->(d)
            CREATE (f)-[:PROMOTED_FROM]->(c)
            """,
            {
                "doc_id": doc_id,
                "claim_id": claim_id,
                "fact_id": fact_id,
                "silo_id": silo_id,
            },
        )

        # Query provenance starting from Fact
        from context_service.db.queries import PROVENANCE_CHAIN, PROVENANCE_ROOT_SOURCES

        chain_rows = await memgraph_client.execute_query(
            PROVENANCE_CHAIN,
            {"node_id": fact_id, "silo_id": silo_id},
        )

        root_rows = await memgraph_client.execute_query(
            PROVENANCE_ROOT_SOURCES,
            {"node_id": fact_id, "silo_id": silo_id},
        )

        # Assert full chain: Fact -> Claim -> Document
        chain_ids = [r["node_id"] for r in chain_rows]
        assert claim_id in chain_ids, "Claim should be in chain"
        assert doc_id in chain_ids, "Document should be in chain"

        # Assert document is root source
        root_ids = [r["node_id"] for r in root_rows]
        assert doc_id in root_ids, "Document should be root source"

    async def test_provenance_via_service(
        self,
        memgraph_client,
        unique_silo_id,
        cleanup_silo,
    ) -> None:
        """Test provenance via ContextService.provenance() method."""
        silo_id = str(unique_silo_id)
        doc_id = str(uuid.uuid4())
        claim_id = str(uuid.uuid4())

        # Create Document and Claim with REFERENCES
        await memgraph_client.execute_write(
            """
            CREATE (d:Document {id: $doc_id, silo_id: $silo_id, content: 'Test document'})
            CREATE (c:Claim {id: $claim_id, silo_id: $silo_id, content: 'Test claim'})
            CREATE (c)-[:REFERENCES]->(d)
            """,
            {"doc_id": doc_id, "claim_id": claim_id, "silo_id": silo_id},
        )

        # Use actual service
        from context_service.services.context import ContextService

        service = ContextService(memgraph=memgraph_client, qdrant=None)
        result = await service.provenance(silo_id=silo_id, node_id=claim_id)

        # Assert chain is populated
        assert len(result.chain) > 0, "Chain should not be empty"
        assert any(step.layer == "Document" for step in result.chain), "Document should be in chain"

        # Assert root sources
        assert len(result.root_sources) > 0, "Root sources should not be empty"
