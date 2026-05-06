"""E2E integration test: ingest -> query -> provenance -> get.

Seeds a set of small documents into a fresh silo, drives the pipeline via
direct service calls (no Dagster graph), then verifies the full read path.

Requires a live Memgraph instance on localhost:7687 and Qdrant on
localhost:6333. Skipped automatically when the stack is not running.
"""

from __future__ import annotations

import math
import socket
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.config.settings import get_settings
from context_service.services.context import ContextService
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.stores import MemgraphClient, create_memgraph_driver
from context_service.stores.qdrant import QdrantClient
from tests.integration.conftest import docker_available

# ---------------------------------------------------------------------------
# Qdrant availability check
# ---------------------------------------------------------------------------


def _check_qdrant_available() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("localhost", 6333))
        s.close()
        return True
    except (TimeoutError, OSError):
        return False


_full_stack_available = pytest.mark.skipif(
    not _check_qdrant_available(),
    reason="Qdrant not running on localhost:6333",
)


# ---------------------------------------------------------------------------
# Seed corpus
# ---------------------------------------------------------------------------

# Each entry: (label, content, semantic_seed)
# semantic_seed drives the deterministic fake vector; higher overlap = higher
# cosine similarity.  Docs 0-1 are about France/capital; 2-3 are unrelated.
_SEED_DOCS: list[tuple[str, str, int]] = [
    ("Document", "Paris is the capital of France.", 10),
    ("Document", "France is a country in western Europe with Paris as its capital city.", 10),
    ("Document", "Berlin is the capital city of Germany.", 20),
    ("Document", "Tokyo is the capital of Japan.", 30),
    ("Document", "The Eiffel Tower is located in Paris, France.", 12),
]

# Query that should match docs 0, 1, 4 (France/Paris cluster).
_QUERY = "What is the capital of France?"
_QUERY_SEED = 10  # Same seed as the France docs -> high cosine similarity.


def _get_vector_dim() -> int:
    from context_service.config.config_loader import load_config

    try:
        return load_config("embeddings")["dimensions"]
    except (FileNotFoundError, KeyError):
        return 1024


_VECTOR_DIM = _get_vector_dim()


