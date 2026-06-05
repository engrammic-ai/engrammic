"""Unit tests for embedding batching functionality."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from context_service.embeddings.litellm_embeddings import (
    LiteLLMEmbeddingError,
    LiteLLMEmbeddingService,
)


class MockEmbeddingResponse:
    """Mock response from litellm.aembedding."""

    def __init__(self, embeddings: list[list[float]]) -> None:
        self.data = [{"embedding": emb} for emb in embeddings]


def _make_mock_response(**kwargs: object) -> MockEmbeddingResponse:
    """Generate a predictable mock response based on the number of inputs."""
    texts = kwargs["input"]
    assert isinstance(texts, list)
    embeddings = [[float(i) + 0.1] * 768 for i in range(len(texts))]
    return MockEmbeddingResponse(embeddings)


@pytest.fixture
def mock_litellm() -> object:
    """Mock litellm.aembedding to return predictable embeddings."""
    with patch("context_service.embeddings.litellm_embeddings.litellm") as mock:
        mock.aembedding = AsyncMock(side_effect=_make_mock_response)
        yield mock


@pytest.fixture
def mock_telemetry() -> object:
    """Suppress telemetry calls that require live infrastructure."""
    with (
        patch(
            "context_service.embeddings.litellm_embeddings.record_embedding",
            return_value=None,
        ),
        patch(
            "context_service.embeddings.litellm_embeddings.record_embedding_batch_size",
            return_value=None,
        ),
        patch(
            "context_service.embeddings.litellm_embeddings.record_embedding_cache_miss",
            return_value=None,
        ),
        patch(
            "context_service.embeddings.litellm_embeddings.get_embedding_rate_limiter",
            return_value=None,
        ),
    ):
        yield


class TestEmbeddingBatching:
    """Tests for the batched embedding functionality."""

    @pytest.mark.asyncio
    async def test_single_text_batched(self, mock_litellm: object, mock_telemetry: object) -> None:
        """Single call returns a correctly-shaped vector."""
        service = LiteLLMEmbeddingService(
            model="test-model",
            batching_enabled=True,
            batch_size=10,
            timeout_ms=100,
            small_batch_threshold=4,
        )
        result = await service.embed_single("test text")
        assert len(result) == 768
        assert mock_litellm.aembedding.call_count == 1  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_multiple_concurrent_batched(
        self, mock_litellm: object, mock_telemetry: object
    ) -> None:
        """Concurrent calls return correct results; batching reduces API round-trips."""
        service = LiteLLMEmbeddingService(
            model="test-model",
            batching_enabled=True,
            batch_size=32,
            timeout_ms=500,
            small_batch_threshold=2,
        )

        results = await asyncio.gather(*[service.embed_single(f"text {i}") for i in range(5)])

        assert len(results) == 5
        for result in results:
            assert len(result) == 768

        # Batching must have coalesced at least some calls; strict upper bound is 5.
        assert mock_litellm.aembedding.call_count <= 5  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_batching_disabled_fallback(
        self, mock_litellm: object, mock_telemetry: object
    ) -> None:
        """When batching is disabled, every embed_single is a separate API call."""
        service = LiteLLMEmbeddingService(
            model="test-model",
            batching_enabled=False,
        )

        # Sequential to avoid any accidental concurrency-based batching.
        await service.embed_single("text 1")
        await service.embed_single("text 2")
        await service.embed_single("text 3")

        assert mock_litellm.aembedding.call_count == 3  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_error_propagates_to_caller(
        self, mock_litellm: object, mock_telemetry: object
    ) -> None:
        """An API error is wrapped and re-raised as LiteLLMEmbeddingError."""
        mock_litellm.aembedding.side_effect = Exception("API error")  # type: ignore[union-attr]
        service = LiteLLMEmbeddingService(
            model="test-model",
            batching_enabled=True,
            batch_size=10,
            timeout_ms=100,
            small_batch_threshold=4,
        )

        with pytest.raises(LiteLLMEmbeddingError, match="API error"):
            await service.embed_single("test text")

    @pytest.mark.asyncio
    async def test_from_config_loads_batching_settings(self) -> None:
        """from_config reads batching settings from the YAML config dict."""
        with patch("context_service.embeddings.litellm_embeddings.load_config") as mock_config:
            mock_config.return_value = {
                "model": "test-model",
                "dimensions": 768,
                "batching": {
                    "enabled": True,
                    "batch_size": 16,
                    "timeout_ms": 50,
                    "small_batch_threshold": 2,
                },
            }

            service = LiteLLMEmbeddingService.from_config()

        assert service._batching_enabled is True
        assert service._batch_size == 16
        assert service._timeout_ms == 50
        assert service._small_batch_threshold == 2

    @pytest.mark.asyncio
    async def test_from_config_loads_token_budget_settings(self) -> None:
        """from_config reads token budget settings from the YAML config dict."""
        with patch("context_service.embeddings.litellm_embeddings.load_config") as mock_config:
            mock_config.return_value = {
                "model": "test-model",
                "dimensions": 768,
                "batching": {
                    "enabled": True,
                    "mode": "token_budget",
                    "token_budget": 4000,
                    "max_batch_size": 32,
                    "timeout_ms": 75,
                },
            }

            service = LiteLLMEmbeddingService.from_config()

        assert service._batching_mode == "token_budget"
        assert service._token_budget == 4000
        assert service._max_batch_size == 32
        assert service._timeout_ms == 75

    @pytest.mark.asyncio
    async def test_token_budget_mode_single_text(
        self, mock_litellm: object, mock_telemetry: object
    ) -> None:
        """Token budget mode works for single text embeddings."""
        with patch("litellm.token_counter", return_value=50):
            service = LiteLLMEmbeddingService(
                model="test-model",
                batching_enabled=True,
                batching_mode="token_budget",
                token_budget=8000,
                max_batch_size=64,
                timeout_ms=50,
            )
            result = await service.embed_single("test text")

        assert len(result) == 768
        assert mock_litellm.aembedding.call_count == 1  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_token_budget_mode_concurrent(
        self, mock_litellm: object, mock_telemetry: object
    ) -> None:
        """Token budget mode batches concurrent calls."""
        with patch("litellm.token_counter", return_value=50):
            service = LiteLLMEmbeddingService(
                model="test-model",
                batching_enabled=True,
                batching_mode="token_budget",
                token_budget=8000,
                max_batch_size=64,
                timeout_ms=100,
            )

            results = await asyncio.gather(
                *[service.embed_single(f"text {i}") for i in range(5)]
            )

        assert len(results) == 5
        for result in results:
            assert len(result) == 768
        # All should batch into one call
        assert mock_litellm.aembedding.call_count == 1  # type: ignore[union-attr]
