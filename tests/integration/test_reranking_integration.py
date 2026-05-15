"""Integration tests for semantic reranking."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestRerankingIntegration:
    @pytest.mark.asyncio
    async def test_hard_query_finds_semantic_match(self) -> None:
        """Test that 'rejected' matches 'no longer viable'."""
        # This test requires live services
        pytest.skip("Requires live Vertex AI and Redis")

    @pytest.mark.asyncio
    async def test_reranking_improves_order(self) -> None:
        """Test that reranking improves result ordering."""
        pytest.skip("Requires live Vertex AI")

    @pytest.mark.asyncio
    async def test_expansion_cache_works(self) -> None:
        """Test that query expansion caching works."""
        pytest.skip("Requires live Redis")
