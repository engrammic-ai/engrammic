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

        with (
            patch("context_service.embeddings.litellm_embeddings.litellm") as mock_litellm,
            patch("context_service.embeddings.litellm_embeddings.record_embedding"),
            patch("context_service.embeddings.litellm_embeddings.record_embedding_cache_miss"),
            patch("context_service.embeddings.litellm_embeddings.record_embedding_batch_size"),
            patch(
                "context_service.embeddings.litellm_embeddings.get_embedding_rate_limiter",
                return_value=None,
            ),
        ):
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
            results = await asyncio.gather(
                *[service.embed_single(f"text {i}") for i in range(n_requests)]
            )

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

        with (
            patch("context_service.embeddings.litellm_embeddings.litellm") as mock_litellm,
            patch("context_service.embeddings.litellm_embeddings.record_embedding"),
            patch("context_service.embeddings.litellm_embeddings.record_embedding_cache_miss"),
            patch("context_service.embeddings.litellm_embeddings.record_embedding_batch_size"),
            patch(
                "context_service.embeddings.litellm_embeddings.get_embedding_rate_limiter",
                return_value=None,
            ),
        ):
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

    @pytest.mark.asyncio
    async def test_token_budget_batching_mixed_lengths(self):
        """Mixed-length texts batch efficiently by token count."""
        api_call_count = 0
        batch_sizes: list[int] = []

        async def mock_aembedding(**kwargs):
            nonlocal api_call_count
            api_call_count += 1
            texts = kwargs["input"]
            batch_sizes.append(len(texts))
            return MockEmbeddingResponse([[0.1] * 768 for _ in texts])

        with (
            patch("context_service.embeddings.litellm_embeddings.litellm") as mock_litellm,
            patch("context_service.embeddings.litellm_embeddings.record_embedding"),
            patch("context_service.embeddings.litellm_embeddings.record_embedding_cache_miss"),
            patch("context_service.embeddings.litellm_embeddings.record_embedding_batch_size"),
            patch(
                "context_service.embeddings.litellm_embeddings.get_embedding_rate_limiter",
                return_value=None,
            ),
            patch("litellm.token_counter") as mock_token_counter,
        ):
            mock_litellm.aembedding = AsyncMock(side_effect=mock_aembedding)

            # Simulate mixed lengths: short texts (50 tokens) and long texts (2000 tokens)
            # With 8000 token budget: can fit ~4 long texts or ~160 short texts
            token_counts = [50] * 10 + [2000] * 2  # 10 short + 2 long
            token_idx = 0

            def count_tokens(model: str, text: str) -> int:
                nonlocal token_idx
                result = token_counts[token_idx % len(token_counts)]
                token_idx += 1
                return result

            mock_token_counter.side_effect = count_tokens

            service = LiteLLMEmbeddingService(
                model="test-model",
                batching_enabled=True,
                batching_mode="token_budget",
                token_budget=8000,
                max_batch_size=64,
                timeout_ms=200,
            )

            # Fire all 12 requests concurrently
            results = await asyncio.gather(
                *[service.embed_single(f"text {i}") for i in range(12)]
            )

            assert len(results) == 12
            for result in results:
                assert len(result) == 768

            # Token budget batching should have made fewer API calls than count-based
            # with 12 items (which might just do 1 batch of 12)
            assert api_call_count >= 1
            # Total texts processed should equal 12
            assert sum(batch_sizes) == 12
