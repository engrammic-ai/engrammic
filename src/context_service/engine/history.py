"""Belief history: supersession chain traversal and confidence trend analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass
class BeliefState:
    node_id: str
    content: str
    confidence: float
    valid_from: datetime | None
    valid_to: datetime | None
    status: Literal["current", "superseded"]
    superseded_by: str | None


@dataclass
class BeliefHistory:
    subject: str
    timeline: list[BeliefState]
    total_versions: int
    confidence_trend: Literal["increasing", "decreasing", "stable", "volatile"]


def compute_confidence_trend(
    confidences: list[float],
) -> Literal["increasing", "decreasing", "stable", "volatile"]:
    """Compute the confidence trend across a belief chain.

    Rules:
    - Empty or single value: "stable"
    - Monotonically increasing: "increasing"
    - Monotonically decreasing: "decreasing"
    - Max-min delta > 0.2 and non-monotonic: "volatile"
    - Otherwise: "stable"
    """
    if len(confidences) <= 1:
        return "stable"

    delta = max(confidences) - min(confidences)
    diffs = [confidences[i + 1] - confidences[i] for i in range(len(confidences) - 1)]

    if all(d >= 0 for d in diffs) and any(d > 0 for d in diffs):
        return "increasing"
    if all(d <= 0 for d in diffs) and any(d < 0 for d in diffs):
        return "decreasing"
    if delta > 0.2:
        return "volatile"
    return "stable"


def build_belief_timeline(subject_id: str, rows: list[dict[str, Any]]) -> BeliefHistory:
    """Build a BeliefHistory from Memgraph query rows.

    Args:
        subject_id: The node ID used as the query start.
        rows: Rows from GET_SUPERSESSION_CHAIN query, each with keys:
              id, content, confidence, valid_from, valid_to, superseded_by

    Returns:
        BeliefHistory with deduplicated, cycle-safe timeline.
    """
    seen_ids: set[str] = set()
    states: list[BeliefState] = []

    for row in rows:
        node_id = row["id"]
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)

        valid_to = row.get("valid_to")
        superseded_by = row.get("superseded_by")
        status: Literal["current", "superseded"] = (
            "superseded" if valid_to is not None or superseded_by is not None else "current"
        )

        states.append(
            BeliefState(
                node_id=node_id,
                content=row.get("content") or "",
                confidence=float(row.get("confidence") or 0.0),
                valid_from=row.get("valid_from"),
                valid_to=valid_to,
                status=status,
                superseded_by=superseded_by,
            )
        )

    states.sort(key=lambda s: (s.valid_from is None, s.valid_from))
    confidences = [s.confidence for s in states]
    trend = compute_confidence_trend(confidences)

    return BeliefHistory(
        subject=subject_id,
        timeline=states,
        total_versions=len(states),
        confidence_trend=trend,
    )


async def get_belief_history(
    memgraph: Any,
    silo_id: str,
    start_id: str,
    limit: int = 20,
) -> BeliefHistory:
    """Query Memgraph for the supersession chain anchored at start_id."""
    from context_service.db.queries import GET_SUPERSESSION_CHAIN

    rows = await memgraph.execute_query(
        GET_SUPERSESSION_CHAIN,
        {"start_id": start_id, "silo_id": silo_id, "limit": limit},
    )
    return build_belief_timeline(start_id, rows)
