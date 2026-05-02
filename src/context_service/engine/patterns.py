"""Pattern detection: derive Wisdom-layer :Pattern nodes from recurring fact shapes.

A pattern is a recurring structural shape observed across :Fact, :Belief, or
:Event nodes.  The three supported pattern types are:

- ``temporal_correlation`` -- facts that occur within a configurable time window
- ``co_occurrence``         -- facts that share entity mentions (not yet implemented)
- ``causal_chain``          -- facts linked by :CAUSES edges (not yet implemented)

Public API
----------
detect_patterns(store, silo_id, pattern_type, *, window_seconds, limit)
    Run detection for a given pattern type and return a list of candidate dicts.

create_or_update_pattern(store, pattern_type, description, observed_node_ids, silo_id,
                         *, confidence)
    Persist a :Pattern node (MERGE) and attach OBSERVED_IN edges.  If a
    matching pattern already exists the frequency counter is incremented and
    the new observed_node_ids are linked.  Returns the pattern id.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog

from context_service.db.queries import (
    CREATE_PATTERN,
    DETECT_TEMPORAL_CORRELATIONS,
    GET_PATTERN_BY_TYPE_AND_SUBJECT,
    UPDATE_PATTERN_FREQUENCY,
)

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

PatternType = Literal["temporal_correlation", "co_occurrence", "causal_chain"]

# Default time window used by temporal correlation detection (seconds).
DEFAULT_TEMPORAL_WINDOW_SECONDS: int = 3600

# Default cap on the number of candidate pairs returned per detection run.
DEFAULT_DETECTION_LIMIT: int = 50


def _make_pattern_id(pattern_type: str, description: str, silo_id: str) -> str:
    """Deterministic pattern id derived from type, description, and silo."""
    key = f"pattern:{silo_id}:{pattern_type}:{description}"
    return hashlib.blake2b(key.encode(), digest_size=32).hexdigest()


async def detect_patterns(
    store: HyperGraphStore,
    silo_id: str,
    pattern_type: PatternType,
    *,
    window_seconds: int = DEFAULT_TEMPORAL_WINDOW_SECONDS,
    limit: int = DEFAULT_DETECTION_LIMIT,
) -> list[dict[str, Any]]:
    """Run detection for *pattern_type* and return raw candidate rows.

    Parameters
    ----------
    store:
        A HyperGraphStore implementation (real or fake).
    silo_id:
        Silo scope.
    pattern_type:
        One of ``"temporal_correlation"``, ``"co_occurrence"``,
        ``"causal_chain"``.
    window_seconds:
        For ``temporal_correlation``: the maximum gap (in seconds) between
        two :Fact ``valid_from`` timestamps for them to qualify as correlated.
    limit:
        Maximum number of candidate rows to return.

    Returns
    -------
    list[dict]
        Raw rows from the detection query.  Each row schema depends on
        *pattern_type*; callers should pass results to
        :func:`create_or_update_pattern`.
    """
    if pattern_type == "temporal_correlation":
        rows = await store.execute_query(
            DETECT_TEMPORAL_CORRELATIONS,
            {
                "silo_id": silo_id,
                "window_seconds": window_seconds,
                "limit": limit,
            },
        )
        logger.debug(
            "pattern_detection_run",
            pattern_type=pattern_type,
            silo_id=silo_id,
            candidates=len(rows),
        )
        return rows

    # co_occurrence and causal_chain are placeholders for future detection
    # passes; return empty lists so callers can wire them without errors.
    logger.debug(
        "pattern_detection_noop",
        pattern_type=pattern_type,
        silo_id=silo_id,
        reason="not_yet_implemented",
    )
    return []


async def create_or_update_pattern(
    store: HyperGraphStore,
    pattern_type: PatternType,
    description: str,
    observed_node_ids: list[str],
    silo_id: str,
    *,
    confidence: float = 1.0,
) -> str:
    """Persist a :Pattern node and link it to *observed_node_ids*.

    If a :Pattern with the same deterministic id already exists its
    ``frequency`` is incremented and ``last_observed`` is updated.  OBSERVED_IN
    edges to any new *observed_node_ids* are merged in the same write.

    Parameters
    ----------
    store:
        A HyperGraphStore implementation.
    pattern_type:
        One of ``"temporal_correlation"``, ``"co_occurrence"``,
        ``"causal_chain"``.
    description:
        Human-readable description of the pattern.
    observed_node_ids:
        List of node ids (Fact / Belief / Event) that exhibit the pattern.
    silo_id:
        Silo scope.
    confidence:
        Confidence score [0, 1] for this pattern occurrence.

    Returns
    -------
    str
        The id of the created or updated :Pattern node.
    """
    pattern_id = _make_pattern_id(pattern_type, description, silo_id)
    now = datetime.now(UTC)

    # Check whether a matching pattern already exists.
    existing = await store.execute_query(
        GET_PATTERN_BY_TYPE_AND_SUBJECT,
        {
            "silo_id": silo_id,
            "pattern_type": pattern_type,
            "subject": description,
            "as_of": now.isoformat(),
        },
    )

    if existing:
        # Increment frequency and update last_observed timestamp.
        await store.execute_write(
            UPDATE_PATTERN_FREQUENCY,
            {
                "pattern_id": pattern_id,
                "silo_id": silo_id,
                "last_observed": now.isoformat(),
            },
        )
        logger.info(
            "pattern_updated",
            pattern_id=pattern_id,
            pattern_type=pattern_type,
            silo_id=silo_id,
        )
    else:
        rows = await store.execute_write(
            CREATE_PATTERN,
            {
                "pattern_id": pattern_id,
                "silo_id": silo_id,
                "pattern_type": pattern_type,
                "description": description,
                "frequency": 1,
                "confidence": confidence,
                "first_observed": now.isoformat(),
                "last_observed": now.isoformat(),
                "created_at": now.isoformat(),
                "observed_node_ids": observed_node_ids,
            },
        )
        edges_created = rows[0].get("edges_created", 0) if rows else 0
        logger.info(
            "pattern_created",
            pattern_id=pattern_id,
            pattern_type=pattern_type,
            silo_id=silo_id,
            observed_nodes=len(observed_node_ids),
            edges_created=edges_created,
        )

    return pattern_id
