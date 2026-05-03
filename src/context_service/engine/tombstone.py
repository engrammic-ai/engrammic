"""Tombstone helpers for ops tooling.

Extracted from pipelines/assets/causal_tombstone.py so the core logic can be
imported without pulling in the Dagster asset decorator.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Cypher templates
# ---------------------------------------------------------------------------

_FIND_MATCHING_EDGES_TEMPLATE = (
    "MATCH ()-[r:CAUSES {{silo_id: $silo_id}}]->()\n"
    "WHERE r.invalidated IS NULL OR r.invalidated = false\n"
    "{edge_type_filter}\n"
    "{confidence_filter}\n"
    "{created_before_filter}\n"
    "RETURN r.id AS edge_id\n"
    "LIMIT $batch_limit"
)

_TOMBSTONE_EDGE = """
MATCH ()-[r:CAUSES {id: $edge_id, silo_id: $silo_id}]->()
SET r.invalidated = true,
    r.invalidated_at = $invalidated_at,
    r.invalidation_reason = $reason
"""


def build_find_query(
    edge_type: str | None,
    confidence_below: float | None,
    created_before: datetime | None,
) -> str:
    """Build the edge-finder Cypher query from filter arguments."""
    edge_type_filter = f"AND type(r) = '{edge_type}'" if edge_type else ""
    confidence_filter = (
        f"AND (r.consensus_confidence < {confidence_below} OR r.extraction_confidence < {confidence_below})"
        if confidence_below is not None
        else ""
    )
    created_before_filter = (
        f"AND r.created_at < '{created_before.isoformat()}'" if created_before else ""
    )
    return _FIND_MATCHING_EDGES_TEMPLATE.format(
        edge_type_filter=edge_type_filter,
        confidence_filter=confidence_filter,
        created_before_filter=created_before_filter,
    )


async def run_tombstone(
    client: Any,
    silo_id: str,
    *,
    edge_ids: list[str] | None = None,
    edge_type: str | None = None,
    confidence_below: float | None = None,
    created_before: datetime | None = None,
    max_invalidation_depth: int = 3,
    batch_limit: int = 500,
) -> dict[str, int]:
    """Tombstone edges matching the criteria and cascade to derived inferences.

    Parameters
    ----------
    client:
        MemgraphClient-compatible object.
    silo_id:
        Silo scope — no cross-silo writes are performed.
    edge_ids:
        If supplied, tombstone exactly these edges (filter args are ignored).
    edge_type:
        Edge type filter (CAUSES / CORROBORATES / PREVENTS).
    confidence_below:
        Tombstone edges with confidence strictly below this threshold.
    created_before:
        Tombstone edges created before this timestamp.
    max_invalidation_depth:
        Max cascade hops for derived-edge invalidation.
    batch_limit:
        Max edges returned by the filter query in one pass.

    Returns
    -------
    dict with keys ``direct`` and ``derived`` — counts of tombstoned edges.
    """
    from context_service.engine.causal_invalidation import invalidate_derived_edges

    now = datetime.now(UTC).isoformat()
    direct_tombstoned = 0
    derived_tombstoned = 0

    if edge_ids is not None:
        target_ids = list(edge_ids)
    else:
        query = build_find_query(edge_type, confidence_below, created_before)
        rows = await client.execute_query(
            query,
            {"silo_id": silo_id, "batch_limit": batch_limit},
        )
        target_ids = [str(row["edge_id"]) for row in rows]

    for edge_id in target_ids:
        await client.execute_write(
            _TOMBSTONE_EDGE,
            {
                "edge_id": edge_id,
                "silo_id": silo_id,
                "invalidated_at": now,
                "reason": "ops_tombstone",
            },
        )
        direct_tombstoned += 1

        count = await invalidate_derived_edges(
            client,
            superseded_edge_id=edge_id,
            silo_id=silo_id,
            max_depth=max_invalidation_depth,
            reason="ops_tombstone_cascade",
        )
        derived_tombstoned += count

    logger.debug(
        "tombstone_complete",
        silo_id=silo_id,
        direct=direct_tombstoned,
        derived=derived_tombstoned,
    )
    return {"direct": direct_tombstoned, "derived": derived_tombstoned}
