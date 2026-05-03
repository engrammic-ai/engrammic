"""Global LLM concurrency limiter.

Prevents unbounded concurrent LLM API calls that can exhaust quota and memory
when many callers (e.g. clustering summarization) fire simultaneously.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def reset_semaphore() -> None:
    """Discard the cached semaphore so it will be recreated on the next call.

    Call this in test teardown (or whenever a new event loop is started) to
    prevent the semaphore from being tied to a closed loop.
    """
    global _semaphore, _semaphore_loop
    _semaphore = None
    _semaphore_loop = None


def get_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore, reinitializing if the loop changed."""
    global _semaphore, _semaphore_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _semaphore is None or current_loop is not _semaphore_loop:
        from context_service.config.settings import get_settings

        limit = get_settings().llm_max_concurrency
        _semaphore = asyncio.Semaphore(limit)
        _semaphore_loop = current_loop
    return _semaphore


async def with_llm_limit[T](coro: Coroutine[Any, Any, T]) -> T:
    """Await *coro* under the global LLM concurrency semaphore."""
    async with get_semaphore():
        return await coro
