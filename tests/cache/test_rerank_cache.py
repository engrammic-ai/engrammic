"""Tests for semantic rerank cache."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.cache.rerank_cache import (
    RERANK_CACHE_COLLECTION,
    SemanticRerankCache,
    _doc_ids_hash,
    _sha256_short,
)


class TestHashFunctions:
    """Test helper hash functions."""

    def test_sha256_short_deterministic(self) -> None:
        """Same input produces same output."""
        assert _sha256_short("test") == _sha256_short("test")

    def test_sha256_short_length(self) -> None:
        """Output is 16 characters."""
        assert len(_sha256_short("test")) == 16

    def test_doc_ids_hash_order_independent(self) -> None:
        """Hash is same regardless of doc ID order."""
        ids1 = ["a", "b", "c"]
        ids2 = ["c", "a", "b"]
        assert _doc_ids_hash(ids1) == _doc_ids_hash(ids2)

    def test_doc_ids_hash_different_for_different_ids(self) -> None:
        """Different doc IDs produce different hashes."""
        assert _doc_ids_hash(["a", "b"]) != _doc_ids_hash(["a", "c"])


class TestSemanticRerankCache:
    """Test SemanticRerankCache."""

    @pytest.fixture
    def mock_qdrant(self) -> MagicMock:
        """Create a mock QdrantClient."""
        mock = MagicMock()
        mock._get_client = AsyncMock()
        return mock

    @pytest.fixture
    def cache(self, mock_qdrant: MagicMock) -> SemanticRerankCache:
        """Create a cache instance with mocked Qdrant."""
        return SemanticRerankCache(
            qdrant=mock_qdrant,
            similarity_threshold=0.95,
            l1_ttl_seconds=300,
            l1_maxsize=100,
        )

    @pytest.mark.asyncio
    async def test_l1_exact_hit(self, cache: SemanticRerankCache) -> None:
        """Exact same query and docs returns cached scores from L1."""
        query = "test query"
        doc_ids = ["doc1", "doc2"]
        scores = [("doc1", 0.9), ("doc2", 0.8)]
        embedding = [0.1] * 768

        # Prime the L1 cache
        l1_key = cache._l1_key(query, doc_ids, "silo1")
        cache._l1[l1_key] = scores

        # Should hit L1, not touch Qdrant
        with patch("context_service.cache.rerank_cache.record_cache_hit") as mock_hit:
            result = await cache.get(query, embedding, doc_ids, "silo1")

        assert result == scores
        mock_hit.assert_called_once_with("rerank_l1", silo_id="silo1")

    @pytest.mark.asyncio
    async def test_l1_miss_different_query(self, cache: SemanticRerankCache) -> None:
        """Different query misses L1 cache."""
        doc_ids = ["doc1", "doc2"]
        scores = [("doc1", 0.9), ("doc2", 0.8)]
        embedding = [0.1] * 768

        # Prime L1 with one query
        cache._l1[cache._l1_key("query1", doc_ids, "silo1")] = scores

        # Mock L2 to return no results
        mock_client = AsyncMock()
        mock_client.get_collections = AsyncMock(
            return_value=MagicMock(collections=[MagicMock(name=RERANK_CACHE_COLLECTION)])
        )
        mock_client.search = AsyncMock(return_value=[])
        cache._qdrant._get_client = AsyncMock(return_value=mock_client)

        # Different query should miss L1
        with patch("context_service.cache.rerank_cache.record_cache_miss") as mock_miss:
            result = await cache.get("query2", embedding, doc_ids, "silo1")

        assert result is None
        mock_miss.assert_called_once_with("rerank", silo_id="silo1")

    @pytest.mark.asyncio
    async def test_l2_semantic_hit(
        self, cache: SemanticRerankCache, mock_qdrant: MagicMock
    ) -> None:
        """Similar query hits L2 cache."""
        query = "test query"
        doc_ids = ["doc1", "doc2"]
        embedding = [0.1] * 768
        stored_scores = [{"doc_id": "doc1", "score": 0.9}, {"doc_id": "doc2", "score": 0.8}]

        # Mock L2 search to return a hit
        mock_result = MagicMock()
        mock_result.score = 0.97  # Above threshold
        mock_result.payload = {"scores": stored_scores}

        mock_client = AsyncMock()
        mock_client.get_collections = AsyncMock(
            return_value=MagicMock(collections=[MagicMock(name=RERANK_CACHE_COLLECTION)])
        )
        mock_client.search = AsyncMock(return_value=[mock_result])
        mock_qdrant._get_client = AsyncMock(return_value=mock_client)

        with patch("context_service.cache.rerank_cache.record_cache_hit") as mock_hit:
            result = await cache.get(query, embedding, doc_ids, "silo1")

        assert result == [("doc1", 0.9), ("doc2", 0.8)]
        mock_hit.assert_called_once_with("rerank_l2", silo_id="silo1")

        # Should also warm L1
        assert cache._l1_key(query, doc_ids, "silo1") in cache._l1

    @pytest.mark.asyncio
    async def test_l2_below_threshold_miss(
        self, cache: SemanticRerankCache, mock_qdrant: MagicMock
    ) -> None:
        """Query below similarity threshold misses L2."""
        query = "test query"
        doc_ids = ["doc1", "doc2"]
        embedding = [0.1] * 768

        # Mock L2 search to return a result below threshold
        mock_result = MagicMock()
        mock_result.score = 0.90  # Below 0.95 threshold

        mock_client = AsyncMock()
        mock_client.get_collections = AsyncMock(
            return_value=MagicMock(collections=[MagicMock(name=RERANK_CACHE_COLLECTION)])
        )
        mock_client.search = AsyncMock(return_value=[mock_result])
        mock_qdrant._get_client = AsyncMock(return_value=mock_client)

        with patch("context_service.cache.rerank_cache.record_cache_miss") as mock_miss:
            result = await cache.get(query, embedding, doc_ids, "silo1")

        assert result is None
        mock_miss.assert_called_once_with("rerank", silo_id="silo1")

    @pytest.mark.asyncio
    async def test_set_stores_in_both_levels(
        self, cache: SemanticRerankCache, mock_qdrant: MagicMock
    ) -> None:
        """Set stores scores in both L1 and L2."""
        query = "test query"
        doc_ids = ["doc1", "doc2"]
        scores = [("doc1", 0.9), ("doc2", 0.8)]
        embedding = [0.1] * 768

        mock_client = AsyncMock()
        mock_client.get_collections = AsyncMock(
            return_value=MagicMock(collections=[MagicMock(name=RERANK_CACHE_COLLECTION)])
        )
        mock_client.upsert = AsyncMock()
        mock_qdrant._get_client = AsyncMock(return_value=mock_client)

        await cache.set(query, embedding, doc_ids, scores, "silo1")

        # L1 should be populated
        assert cache._l1[cache._l1_key(query, doc_ids, "silo1")] == scores

        # L2 should have been called
        mock_client.upsert.assert_called_once()
        call_args = mock_client.upsert.call_args
        assert call_args.kwargs["collection_name"] == RERANK_CACHE_COLLECTION

    @pytest.mark.asyncio
    async def test_different_docs_miss(self, cache: SemanticRerankCache) -> None:
        """Same query but different docs misses cache."""
        query = "test query"
        scores = [("doc1", 0.9), ("doc2", 0.8)]
        embedding = [0.1] * 768

        # Prime L1 with doc1, doc2
        cache._l1[cache._l1_key(query, ["doc1", "doc2"], "silo1")] = scores

        # Query with doc1, doc3 should miss
        mock_client = AsyncMock()
        mock_client.get_collections = AsyncMock(
            return_value=MagicMock(collections=[MagicMock(name=RERANK_CACHE_COLLECTION)])
        )
        mock_client.search = AsyncMock(return_value=[])
        cache._qdrant._get_client = AsyncMock(return_value=mock_client)

        result = await cache.get(query, embedding, ["doc1", "doc3"], "silo1")
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_collection_on_first_use(
        self, cache: SemanticRerankCache, mock_qdrant: MagicMock
    ) -> None:
        """Collection is created if it doesn't exist."""
        mock_client = AsyncMock()
        mock_client.get_collections = AsyncMock(
            return_value=MagicMock(collections=[])  # No collections
        )
        mock_client.create_collection = AsyncMock()
        mock_client.create_payload_index = AsyncMock()
        mock_client.search = AsyncMock(return_value=[])
        mock_qdrant._get_client = AsyncMock(return_value=mock_client)

        await cache.get("query", [0.1] * 768, ["doc1"], "silo1")

        mock_client.create_collection.assert_called_once()
        assert mock_client.create_payload_index.call_count == 2  # silo_id and doc_ids_hash
