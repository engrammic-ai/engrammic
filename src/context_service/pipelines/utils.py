"""Shared utilities for Dagster pipelines."""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any


def run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running.

    Used by Dagster assets and sensors that need to call async code from sync contexts.
    If no event loop is running, uses asyncio.run(). If a loop is already running
    (e.g., when Dagster runs in an async context), submits to a ThreadPoolExecutor.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)
