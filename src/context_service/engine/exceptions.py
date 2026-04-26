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
