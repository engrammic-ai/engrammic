"""Tests for TokenBudgetBatcher."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from context_service.embeddings.token_budget_batcher import TokenBudgetBatcher


@pytest.fixture
def mock_embed_fn() -> AsyncMock:
    """Mock embedding function that returns vectors of the same length as texts."""

    async def _embed(texts: list[str]) -> list[list[float]]:
        return [[1.0, 2.0, 3.0] for _ in texts]

    return AsyncMock(side_effect=_embed)


@pytest.fixture
def batcher(mock_embed_fn: AsyncMock) -> TokenBudgetBatcher:
    """Create a TokenBudgetBatcher with test config."""
    return TokenBudgetBatcher(
        model="test-model",
        embed_fn=mock_embed_fn,
        token_budget=100,
        max_batch_size=10,
        timeout_ms=50,
    )


class TestTokenBudgetBatcher:
    """Tests for TokenBudgetBatcher."""

    @pytest.mark.asyncio
    async def test_single_text_returns_embedding(
        self, batcher: TokenBudgetBatcher, mock_embed_fn: AsyncMock
    ) -> None:
        """Basic functionality: single text returns its embedding."""
        with patch("litellm.token_counter", return_value=10):
            result = await batcher.embed_single("hello world")

        assert result == [1.0, 2.0, 3.0]
        mock_embed_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_budget_triggers_flush(
        self, mock_embed_fn: AsyncMock
    ) -> None:
        """Batch flushes when token budget is exceeded."""
        batcher = TokenBudgetBatcher(
            model="test-model",
            embed_fn=mock_embed_fn,
            token_budget=50,
            max_batch_size=10,
            timeout_ms=1000,
        )

        # First text: 30 tokens (under budget)
        # Second text: 30 tokens (would push to 60, over 50 budget)
        token_counts = [30, 30]
        call_idx = 0

        def mock_count(model: str, text: str) -> int:
            nonlocal call_idx
            result = token_counts[call_idx % len(token_counts)]
            call_idx += 1
            return result

        with patch("litellm.token_counter", side_effect=mock_count):
            # Start both embeds concurrently
            task1 = asyncio.create_task(batcher.embed_single("short text"))
            await asyncio.sleep(0.01)  # Let first text get queued
            task2 = asyncio.create_task(batcher.embed_single("another text"))

            results = await asyncio.gather(task1, task2)

        assert len(results) == 2
        # First text triggers flush before second is added
        assert mock_embed_fn.call_count == 2

    @pytest.mark.asyncio
    async def test_max_batch_size_triggers_flush(
        self, mock_embed_fn: AsyncMock
    ) -> None:
        """Batch flushes at max count even if under token budget."""
        batcher = TokenBudgetBatcher(
            model="test-model",
            embed_fn=mock_embed_fn,
            token_budget=10000,  # Very high
            max_batch_size=3,
            timeout_ms=1000,
        )

        with patch("litellm.token_counter", return_value=10):
            # Queue 4 texts - should trigger flush after 3rd
            tasks = [
                asyncio.create_task(batcher.embed_single(f"text {i}"))
                for i in range(4)
            ]
            results = await asyncio.gather(*tasks)

        assert len(results) == 4
        # Should have flushed at least once due to max_batch_size
        assert mock_embed_fn.call_count >= 2

    @pytest.mark.asyncio
    async def test_timeout_flushes_partial(
        self, mock_embed_fn: AsyncMock
    ) -> None:
        """Partial batch flushes after timeout expires."""
        batcher = TokenBudgetBatcher(
            model="test-model",
            embed_fn=mock_embed_fn,
            token_budget=10000,
            max_batch_size=100,
            timeout_ms=50,
        )

        with patch("litellm.token_counter", return_value=10):
            # Single text, well under budget and count
            result = await batcher.embed_single("solo text")

        assert result == [1.0, 2.0, 3.0]
        mock_embed_fn.assert_called_once()
        # Should have been called via timeout, not budget/count trigger

    @pytest.mark.asyncio
    async def test_concurrent_calls_batched(
        self, mock_embed_fn: AsyncMock
    ) -> None:
        """Multiple concurrent calls are batched together."""
        batcher = TokenBudgetBatcher(
            model="test-model",
            embed_fn=mock_embed_fn,
            token_budget=1000,
            max_batch_size=100,
            timeout_ms=50,
        )

        with patch("litellm.token_counter", return_value=10):
            # Start 5 concurrent embeds
            tasks = [
                asyncio.create_task(batcher.embed_single(f"text {i}"))
                for i in range(5)
            ]
            results = await asyncio.gather(*tasks)

        assert len(results) == 5
        # All should have been batched into one call
        assert mock_embed_fn.call_count == 1
        # Verify batch contained all 5 texts
        call_args = mock_embed_fn.call_args[0][0]
        assert len(call_args) == 5

    @pytest.mark.asyncio
    async def test_long_text_solo_batch(
        self, mock_embed_fn: AsyncMock
    ) -> None:
        """Text near budget limit batches alone."""
        batcher = TokenBudgetBatcher(
            model="test-model",
            embed_fn=mock_embed_fn,
            token_budget=100,
            max_batch_size=10,
            timeout_ms=50,
        )

        # First text: 90 tokens (almost at budget)
        # Second text: 20 tokens (would exceed budget)
        token_counts = iter([90, 20])

        def mock_count(model: str, text: str) -> int:
            return next(token_counts)

        with patch("litellm.token_counter", side_effect=mock_count):
            task1 = asyncio.create_task(batcher.embed_single("long text here"))
            await asyncio.sleep(0.01)
            task2 = asyncio.create_task(batcher.embed_single("short"))

            results = await asyncio.gather(task1, task2)

        assert len(results) == 2
        # First text should flush before second is added
        assert mock_embed_fn.call_count == 2

    @pytest.mark.asyncio
    async def test_error_propagates_to_all(
        self, mock_embed_fn: AsyncMock
    ) -> None:
        """API error fails all waiters in the batch."""
        mock_embed_fn.side_effect = RuntimeError("API error")

        batcher = TokenBudgetBatcher(
            model="test-model",
            embed_fn=mock_embed_fn,
            token_budget=1000,
            max_batch_size=100,
            timeout_ms=50,
        )

        with patch("litellm.token_counter", return_value=10):
            tasks = [
                asyncio.create_task(batcher.embed_single(f"text {i}"))
                for i in range(3)
            ]

            # All should raise the same error
            for task in tasks:
                with pytest.raises(RuntimeError, match="API error"):
                    await task

    @pytest.mark.asyncio
    async def test_litellm_token_counter_used(
        self, batcher: TokenBudgetBatcher, mock_embed_fn: AsyncMock
    ) -> None:
        """Verifies LiteLLM tokenizer is called with correct model."""
        with patch("litellm.token_counter", return_value=10) as mock_counter:
            await batcher.embed_single("test text")

        mock_counter.assert_called_once_with(model="test-model", text="test text")

    @pytest.mark.asyncio
    async def test_close_flushes_pending(
        self, mock_embed_fn: AsyncMock
    ) -> None:
        """close() flushes any remaining pending items."""
        batcher = TokenBudgetBatcher(
            model="test-model",
            embed_fn=mock_embed_fn,
            token_budget=10000,
            max_batch_size=100,
            timeout_ms=10000,  # Very long timeout
        )

        with patch("litellm.token_counter", return_value=10):
            # Start an embed but don't wait for timeout
            task = asyncio.create_task(batcher.embed_single("pending text"))
            await asyncio.sleep(0.01)  # Let it queue

            # Close should flush immediately
            await batcher.close()

            result = await task

        assert result == [1.0, 2.0, 3.0]
        mock_embed_fn.assert_called_once()
