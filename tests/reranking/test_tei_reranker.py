"""Tests for TEIReranker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.reranking.reranker import RerankResult
from context_service.reranking.tei_reranker import TEIReranker, TEIRerankerError


class TestTEIReranker:
    @pytest.mark.asyncio
    async def test_rerank_returns_results(self) -> None:
        """Mock httpx response and verify correct RerankResult list is returned."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [
            {"index": 1, "score": 0.95},
            {"index": 0, "score": 0.80},
            {"index": 2, "score": 0.60},
        ]

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        reranker = TEIReranker(base_url="http://localhost:8082")
        reranker._client = mock_client

        results = await reranker.rerank(
            query="what was rejected?",
            documents=["doc zero", "doc one", "doc two"],
            node_ids=["node-0", "node-1", "node-2"],
            top_k=3,
        )

        assert len(results) == 3
        assert results[0] == RerankResult(node_id="node-1", score=0.95, original_rank=1)
        assert results[1] == RerankResult(node_id="node-0", score=0.80, original_rank=0)
        assert results[2] == RerankResult(node_id="node-2", score=0.60, original_rank=2)

        mock_client.post.assert_called_once_with(
            "/rerank",
            json={"query": "what was rejected?", "texts": ["doc zero", "doc one", "doc two"]},
        )

    @pytest.mark.asyncio
    async def test_rerank_empty_documents(self) -> None:
        """Returns empty list without making any network call."""
        mock_client = AsyncMock()

        reranker = TEIReranker(base_url="http://localhost:8082")
        reranker._client = mock_client

        results = await reranker.rerank(
            query="test",
            documents=[],
            node_ids=[],
            top_k=10,
        )

        assert results == []
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_rerank_validates_document_node_id_length(self) -> None:
        """Raises ValueError when documents and node_ids have different lengths."""
        reranker = TEIReranker(base_url="http://localhost:8082")

        with pytest.raises(ValueError, match="must have same length"):
            await reranker.rerank(
                query="test",
                documents=["doc0", "doc1"],
                node_ids=["node-0"],
                top_k=2,
            )

    @pytest.mark.asyncio
    async def test_rerank_raises_tei_error_after_retries(self) -> None:
        """TEIRerankerError is raised after all retry attempts are exhausted."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

        reranker = TEIReranker(base_url="http://localhost:8082")
        reranker._client = mock_client

        with (
            patch("context_service.reranking.tei_reranker.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(TEIRerankerError),
        ):
            await reranker.rerank(
                query="test",
                documents=["doc0"],
                node_ids=["node-0"],
                top_k=1,
            )
