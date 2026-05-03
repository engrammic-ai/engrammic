"""Heat lookup.

Reads ``n.heat_score`` from Memgraph, falling back to a neutral 0.5 when the
property is absent (i.e. the heat asset has not yet run for this node).

Phase 1 shipped a stub that returned 0.5 unconditionally; that stub is gone.
If you see heat scores that look uniformly neutral, check that the heat Dagster
asset is scheduled and has completed at least one run for the silo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

DEFAULT_HEAT = 0.5

_GET_HEAT_QUERY = "MATCH (n {id: $id, silo_id: $silo_id}) RETURN coalesce(n.heat_score, 0.5) AS h"


async def get_heat(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
) -> float:
    """Return the heat score for a node.

    Queries the graph store for ``n.heat_score`` and falls back to
    ``DEFAULT_HEAT`` (0.5) when the property is absent or the node is not
    found.

    Uses ``execute_query`` escape hatch because heat_score is a raw node
    property not surfaced by any domain-level protocol method (tech debt).

    Args:
        store: HyperGraphStore protocol implementation.
        node_id: Node ID (string form of the UUID).
        silo_id: Silo the node belongs to.

    Returns:
        Float heat score in [0.0, 1.0] (typically).
    """
    try:
        rows: list[dict[str, Any]] = await store.execute_query(
            _GET_HEAT_QUERY,
            {"id": str(node_id), "silo_id": silo_id},
        )
        return float(rows[0]["h"]) if rows else DEFAULT_HEAT
    except Exception as exc:
        logger.warning(
            "heat_lookup_failed",
            node_id=node_id,
            silo_id=silo_id,
            error=str(exc),
        )
        return DEFAULT_HEAT


__all__ = ["DEFAULT_HEAT", "get_heat"]
