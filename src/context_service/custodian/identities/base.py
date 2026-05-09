from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore


@dataclass
class IdentityDeps:
    """Shared dependency container for all identities."""

    org_id: str
    silo_id: str
    memgraph_client: HyperGraphStore | None = None
    node_ids: list[str] = field(default_factory=list)
