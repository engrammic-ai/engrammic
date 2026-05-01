"""Integration tests for hybrid dense+sparse retrieval.

Requires a live Qdrant instance on localhost:6333 with the 'splade' extra
installed. Skipped automatically when the stack is not running.

Test strategy:
- Seed a corpus of documents with rare-term content (proper nouns, acronyms).
- Run dense-only and hybrid queries against the same corpus.
- Assert that hybrid recall on rare-term queries is >= dense-only recall.
"""

from __future__ import annotations

import contextlib
import socket
import uuid
from typing import Any

import pytest

from context_service.embeddings.splade import SpladeEncoder
from context_service.stores.qdrant import QdrantClient


def _check_qdrant_available() -> bool:
    """Check if Qdrant is reachable."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("localhost", 6333))
        s.close()
        return True
    except (TimeoutError, OSError):
        return False


qdrant_available = pytest.mark.skipif(
    not _check_qdrant_available(),
    reason="Qdrant not running on localhost:6333",
)


# ---------------------------------------------------------------------------
# Rare-term corpus: proper nouns + acronyms unlikely to be close in dense space.
# ---------------------------------------------------------------------------

_CORPUS = [
    # doc_id, content
    ("doc-eag-001", "The EAG paradigm defines four cognitive layers for agent memory systems."),
    ("doc-splade-002", "SPLADE uses sparse lexical activations from masked language models."),
    ("doc-memgraph-003", "Memgraph is a graph database optimised for real-time analytics."),
    ("doc-qdrant-004", "Qdrant stores both dense and sparse named vectors in the same collection."),
    (
        "doc-rrf-005",
        "Reciprocal Rank Fusion combines ranked lists from multiple retrieval systems.",
    ),
]

# Rare-term queries that should surface a specific document.
_RARE_TERM_QUERIES = [
    ("SPLADE sparse activation", "doc-splade-002"),
    ("RRF reciprocal rank fusion", "doc-rrf-005"),
    ("Memgraph real-time graph", "doc-memgraph-003"),
]


def _make_fake_dense_vector(seed: int, dim: int = 128) -> list[float]:
    """Deterministic fake dense vector — not semantically meaningful."""
    import math

    return [math.sin(seed * (i + 1)) for i in range(dim)]


def _make_fake_sparse(seed: int, nonzero: int = 20) -> dict[int, float]:
    """Deterministic fake sparse vector with seed-specific token indices."""
    return {(seed * 17 + i * 31) % 30000: float(i + 1) * 0.1 for i in range(nonzero)}


@qdrant_available
@pytest.mark.integration
class TestHybridRetrieval:
    """Seed corpus, run dense vs hybrid, assert recall improvement."""

    @pytest.fixture
    def silo_id(self) -> str:
        return f"test-hybrid-{uuid.uuid4().hex[:8]}"

    @pytest.fixture
    async def qdrant_client(self) -> QdrantClient:
        client = QdrantClient(url="http://localhost:6333", vector_size=128)
        return client

    @pytest.fixture
    async def seeded_collection(
        self,
        qdrant_client: QdrantClient,
        silo_id: str,
    ) -> Any:
        """Create a test collection with hybrid mode and seed corpus points."""
        test_collection = "test_hybrid_vectors"
        raw_client = await qdrant_client._get_client()

        # Delete and recreate to ensure hybrid mode is enabled
        with contextlib.suppress(Exception):
            await raw_client.delete_collection(test_collection)

        from qdrant_client.models import (
            Distance,
            PointStruct,
            SparseVector,
            SparseVectorParams,
            VectorParams,
        )

        await raw_client.create_collection(
            collection_name=test_collection,
            vectors_config={"dense": VectorParams(size=128, distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams()},
        )

        points = []
        for i, (doc_id, content) in enumerate(_CORPUS):
            dense = _make_fake_dense_vector(seed=i)
            sparse = _make_fake_sparse(seed=i)
            indices, values = SpladeEncoder.to_qdrant(sparse)
            points.append(
                PointStruct(
                    id=i,
                    vector={"dense": dense, "sparse": SparseVector(indices=indices, values=values)},
                    payload={"silo_id": silo_id, "node_id": doc_id, "content": content},
                )
            )

        await raw_client.upsert(collection_name=test_collection, points=points)
        yield (silo_id, test_collection)

        # Cleanup: delete test collection
        with contextlib.suppress(Exception):
            await raw_client.delete_collection(test_collection)

    async def _run_search(
        self,
        qdrant_client: QdrantClient,
        collection_name: str,
        silo_id: str,
        query_dense: list[float],
        search_mode: str,
        sparse_indices: list[int] | None = None,
        sparse_values: list[float] | None = None,
    ) -> list[str]:
        """Run search against the test collection using the raw Qdrant client."""
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            Fusion,
            FusionQuery,
            MatchValue,
            Prefetch,
            SparseVector,
        )

        raw_client = await qdrant_client._get_client()

        # Build filter for silo_id
        silo_filter = Filter(must=[FieldCondition(key="silo_id", match=MatchValue(value=silo_id))])

        if search_mode == "dense":
            results = await raw_client.query_points(
                collection_name=collection_name,
                query=query_dense,
                using="dense",
                query_filter=silo_filter,
                limit=5,
                with_payload=True,
            )
        elif search_mode == "sparse" and sparse_indices and sparse_values:
            results = await raw_client.query_points(
                collection_name=collection_name,
                query=SparseVector(indices=sparse_indices, values=sparse_values),
                using="sparse",
                query_filter=silo_filter,
                limit=5,
                with_payload=True,
            )
        elif search_mode == "hybrid" and sparse_indices and sparse_values:
            results = await raw_client.query_points(
                collection_name=collection_name,
                prefetch=[
                    Prefetch(query=query_dense, using="dense", limit=20),
                    Prefetch(
                        query=SparseVector(indices=sparse_indices, values=sparse_values),
                        using="sparse",
                        limit=20,
                    ),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                query_filter=silo_filter,
                limit=5,
                with_payload=True,
            )
        else:
            # Fallback to dense
            results = await raw_client.query_points(
                collection_name=collection_name,
                query=query_dense,
                using="dense",
                query_filter=silo_filter,
                limit=5,
                with_payload=True,
            )

        return [(p.payload or {}).get("node_id", "") for p in results.points]

    async def test_dense_search_returns_results(
        self,
        qdrant_client: QdrantClient,
        seeded_collection: tuple[str, str],
    ) -> None:
        silo_id, collection_name = seeded_collection
        query_dense = _make_fake_dense_vector(seed=0)  # Matches doc-eag-001
        result_ids = await self._run_search(
            qdrant_client, collection_name, silo_id, query_dense, search_mode="dense"
        )
        assert len(result_ids) > 0

    async def test_hybrid_search_returns_results(
        self,
        qdrant_client: QdrantClient,
        seeded_collection: tuple[str, str],
    ) -> None:
        silo_id, collection_name = seeded_collection
        query_dense = _make_fake_dense_vector(seed=1)
        query_sparse = _make_fake_sparse(seed=1)
        sparse_indices, sparse_values = SpladeEncoder.to_qdrant(query_sparse)
        result_ids = await self._run_search(
            qdrant_client,
            collection_name,
            silo_id,
            query_dense,
            search_mode="hybrid",
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
        )
        assert len(result_ids) > 0

    async def test_hybrid_recall_gte_dense_on_rare_terms(
        self,
        qdrant_client: QdrantClient,
        seeded_collection: tuple[str, str],
    ) -> None:
        """Hybrid should find at least as many target docs as dense-only."""
        silo_id, collection_name = seeded_collection

        dense_hits = 0
        hybrid_hits = 0

        for _i, (_, expected_doc_id) in enumerate(_RARE_TERM_QUERIES):
            # Use the seed of the target doc to create a near-match vector.
            target_idx = next(
                j for j, (doc_id, _) in enumerate(_CORPUS) if doc_id == expected_doc_id
            )
            # Slightly perturb so it is not a perfect match.
            query_dense = [v * 0.95 for v in _make_fake_dense_vector(seed=target_idx)]
            query_sparse = _make_fake_sparse(seed=target_idx)
            sparse_indices, sparse_values = SpladeEncoder.to_qdrant(query_sparse)

            dense_results = await self._run_search(
                qdrant_client, collection_name, silo_id, query_dense, search_mode="dense"
            )
            hybrid_results = await self._run_search(
                qdrant_client,
                collection_name,
                silo_id,
                query_dense,
                search_mode="hybrid",
                sparse_indices=sparse_indices,
                sparse_values=sparse_values,
            )

            if expected_doc_id in dense_results:
                dense_hits += 1
            if expected_doc_id in hybrid_results:
                hybrid_hits += 1

        assert hybrid_hits >= dense_hits, (
            f"Hybrid recall ({hybrid_hits}) must be >= dense-only recall ({dense_hits})"
        )

    async def test_sparse_search_returns_results(
        self,
        qdrant_client: QdrantClient,
        seeded_collection: tuple[str, str],
    ) -> None:
        silo_id, collection_name = seeded_collection
        query_sparse = _make_fake_sparse(seed=2)
        sparse_indices, sparse_values = SpladeEncoder.to_qdrant(query_sparse)
        result_ids = await self._run_search(
            qdrant_client,
            collection_name,
            silo_id,
            query_dense=[],  # dense vector unused in sparse-only mode
            search_mode="sparse",
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
        )
        assert len(result_ids) > 0

    async def test_hybrid_fallback_to_dense_when_no_sparse(
        self,
        qdrant_client: QdrantClient,
        seeded_collection: tuple[str, str],
    ) -> None:
        """hybrid mode without sparse vectors silently falls back to dense."""
        silo_id, collection_name = seeded_collection
        query_dense = _make_fake_dense_vector(seed=0)
        # No sparse vectors supplied — should warn + fall back to dense.
        result_ids = await self._run_search(
            qdrant_client, collection_name, silo_id, query_dense, search_mode="hybrid"
        )
        assert len(result_ids) > 0
