"""Engine-layer exceptions."""

from __future__ import annotations


class EngineError(Exception):
    """Base exception for engine operations."""


class StaleVersionError(EngineError):
    """Raised when a node update has a stale version (optimistic concurrency)."""

    def __init__(self, node_id: str, expected: int, actual: int) -> None:
        self.node_id = node_id
        self.expected = expected
        self.actual = actual
        super().__init__(f"Node {node_id}: expected version {expected}, found {actual}")


class StorageCircuitOpenError(EngineError):
    """Raised when a storage backend circuit breaker is open.

    Carries a retry_after_seconds hint so callers can implement backoff
    without polling.
    """

    def __init__(self, store: str, retry_after_seconds: float) -> None:
        self.store = store
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Storage circuit open for {store!r}; retry after {retry_after_seconds:.1f}s"
        )
