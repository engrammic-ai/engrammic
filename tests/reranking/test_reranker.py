"""Tests for LiteLLMReranker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.reranking.reranker import LiteLLMReranker, RerankResult


class TestRerankResult:
    def test_rerank_result_fields(self) -> None:
        result = RerankResult(
            node_id="node-123",
            score=0.95,
            original_rank=2,
        )
        assert result.node_id == "node-123"
        assert result.score == 0.95
        assert result.original_rank == 2


class TestLiteLLMReranker:
    @pytest.mark.asyncio
    async def test_rerank_returns_sorted_results(self) -> None:
        mock_response = MagicMock()
        mock_response.results = [
            {"index": 1, "relevance_score": 0.95},
            {"index": 0, "relevance_score": 0.80},
            {"index": 2, "relevance_score": 0.60},
        ]

        with patch("context_service.reranking.reranker.litellm") as mock_litellm:
            mock_litellm.arerank = AsyncMock(return_value=mock_response)

            reranker = LiteLLMReranker(model="vertex_ai/semantic-ranker-default@latest")
            results = await reranker.rerank(
                query="what was rejected?",
                documents=["doc zero", "doc one", "doc two"],
                node_ids=["node-0", "node-1", "node-2"],
                top_k=3,
            )

            assert len(results) == 3
            assert results[0].node_id == "node-1"
            assert results[0].score == 0.95
            assert results[0].original_rank == 1
            assert results[1].node_id == "node-0"
            assert results[2].node_id == "node-2"

    @pytest.mark.asyncio
    async def test_rerank_empty_documents_returns_empty(self) -> None:
        reranker = LiteLLMReranker(model="vertex_ai/semantic-ranker-default@latest")
        results = await reranker.rerank(
            query="test",
            documents=[],
            node_ids=[],
            top_k=10,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_rerank_fallback_on_error(self) -> None:
        with patch("context_service.reranking.reranker.litellm") as mock_litellm:
            mock_litellm.arerank = AsyncMock(side_effect=Exception("API error"))

            reranker = LiteLLMReranker(model="vertex_ai/semantic-ranker-default@latest")
            results = await reranker.rerank(
                query="test",
                documents=["doc0", "doc1"],
                node_ids=["node-0", "node-1"],
                top_k=2,
            )

            # Fallback: returns original order
            assert len(results) == 2
            assert results[0].node_id == "node-0"
            assert results[1].node_id == "node-1"
