"""Transitive invalidation of inferred CAUSES edges.

When a direct CAUSES edge is superseded, any inferred edges that were derived
from it (tracked via inferred_from_edge_ids) must be tombstoned.  This module
provides the core async helper so it can be called from custodian/supersession
code without importing the Dagster asset layer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_FIND_DERIVED_EDGES = """
MATCH ()-[r:CAUSES {silo_id: $silo_id}]->()
WHERE $superseded_edge_id IN r.inferred_from_edge_ids
  AND r.inferred = true
RETURN r.id AS derived_edge_id
"""

_TOMBSTONE_DERIVED_EDGE = """
MATCH ()-[r:CAUSES {id: $edge_id, silo_id: $silo_id}]->()
SET r.invalidated = true,
    r.invalidated_at = $invalidated_at,
    r.invalidation_reason = $reason
"""


async def invalidate_derived_edges(
    client: Any,
    superseded_edge_id: str,
    silo_id: str,
    *,
    max_depth: int = 3,
    reason: str = "source_superseded",
) -> int:
    """Tombstone inferred CAUSES edges that depended on a superseded direct edge.

    Walks the derived-edge graph up to ``max_depth`` hops.  Each discovered
    inferred edge is marked with ``invalidated = true`` so queries can filter it
    out without a physical delete.

    Parameters
    ----------
    client:
        A MemgraphClient-compatible object with ``execute_query`` and
        ``execute_write`` coroutine methods.
    superseded_edge_id:
        The ID of the CAUSES edge that was superseded.
    silo_id:
        Silo scope for all queries.
    max_depth:
        Maximum cascade hops.  Defaults to CausalConfig.max_invalidation_depth.
    reason:
        Reason string stored on the tombstoned edge for auditability.

    Returns
    -------
    int
        Number of derived edges tombstoned.
    """
    now = datetime.now(UTC).isoformat()
    frontier: set[str] = {superseded_edge_id}
    visited: set[str] = set()
    tombstoned = 0

    for _ in range(max_depth):
        if not frontier:
            break

        next_frontier: set[str] = set()
        for edge_id in frontier:
            if edge_id in visited:
                continue
            visited.add(edge_id)

            rows = await client.execute_query(
                _FIND_DERIVED_EDGES,
                {"superseded_edge_id": edge_id, "silo_id": silo_id},
            )
            for row in rows:
                derived_id: str = str(row["derived_edge_id"])
                if derived_id in visited:
                    continue
                await client.execute_write(
                    _TOMBSTONE_DERIVED_EDGE,
                    {
                        "edge_id": derived_id,
                        "silo_id": silo_id,
                        "invalidated_at": now,
                        "reason": reason,
                    },
                )
                tombstoned += 1
                next_frontier.add(derived_id)

        frontier = next_frontier

    logger.debug(
        "causal_invalidation_complete",
        superseded_edge_id=superseded_edge_id,
        silo_id=silo_id,
        tombstoned=tombstoned,
        max_depth=max_depth,
    )
    return tombstoned
