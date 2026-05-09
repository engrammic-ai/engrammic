from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CustodianTrigger(Protocol):
    """Swappable trigger mechanism for Custodian identity."""

    async def enqueue(self, silo_id: str, node_id: str, event_type: str) -> None:
        """Enqueue a node for custodian processing."""
        ...

    async def flush(self, silo_id: str) -> list[str]:
        """Flush pending nodes for a silo, return node_ids."""
        ...
