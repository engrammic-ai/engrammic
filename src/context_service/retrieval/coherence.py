"""Coherence filtering for recall results.

Filters dominated contradictions to return a coherent worldview.
When A contradicts B, keep only the winner (higher layer or higher confidence).
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Layer hierarchy for domination logic (higher = stronger)
# Spec: Belief/Commitment > Fact > Claim > Memory
# We map by layer name; node-type refinement can be added later
LAYER_ORDER: dict[str, int] = {
    "wisdom": 4,
    "knowledge": 3,
    "memory": 2,
    "intelligence": 1,  # Not in spec, treat as lowest
}


def _get_layer_rank(layer: str | None) -> int:
    """Get layer rank for domination comparison."""
    if layer is None:
        return 0
    return LAYER_ORDER.get(layer.lower(), 0)


def _dominates(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Check if node A dominates node B in epistemic hierarchy.

    Domination rules:
    1. Higher layer wins (wisdom > knowledge > memory)
    2. Same layer: higher confidence wins
    3. Same layer and confidence: more recent wins (by created_at)
    """
    a_rank = _get_layer_rank(a.get("layer"))
    b_rank = _get_layer_rank(b.get("layer"))

    if a_rank > b_rank:
        return True
    if a_rank < b_rank:
        return False

    # Same layer: compare confidence
    a_conf = float(a.get("confidence") or 0.0)
    b_conf = float(b.get("confidence") or 0.0)

    if a_conf > b_conf:
        return True
    if a_conf < b_conf:
        return False

    # Same confidence: more recent wins
    a_created = a.get("created_at")
    b_created = b.get("created_at")
    if a_created and b_created:
        return bool(a_created > b_created)

    # Tie: A doesn't dominate
    return False


def filter_dominated_contradictions(
    results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Filter out dominated nodes from contradiction pairs.

    For each pair of nodes that contradict each other (both in results),
    keep only the winner. Returns (filtered_results, filtered_count).

    Args:
        results: List of result dicts, each with:
            - node_id: str
            - layer: str
            - confidence: float
            - contradicts: list[str]  # node IDs this node contradicts

    Returns:
        Tuple of (filtered_results, filtered_count)
    """
    if not results:
        return results, 0

    # Build node_id -> result mapping
    by_id: dict[str, dict[str, Any]] = {r["node_id"]: r for r in results if "node_id" in r}

    # Find contradiction pairs within result set
    # Only consider pairs where both nodes are in results
    dominated_ids: set[str] = set()

    for node_id, node in by_id.items():
        contradicts = node.get("contradicts") or []
        for other_id in contradicts:
            if other_id not in by_id:
                continue  # Other node not in results
            if other_id in dominated_ids:
                continue  # Already marked as dominated
            if node_id in dominated_ids:
                continue  # This node already dominated

            other = by_id[other_id]

            # Determine winner
            if _dominates(node, other):
                dominated_ids.add(other_id)
                logger.debug(
                    "coherence_filter_dominated",
                    winner=node_id,
                    loser=other_id,
                    winner_layer=node.get("layer"),
                    loser_layer=other.get("layer"),
                )
            elif _dominates(other, node):
                dominated_ids.add(node_id)
                logger.debug(
                    "coherence_filter_dominated",
                    winner=other_id,
                    loser=node_id,
                    winner_layer=other.get("layer"),
                    loser_layer=node.get("layer"),
                )
            # If neither dominates (tie), keep both

    if not dominated_ids:
        return results, 0

    filtered = [r for r in results if r.get("node_id") not in dominated_ids]
    filtered_count = len(dominated_ids)

    logger.info(
        "coherence_filter_applied",
        original_count=len(results),
        filtered_count=filtered_count,
        remaining_count=len(filtered),
    )

    return filtered, filtered_count
