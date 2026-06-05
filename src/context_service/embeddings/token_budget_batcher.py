"""Token-budget based embedding batcher.

Batches embedding requests by token count rather than fixed count,
maximizing API utilization for variable-length texts.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

import litellm

from context_service.config.logging import get_logger
from context_service.telemetry.recorder import record_embedding_token_utilization

logger = get_logger(__name__)


class TokenBudgetBatcher:
    """Batches async embedding calls by token count using LiteLLM's tokenizer.

    Instead of "batch up to N texts", batches "up to ~T tokens worth of text".
    This maximizes API utilization when text lengths vary significantly.
    """

    def __init__(
        self,
        model: str,
        embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
        token_budget: int = 8000,
        max_batch_size: int = 64,
        timeout_ms: int = 100,
    ) -> None:
        """Initialize the token budget batcher.

        Args:
            model: LiteLLM model identifier for tokenization.
            embed_fn: Async function that embeds a batch of texts.
            token_budget: Maximum tokens per batch.
            max_batch_size: Maximum texts per batch (hard cap).
            timeout_ms: Max wait time before flushing a partial batch.
        """
        self._model = model
        self._embed_fn = embed_fn
        self._token_budget = token_budget
        self._max_batch_size = max_batch_size
        self._timeout_s = timeout_ms / 1000

        self._pending: list[tuple[str, int, asyncio.Future[list[float]]]] = []
        self._current_tokens: int = 0
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None

    def _count_tokens(self, text: str) -> int:
        """Count tokens using LiteLLM's model-aware tokenizer."""
        count: int = litellm.token_counter(model=self._model, text=text)
        return count

    async def embed_single(self, text: str) -> list[float]:
        """Add text to batch, return its embedding when batch completes.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.

        Raises:
            Exception: If embedding fails (propagated to all waiters).
        """
        tokens = self._count_tokens(text)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[list[float]] = loop.create_future()

        async with self._lock:
            # Would this text push us over budget?
            if (
                self._current_tokens + tokens > self._token_budget
                or len(self._pending) >= self._max_batch_size
            ):
                await self._flush_locked()

            self._pending.append((text, tokens, future))
            self._current_tokens += tokens

            # Start timeout if this is first item
            if len(self._pending) == 1:
                self._flush_task = asyncio.create_task(self._flush_after_timeout())

        return await future

    async def _flush_after_timeout(self) -> None:
        """Flush pending batch after timeout expires."""
        await asyncio.sleep(self._timeout_s)
        async with self._lock:
            if self._pending:
                await self._flush_locked()

    async def _flush_locked(self) -> None:
        """Flush pending batch. Caller must hold lock."""
        if not self._pending:
            return

        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task

        texts = [t for t, _, _ in self._pending]
        futures = [f for _, _, f in self._pending]
        token_count = self._current_tokens

        self._pending = []
        self._current_tokens = 0
        self._flush_task = None

        logger.debug(
            "token_budget_batch_flush",
            batch_size=len(texts),
            tokens_used=token_count,
            token_budget=self._token_budget,
            utilization_pct=int((token_count / self._token_budget) * 100),
        )

        try:
            embeddings = await self._embed_fn(texts)
            # Record utilization only on success
            record_embedding_token_utilization(token_count, self._token_budget)
            for future, embedding in zip(futures, embeddings, strict=True):
                if not future.done():
                    future.set_result(embedding)
        except Exception as e:
            for future in futures:
                if not future.done():
                    future.set_exception(e)

    async def close(self) -> None:
        """Flush any remaining pending items and clean up."""
        async with self._lock:
            if self._pending:
                await self._flush_locked()
