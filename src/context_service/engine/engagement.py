"""Engagement detection for recall responses.

Queries Redis marker index and pending ProposedBeliefs to build an engagement
payload surfaced to the agent when recalling nodes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from context_service.db.queries import (
    GET_PENDING_PROPOSED_BELIEFS_FOR_CLAIMS,
    GET_PROPOSED_BELIEFS_FOR_SILO,
)
from context_service.engine.markers import (
    get_all_pending_markers,
    get_marker_details,
    get_markers_for_about_set,
)

_SILO_PROPOSED_BELIEF_LIMIT = 50

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


def _build_summary(marker: dict[str, Any]) -> str:
    """Build human-readable summary for a marker."""
    marker_type = marker.get("marker_type")
    if marker_type == "Contradiction":
        node_a = marker.get("node_a_id", "unknown")
        node_b = marker.get("node_b_id", "unknown")
        return f"Contradiction between {node_a} and {node_b}"
    elif marker_type == "StaleCommitment":
        commitment_id = marker.get("commitment_id", "unknown")
        return f"Commitment {commitment_id} may be stale"
    elif marker_type == "ProposedBelief":
        content = marker.get("content", "")
        preview = content[:80] + "..." if len(content) > 80 else content
        return f"System synthesized belief: {preview}"
    return "Unknown marker"


def _get_decision_required(marker_type: str) -> str:
    """Return the decision action required for a marker type."""
    if marker_type == "ProposedBelief":
        return "accept"
    return "dismiss"


async def get_engagement_for_about_set(
    redis: Redis[bytes],  # type: ignore[type-arg]
    store: HyperGraphStore,
    silo_id: str,
    about_ids: list[str],
) -> dict[str, Any] | None:
    """Query markers and pending ProposedBeliefs for an about_id set.

    Parameters
    ----------
    redis:
        Async Redis client for marker index lookups.
    store:
        HyperGraphStore for graph queries.
    silo_id:
        Silo scope.
    about_ids:
        Node IDs to check for engagement markers.

    Returns
    -------
    Engagement payload dict with mode and markers list, or None if no markers.
    """
    if not about_ids:
        return None

    markers_out: list[dict[str, Any]] = []

    # 1. Get Contradiction/StaleCommitment markers from Redis index
    marker_ids = await get_markers_for_about_set(redis, silo_id, about_ids)
    if marker_ids:
        marker_details = await get_marker_details(store, silo_id, marker_ids)
        for m in marker_details:
            if m.get("status") != "pending":
                continue
            marker_type = m.get("marker_type", "")
            markers_out.append({
                "marker_id": str(m.get("id", "")),
                "marker_type": marker_type,
                "summary": _build_summary(m),
                "node_ids": m.get("about_ids", []),
                "detected_at": m.get("detected_at", ""),
                "decision_required": _get_decision_required(marker_type),
            })

    # 2. Get pending ProposedBeliefs that touch the about_ids
    try:
        proposed_rows = await store.execute_query(
            GET_PENDING_PROPOSED_BELIEFS_FOR_CLAIMS,
            {"silo_id": silo_id, "about_ids": about_ids},
        )
        for pb in proposed_rows:
            if pb.get("status") != "pending":
                continue
            markers_out.append({
                "marker_id": str(pb.get("id", "")),
                "marker_type": "ProposedBelief",
                "summary": _build_summary({"marker_type": "ProposedBelief", "content": pb.get("content", "")}),
                "node_ids": pb.get("about_ids", []),
                "detected_at": pb.get("created_at", ""),
                "decision_required": "accept",
            })
    except Exception as exc:
        logger.warning(
            "engagement_proposed_beliefs_query_failed",
            silo_id=silo_id,
            error=str(exc),
        )

    if not markers_out:
        return None

    return {
        "mode": "soft",
        "markers": markers_out,
    }


async def get_engagement_for_silo(
    redis: Redis[bytes],  # type: ignore[type-arg]  # noqa: ARG001
    store: HyperGraphStore,
    silo_id: str,
) -> dict[str, Any] | None:
    """Query all pending markers and ProposedBeliefs for a silo.

    Used by the no-hint tick path to surface all pending engagement for the
    silo without scoping to a specific about_id set. Returns the same shape
    as :func:`get_engagement_for_about_set`.

    Parameters
    ----------
    redis:
        Async Redis client (unused for this path; accepted for API symmetry
        with :func:`get_engagement_for_about_set`).
    store:
        HyperGraphStore for graph queries.
    silo_id:
        Silo scope.

    Returns
    -------
    Engagement payload dict with mode and markers list, or None if no markers.
    """
    markers_out: list[dict[str, Any]] = []

    # 1. Get Contradiction/StaleCommitment markers from the graph
    marker_ids = await get_all_pending_markers(store, silo_id)
    if marker_ids:
        marker_details = await get_marker_details(store, silo_id, marker_ids)
        for m in marker_details:
            if m.get("status") != "pending":
                continue
            marker_type = m.get("marker_type", "")
            markers_out.append({
                "marker_id": str(m.get("id", "")),
                "marker_type": marker_type,
                "summary": _build_summary(m),
                "node_ids": m.get("about_ids", []),
                "detected_at": m.get("detected_at", ""),
                "decision_required": _get_decision_required(marker_type),
            })

    # 2. Get all pending ProposedBeliefs for the silo
    try:
        proposed_rows = await store.execute_query(
            GET_PROPOSED_BELIEFS_FOR_SILO,
            {"silo_id": silo_id, "limit": _SILO_PROPOSED_BELIEF_LIMIT},
        )
        for pb in proposed_rows:
            markers_out.append({
                "marker_id": str(pb.get("proposed_belief_id", "")),
                "marker_type": "ProposedBelief",
                "summary": _build_summary({"marker_type": "ProposedBelief", "content": pb.get("content", "")}),
                "node_ids": pb.get("source_fact_ids", []),
                "detected_at": pb.get("created_at", ""),
                "decision_required": "accept",
            })
    except Exception as exc:
        logger.warning(
            "engagement_silo_proposed_beliefs_query_failed",
            silo_id=silo_id,
            error=str(exc),
        )

    if not markers_out:
        return None

    return {
        "mode": "soft",
        "markers": markers_out,
    }
