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

    async def retry_after_seconds(self) -> float:
        """Return seconds until the circuit resets; 0.0 if currently closed."""
        async with self._lock:
            if self._opened_at is None:
                return 0.0
            now = self._now()
            remaining = self.cooldown_s - (now - self._opened_at)
            return max(0.0, remaining)

    async def record_failure(self) -> bool:
        """Record a failure; returns True if the circuit just transitioned to open."""
        async with self._lock:
            now = self._now()
            self._failures.append(now)
            self._prune(now)
            if len(self._failures) >= self.failure_threshold and self._opened_at is None:
                self._opened_at = now
                return True
            return False

    async def record_success(self) -> bool:
        """Record a success; returns True if the circuit just transitioned to closed."""
        async with self._lock:
            was_open = self._opened_at is not None
            self._failures.clear()
            self._opened_at = None
            return was_open

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

    async def check_open(self) -> tuple[bool, bool]:
        """Return (is_open, just_closed).

        just_closed is True when the cooldown window elapsed on this check,
        transitioning the circuit from open to closed. Callers that need
        to log/emit on the closed transition should use this method instead
        of is_open().
        """
        async with self._lock:
            now = self._now()
            if self._opened_at is not None:
                if now - self._opened_at >= self.cooldown_s:
                    self._failures.clear()
                    self._opened_at = None
                    return False, True
                return True, False
            self._prune(now)
            return len(self._failures) >= self.failure_threshold, False

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()
