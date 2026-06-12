"""Marker helper functions with Redis index sync.

Thin wrappers around Contradiction and StaleCommitment CRUD queries.
All writes go to the graph first; Redis index is updated after. If Redis
fails, the graph record is still valid and GET_MARKERS_BY_ABOUT_ID serves
as a graph-side fallback. Failures are logged and not re-raised.

Redis key pattern:
    markers:{silo_id}:about:{node_id}  ->  sorted set of marker_ids
    Score: detected_at as Unix timestamp (float).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from context_service.db.queries import (
    CREATE_CONTRADICTION,
    CREATE_STALE_COMMITMENT,
    GET_ALL_PENDING_MARKERS_FOR_SILO,
    GET_MARKERS_BY_IDS,
    UPDATE_MARKER_STATUS,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

# Redis key helpers
_ABOUT_KEY = "markers:{silo_id}:about:{node_id}"


def _about_key(silo_id: str, node_id: str) -> str:
    return _ABOUT_KEY.format(silo_id=silo_id, node_id=node_id)


def _score(dt: datetime) -> float:
    """Convert a datetime to a Redis sorted-set score (Unix epoch float)."""
    return dt.timestamp()


# ---------------------------------------------------------------------------
# Create helpers
# ---------------------------------------------------------------------------


async def create_contradiction(
    store: HyperGraphStore,
    redis: Redis[bytes],
    silo_id: str,
    node_a_id: str,
    node_b_id: str,
    about_ids: list[str],
    confidence: float,
    expires_hours: int = 168,
) -> dict[str, Any]:
    """Create a :Contradiction marker node and update the Redis index.

    Parameters
    ----------
    store:
        HyperGraphStore (Memgraph) used for the write.
    redis:
        Async Redis client.
    silo_id:
        Silo scope.
    node_a_id, node_b_id:
        The two conflicting node IDs.
    about_ids:
        All node IDs this contradiction touches (used for index).
    confidence:
        LLM confidence in the contradiction (0.0-1.0).
    expires_hours:
        Hours until the marker expires. Default 168 (7 days).

    Returns
    -------
    dict with marker fields including ``marker_id`` and ``detected_at``.
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=expires_hours)
    marker_id = str(uuid.uuid4())

    params: dict[str, Any] = {
        "id": marker_id,
        "silo_id": silo_id,
        "node_a_id": node_a_id,
        "node_b_id": node_b_id,
        "about_ids": about_ids,
        "confidence": confidence,
        "detected_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }

    rows = await store.execute_write(CREATE_CONTRADICTION, params)
    if not rows:
        raise RuntimeError(f"CREATE_CONTRADICTION returned no rows for silo={silo_id}")

    logger.info(
        "marker_created",
        marker_type="Contradiction",
        marker_id=marker_id,
        silo_id=silo_id,
        about_count=len(about_ids),
    )

    await _index_marker(redis, silo_id, marker_id, about_ids, score=_score(now))

    return {
        "marker_id": marker_id,
        "marker_type": "Contradiction",
        "silo_id": silo_id,
        "status": "pending",
        "node_a_id": node_a_id,
        "node_b_id": node_b_id,
        "about_ids": about_ids,
        "confidence": confidence,
        "detected_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


async def create_stale_commitment(
    store: HyperGraphStore,
    redis: Redis[bytes],
    silo_id: str,
    commitment_id: str,
    evidence_ids: list[str],
    about_ids: list[str],
    expires_hours: int = 168,
) -> dict[str, Any]:
    """Create a :StaleCommitment marker node and update the Redis index.

    Parameters
    ----------
    store:
        HyperGraphStore (Memgraph) used for the write.
    redis:
        Async Redis client.
    silo_id:
        Silo scope.
    commitment_id:
        The Commitment node that is now stale.
    evidence_ids:
        New evidence nodes that undermine the commitment.
    about_ids:
        All node IDs this marker touches (for index).
    expires_hours:
        Hours until the marker expires. Default 168 (7 days).

    Returns
    -------
    dict with marker fields including ``marker_id`` and ``detected_at``.
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=expires_hours)
    marker_id = str(uuid.uuid4())

    params: dict[str, Any] = {
        "id": marker_id,
        "silo_id": silo_id,
        "commitment_id": commitment_id,
        "evidence_ids": evidence_ids,
        "about_ids": about_ids,
        "detected_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }

    rows = await store.execute_write(CREATE_STALE_COMMITMENT, params)
    if not rows:
        raise RuntimeError(f"CREATE_STALE_COMMITMENT returned no rows for silo={silo_id}")

    logger.info(
        "marker_created",
        marker_type="StaleCommitment",
        marker_id=marker_id,
        silo_id=silo_id,
        about_count=len(about_ids),
    )

    await _index_marker(redis, silo_id, marker_id, about_ids, score=_score(now))

    return {
        "marker_id": marker_id,
        "marker_type": "StaleCommitment",
        "silo_id": silo_id,
        "status": "pending",
        "commitment_id": commitment_id,
        "evidence_ids": evidence_ids,
        "about_ids": about_ids,
        "detected_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Status transition helpers
# ---------------------------------------------------------------------------


async def resolve_marker(
    store: HyperGraphStore,
    redis: Redis[bytes],
    silo_id: str,
    marker_id: str,
    resolution: str,
) -> dict[str, Any]:
    """Set marker status to 'resolved' and remove from Redis index.

    Fetches about_ids first (one read) to know which Redis keys to clean.

    Parameters
    ----------
    store:
        HyperGraphStore used for graph reads/writes.
    redis:
        Async Redis client.
    silo_id:
        Silo scope.
    marker_id:
        ID of the marker to resolve.
    resolution:
        Human-readable description of how the contradiction/staleness was
        addressed.

    Returns
    -------
    dict with ``marker_id``, ``marker_type``, and ``status``.
    """
    return await _transition_marker(
        store, redis, silo_id, marker_id, status="resolved", reason=resolution
    )


async def dismiss_marker(
    store: HyperGraphStore,
    redis: Redis[bytes],
    silo_id: str,
    marker_id: str,
    reason: str,
) -> dict[str, Any]:
    """Set marker status to 'dismissed' and remove from Redis index.

    Parameters
    ----------
    store:
        HyperGraphStore used for graph reads/writes.
    redis:
        Async Redis client.
    silo_id:
        Silo scope.
    marker_id:
        ID of the marker to dismiss.
    reason:
        Human-readable reason for dismissal.

    Returns
    -------
    dict with ``marker_id``, ``marker_type``, and ``status``.
    """
    return await _transition_marker(
        store, redis, silo_id, marker_id, status="dismissed", reason=reason
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


async def get_markers_for_about_set(
    redis: Redis[bytes],
    silo_id: str,
    about_ids: list[str],
) -> list[str]:
    """Return marker IDs that touch any node in ``about_ids``.

    Uses a Redis pipeline to fetch sorted sets for each about_id in one
    round-trip, then deduplicates in Python. Returns marker IDs only; call
    :func:`get_marker_details` for full marker data.

    Parameters
    ----------
    redis:
        Async Redis client.
    silo_id:
        Silo scope.
    about_ids:
        Nodes whose markers you want to surface.

    Returns
    -------
    Deduplicated list of marker_id strings (most-recently-detected first
    across the union).
    """
    if not about_ids:
        return []

    try:
        pipe = redis.pipeline(transaction=False)
        for node_id in about_ids:
            pipe.zrange(_about_key(silo_id, node_id), 0, -1)
        results: list[list[bytes]] = await pipe.execute()
    except Exception as exc:
        logger.warning(
            "markers_redis_lookup_failed",
            silo_id=silo_id,
            about_count=len(about_ids),
            error=str(exc),
        )
        return []

    seen: set[str] = set()
    marker_ids: list[str] = []
    for bucket in results:
        for raw in bucket:
            mid = raw.decode() if isinstance(raw, bytes) else raw
            if mid not in seen:
                seen.add(mid)
                marker_ids.append(mid)

    return marker_ids


async def get_all_pending_markers(
    store: HyperGraphStore,
    silo_id: str,
) -> list[str]:
    """Return all pending (non-expired) marker IDs for a silo.

    Queries the graph directly for Contradiction and StaleCommitment nodes
    with status='pending' that have not yet expired. Used by the tick verb
    to surface engagement without a specific about_id set.

    Parameters
    ----------
    store:
        HyperGraphStore used for graph reads.
    silo_id:
        Silo scope.

    Returns
    -------
    List of marker_id strings, most-recently-detected first.
    """
    rows = await store.execute_query(
        GET_ALL_PENDING_MARKERS_FOR_SILO,
        {"silo_id": silo_id},
    )
    return [str(row["id"]) for row in rows if row.get("id")]


async def get_marker_details(
    store: HyperGraphStore,
    silo_id: str,
    marker_ids: list[str],
) -> list[dict[str, Any]]:
    """Fetch full marker details from the graph for a list of marker IDs.

    Intended as the second step after :func:`get_markers_for_about_set`
    identifies relevant markers.

    Parameters
    ----------
    store:
        HyperGraphStore used for graph reads.
    silo_id:
        Silo scope.
    marker_ids:
        IDs returned by :func:`get_markers_for_about_set`.

    Returns
    -------
    List of marker dicts (each has ``id``, ``marker_type``, ``status``,
    ``detected_at``, ``about_ids``, and type-specific fields).
    """
    if not marker_ids:
        return []

    rows = await store.execute_query(
        GET_MARKERS_BY_IDS,
        {"silo_id": silo_id, "ids": marker_ids},
    )
    return list(rows)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _index_marker(
    redis: Redis[bytes],
    silo_id: str,
    marker_id: str,
    about_ids: list[str],
    score: float,
) -> None:
    """Add marker_id to the Redis sorted set for each about_id.

    Failures are logged and swallowed — the graph record is authoritative.
    """
    try:
        pipe = redis.pipeline(transaction=False)
        for node_id in about_ids:
            pipe.zadd(_about_key(silo_id, node_id), {marker_id: score})
        await pipe.execute()
    except Exception as exc:
        logger.warning(
            "markers_redis_index_failed",
            marker_id=marker_id,
            silo_id=silo_id,
            about_count=len(about_ids),
            error=str(exc),
        )


async def _deindex_marker(
    redis: Redis[bytes],
    silo_id: str,
    marker_id: str,
    about_ids: list[str],
) -> None:
    """Remove marker_id from the Redis sorted set for each about_id.

    Failures are logged and swallowed.
    """
    try:
        pipe = redis.pipeline(transaction=False)
        for node_id in about_ids:
            pipe.zrem(_about_key(silo_id, node_id), marker_id)
        await pipe.execute()
    except Exception as exc:
        logger.warning(
            "markers_redis_deindex_failed",
            marker_id=marker_id,
            silo_id=silo_id,
            about_count=len(about_ids),
            error=str(exc),
        )


async def _transition_marker(
    store: HyperGraphStore,
    redis: Redis[bytes],
    silo_id: str,
    marker_id: str,
    status: str,
    reason: str,
) -> dict[str, Any]:
    """Shared logic for resolve/dismiss: read about_ids, update graph, deindex."""
    # Fetch about_ids before the status update so we know what to deindex.
    detail_rows = await store.execute_query(
        GET_MARKERS_BY_IDS,
        {"silo_id": silo_id, "ids": [marker_id]},
    )
    about_ids: list[str] = []
    if detail_rows:
        raw = detail_rows[0].get("about_ids") or []
        about_ids = [str(x) for x in raw]

    now = datetime.now(UTC)
    update_rows = await store.execute_write(
        UPDATE_MARKER_STATUS,
        {
            "id": marker_id,
            "silo_id": silo_id,
            "status": status,
            "resolved_at": now.isoformat(),
            "resolution": reason,
        },
    )

    if not update_rows:
        raise RuntimeError(
            f"UPDATE_MARKER_STATUS returned no rows for marker_id={marker_id} silo={silo_id}"
        )

    row = update_rows[0]
    logger.info(
        "marker_status_updated",
        marker_id=marker_id,
        marker_type=row.get("marker_type"),
        status=status,
        silo_id=silo_id,
    )

    if about_ids:
        await _deindex_marker(redis, silo_id, marker_id, about_ids)

    return {
        "marker_id": str(row["marker_id"]),
        "marker_type": row.get("marker_type"),
        "status": status,
        "resolved_at": now.isoformat(),
        "resolution": reason,
    }
