"""Heat lookup.

Phase 1 (this file) is a stub returning a neutral 0.5 so the priority formula
remains well-defined while the real heat asset is deferred to Phase 2.
The function signature is the Phase 2 signature so callers don't refactor
when the stub flips to a Memgraph read.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_service.stores import MemgraphClient

logger = logging.getLogger(__name__)

STUB_HEAT_VALUE = 0.5

# Process-local set: silo_ids for which we have already emitted the
# heat.stub_active log line. Cleared in tests via fixture.
_STUB_LOG_GUARD: set[str] = set()


async def get_heat(
    memgraph: MemgraphClient,  # noqa: ARG001  -- Phase 2 will use this
    node_id: str,  # noqa: ARG001  -- Phase 2 will use this
    silo_id: str,
) -> float:
    """Return the heat score for a node.

    Phase 1: returns ``STUB_HEAT_VALUE`` (0.5) without touching Memgraph.
    Phase 2: reads ``n.heat_score`` from Memgraph; falls back to 0.5 if absent.
    """
    if silo_id not in _STUB_LOG_GUARD:
        _STUB_LOG_GUARD.add(silo_id)
        logger.info("heat.stub_active", extra={"silo_id": silo_id})
    return STUB_HEAT_VALUE


__all__ = ["STUB_HEAT_VALUE", "get_heat"]
