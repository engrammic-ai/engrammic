"""Integration test for embedding batching flow."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from context_service.embeddings.litellm_embeddings import LiteLLMEmbeddingService


class MockEmbeddingResponse:
    """Mock response from litellm.aembedding."""
    def __init__(self, embeddings: list[list[float]]):
        self.data = [{"embedding": emb} for emb in embeddings]


@pytest.mark.integration
class TestBatchEmbeddingFlow:
    """Integration tests for embedding batching effectiveness."""

    @pytest.mark.asyncio
    async def test_batch_embedding_reduces_api_calls(self):
        """Emit N concurrent embedding requests, verify fewer than N API calls."""
        api_call_count = 0

        async def mock_aembedding(**kwargs):
            nonlocal api_call_count
            api_call_count += 1
            texts = kwargs["input"]
            # Return embeddings for all texts in the batch
            return MockEmbeddingResponse([[0.1] * 768 for _ in texts])

        with patch("context_service.embeddings.litellm_embeddings.litellm") as mock_litellm, \
             patch("context_service.embeddings.litellm_embeddings.record_embedding"), \
             patch("context_service.embeddings.litellm_embeddings.record_embedding_cache_miss"), \
             patch("context_service.embeddings.litellm_embeddings.record_embedding_batch_size"), \
             patch("context_service.embeddings.litellm_embeddings.get_embedding_rate_limiter", return_value=None):

            mock_litellm.aembedding = AsyncMock(side_effect=mock_aembedding)

            service = LiteLLMEmbeddingService(
                model="test-model",
                batching_enabled=True,
                batch_size=32,
                timeout_ms=200,
                small_batch_threshold=4,
            )

            # Fire 20 concurrent embedding requests
            n_requests = 20
            results = await asyncio.gather(*[
                service.embed_single(f"text {i}") for i in range(n_requests)
            ])

            # All results should be returned
            assert len(results) == n_requests
            for result in results:
                assert len(result) == 768

            # Should have made fewer than N API calls (batching worked)
            assert api_call_count < n_requests, (
                f"Expected batching to reduce API calls, but got {api_call_count} calls for {n_requests} requests"
            )
            # Should have made at least 1 call
            assert api_call_count >= 1

    @pytest.mark.asyncio
    async def test_batching_disabled_no_reduction(self):
        """With batching disabled, each request makes its own API call."""
        api_call_count = 0

        async def mock_aembedding(**kwargs):
            nonlocal api_call_count
            api_call_count += 1
            texts = kwargs["input"]
            return MockEmbeddingResponse([[0.1] * 768 for _ in texts])

        with patch("context_service.embeddings.litellm_embeddings.litellm") as mock_litellm, \
             patch("context_service.embeddings.litellm_embeddings.record_embedding"), \
             patch("context_service.embeddings.litellm_embeddings.record_embedding_cache_miss"), \
             patch("context_service.embeddings.litellm_embeddings.record_embedding_batch_size"), \
             patch("context_service.embeddings.litellm_embeddings.get_embedding_rate_limiter", return_value=None):

            mock_litellm.aembedding = AsyncMock(side_effect=mock_aembedding)

            service = LiteLLMEmbeddingService(
                model="test-model",
                batching_enabled=False,
            )

            # Fire requests sequentially (to avoid any accidental batching)
            n_requests = 5
            for i in range(n_requests):
                await service.embed_single(f"text {i}")

            # Each request should have made its own API call
            assert api_call_count == n_requests
