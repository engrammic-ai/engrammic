"""Global LLM concurrency limiter.

Prevents unbounded concurrent LLM API calls that can exhaust quota and memory
when many callers (e.g. clustering summarization) fire simultaneously.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore, initializing it on first call."""
    global _semaphore
    if _semaphore is None:
        from context_service.config.settings import get_settings

        limit = get_settings().llm_max_concurrency
        _semaphore = asyncio.Semaphore(limit)
    return _semaphore


async def with_llm_limit[T](coro: Coroutine[Any, Any, T]) -> T:
    """Await *coro* under the global LLM concurrency semaphore."""
    async with get_semaphore():
        return await coro
