"""Tests for LiteLLMReranker."""

from __future__ import annotations

from context_service.reranking.reranker import RerankResult


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
