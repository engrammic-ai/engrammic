from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Registry: (silo_id, service_name) -> CircuitBreaker
# Ensures CB state persists across requests for the same silo/service pair.
#
# NOTE: _registry_lock is bound to the event loop that imports this module.
# All current callers (FastAPI, Dagster ops, MCP tools) run on a single shared
# loop per process, so this is safe today. If a future caller spins a private
# loop and reimports, the lock will not arbitrate across loops — switch to a
# per-loop registry then.
_registry: dict[tuple[str, str], CircuitBreaker] = {}
_registry_lock = asyncio.Lock()


async def get_or_create(
    silo_id: str,
    service_name: str,
    *,
    failure_threshold: int,
    window_s: float,
    cooldown_s: float,
    now_fn: Callable[[], float] = time.monotonic,
) -> CircuitBreaker:
    """Return the shared CircuitBreaker for (silo_id, service_name), creating it if absent."""
    key = (silo_id, service_name)
    async with _registry_lock:
        if key not in _registry:
            _registry[key] = CircuitBreaker(
                failure_threshold=failure_threshold,
                window_s=window_s,
                cooldown_s=cooldown_s,
                now_fn=now_fn,
            )
        return _registry[key]


class CircuitBreaker:
    """Simple sliding-window circuit breaker.

    Open state is implied: once failures-within-window reaches the threshold,
    is_open() returns True until cooldown_s elapses since the last-recorded
    failure; after that window resets empty.

    All mutating methods acquire an asyncio.Lock to prevent races when
    multiple coroutines share the same instance.
    """

    def __init__(
        self,
        failure_threshold: int,
        window_s: float,
        cooldown_s: float,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.window_s = window_s
        self.cooldown_s = cooldown_s
        self._now = now_fn
        self._failures: deque[float] = deque()
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    async def record_failure(self) -> None:
        async with self._lock:
            now = self._now()
            self._failures.append(now)
            self._prune(now)
            if len(self._failures) >= self.failure_threshold and self._opened_at is None:
                self._opened_at = now

    async def record_success(self) -> None:
        async with self._lock:
            self._failures.clear()
            self._opened_at = None

    async def is_open(self) -> bool:
        async with self._lock:
            now = self._now()
            if self._opened_at is not None:
                if now - self._opened_at >= self.cooldown_s:
                    # cooldown elapsed — reset
                    self._failures.clear()
                    self._opened_at = None
                    return False
                return True
            self._prune(now)
            return len(self._failures) >= self.failure_threshold

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()
