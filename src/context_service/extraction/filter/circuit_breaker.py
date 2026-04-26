from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class CircuitBreaker:
    """Simple sliding-window circuit breaker.

    Open state is implied: once failures-within-window reaches the threshold,
    is_open() returns True until cooldown_s elapses since the last-recorded
    failure; after that window resets empty.
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

    def record_failure(self) -> None:
        now = self._now()
        self._failures.append(now)
        self._prune(now)
        if len(self._failures) >= self.failure_threshold and self._opened_at is None:
            self._opened_at = now

    def record_success(self) -> None:
        self._failures.clear()
        self._opened_at = None

    def is_open(self) -> bool:
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