def _fake_vector(seed: int, dim: int = _VECTOR_DIM) -> list[float]:
    """Deterministic unit-length fake vector seeded by an integer."""
    raw = [math.sin(seed * (i + 1) * 0.1) for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


def _mock_embedding(seed: int) -> Any:
    """Return an EmbeddingService mock that always emits a fixed vector."""
    mock = AsyncMock()
    vec = _fake_vector(seed)
    mock.embed_single = AsyncMock(return_value=vec)
    mock.embed_query = AsyncMock(return_value=vec)
    mock.embed = AsyncMock(return_value=[vec])
    return mock


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@docker_available
@_full_stack_available
@pytest.mark.integration
class TestE2EIngestQuery:
    """Full ingest -> query -> provenance -> get loop against the live stack."""

    # -- fixtures ------------------------------------------------------------

    @pytest.fixture
    def org_id(self) -> str:
        return f"test-e2e-{uuid.uuid4().hex[:8]}"

    @pytest.fixture
    def silo_id(self, org_id: str) -> uuid.UUID:
        return derive_silo_id(org_id)

    @pytest.fixture
    def scope(self, org_id: str, silo_id: uuid.UUID) -> ScopeContext:
        return ScopeContext(org_id=org_id, silo_id=silo_id)

    @pytest.fixture
    async def memgraph(self) -> MemgraphClient:
        settings = get_settings()
        driver = await create_memgraph_driver(settings)
        client = MemgraphClient(driver)
        yield client
        await driver.close()

    @pytest.fixture
    def qdrant(self) -> QdrantClient:
        return QdrantClient(url="http://localhost:6333", vector_size=_VECTOR_DIM)

    @pytest.fixture
    async def cleanup(self, memgraph: MemgraphClient, silo_id: uuid.UUID) -> Any:
        """Delete all test nodes after the test."""
        yield
        sid = str(silo_id)
        await memgraph.execute_write(
            "MATCH (n {silo_id: $silo_id}) DETACH DELETE n",
            {"silo_id": sid},
        )
        await memgraph.execute_write(
            "MATCH (s:Silo {id: $silo_id}) DELETE s",
            {"silo_id": sid},
        )

    @pytest.fixture
    async def seeded_nodes(
        self,
        memgraph: MemgraphClient,
        qdrant: QdrantClient,
        scope: ScopeContext,
        cleanup: Any,
    ) -> list[Any]:
        """Ingest all seed documents; return the resulting Node objects."""
        nodes = []
        for label, content, seed in _SEED_DOCS:
            embedding = _mock_embedding(seed)
            service = ContextService(memgraph=memgraph, qdrant=qdrant, embedding=embedding)
            node = await service.store(scope=scope, content=content, node_type=label)
            nodes.append(node)
        return nodes

    # -- tests ---------------------------------------------------------------

    async def test_query_top_result_references_seed_doc(
        self,
        memgraph: MemgraphClient,
        qdrant: QdrantClient,
        scope: ScopeContext,
        seeded_nodes: list[Any],
    ) -> None:
        """context_query should return a result whose content matches a seeded doc."""
        france_ids = {
            str(seeded_nodes[0].id),
            str(seeded_nodes[1].id),
            str(seeded_nodes[4].id),
        }

        query_embedding = _mock_embedding(_QUERY_SEED)
        service = ContextService(memgraph=memgraph, qdrant=qdrant, embedding=query_embedding)

        results = await service.query(scope, _QUERY, top_k=5, search_mode="dense")

        assert results, "Expected at least one result from context_query"

        result_ids = {str(r.node_id) for r in results}
        overlap = result_ids & france_ids
        assert overlap, (
            f"Expected at least one France/Paris doc in query results. "
            f"Got: {result_ids}, expected overlap with: {france_ids}"
        )

        top_id = str(results[0].node_id)
        assert top_id in france_ids, (
            f"Top result {top_id} is not a France/Paris document. Expected one of {france_ids}"
        )

    async def test_provenance_traces_to_seed_doc(
        self,
        memgraph: MemgraphClient,
        qdrant: QdrantClient,
        scope: ScopeContext,
        seeded_nodes: list[Any],
    ) -> None:
        """context_provenance should return a chain that includes the source document."""
        seed_node = seeded_nodes[0]
        silo_id = str(scope.silo_id)

        # Add a REFERENCES edge from a claim to the document to exercise multi-hop provenance.
        claim_id = str(uuid.uuid4())
        await memgraph.execute_write(
            """
            CREATE (c:Claim {
                id: $claim_id,
                silo_id: $silo_id,
                type: 'Claim',
                content: 'Paris is capital of France',
                confidence: 0.9,
                created_at: timestamp()
            })
            """,
            {"claim_id": claim_id, "silo_id": silo_id},
        )
        await memgraph.execute_write(
            """
            MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
            MATCH (d:Document {id: $doc_id, silo_id: $silo_id})
            CREATE (c)-[:REFERENCES]->(d)
            """,
            {"claim_id": claim_id, "doc_id": str(seed_node.id), "silo_id": silo_id},
        )

        service = ContextService(memgraph=memgraph, qdrant=qdrant)
        result = await service.provenance(silo_id=silo_id, node_id=claim_id)

        assert result.chain, "Provenance chain should not be empty"
        chain_ids = [step.node_id for step in result.chain]
        assert str(seed_node.id) in chain_ids, (
            f"Seed document {seed_node.id} should appear in provenance chain. Chain: {chain_ids}"
        )

        assert any(step.layer == "Document" for step in result.chain), (
            "Expected a Document step in provenance chain"
        )

    async def test_get_returns_populated_metadata(
        self,
        memgraph: MemgraphClient,
        qdrant: QdrantClient,
        scope: ScopeContext,
        seeded_nodes: list[Any],
    ) -> None:
        """context_get should return the node with content and metadata populated."""
        target = seeded_nodes[0]

        service = ContextService(memgraph=memgraph, qdrant=qdrant)
        node = await service.get(node_id=target.id, silo_id=scope.silo_id)

        assert node is not None, f"Expected node {target.id} to be retrievable via context_get"
        assert node.id == target.id
        assert node.content == target.content
        assert node.type == "Document"
        assert node.silo_id == scope.silo_id
        assert node.content_hash is not None, "content_hash should be populated"

    async def test_all_seed_docs_stored_in_graph(
        self,
        memgraph: MemgraphClient,
        scope: ScopeContext,
        seeded_nodes: list[Any],
    ) -> None:
        """All seeded documents should be present in Memgraph."""
        silo_id = str(scope.silo_id)
        rows = await memgraph.execute_query(
            "MATCH (n:Document {silo_id: $silo_id}) RETURN count(n) AS cnt",
            {"silo_id": silo_id},
        )
        count = int(rows[0]["cnt"]) if rows else 0
        assert count == len(_SEED_DOCS), f"Expected {len(_SEED_DOCS)} Document nodes, found {count}"
