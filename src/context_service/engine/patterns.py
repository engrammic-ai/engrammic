"""Pattern detection: derive Wisdom-layer :Pattern nodes from recurring fact shapes.

A pattern is a recurring structural shape observed across :Fact, :Belief, or
:Event nodes.  The three supported pattern types are:

- ``temporal_correlation`` -- facts that occur within a configurable time window
- ``co_occurrence``         -- facts that share a Leiden cluster (same community)
- ``causal_chain``          -- A->B->C paths of 3+ hops via :CAUSES edges

Public API
----------
detect_patterns(store, silo_id, pattern_type, *, window_seconds, limit)
    Run detection for a given pattern type and return a list of candidate dicts.

create_or_update_pattern(store, pattern_type, description, observed_node_ids, silo_id,
                         *, confidence)
    Persist a :Pattern node (MERGE) and attach OBSERVED_IN edges.  If a
    matching pattern already exists the frequency counter is incremented and
    the new observed_node_ids are linked.  Returns the pattern id.

decay_patterns(store, silo_id, *, decay_factor, stale_before_iso, min_confidence)
    Apply exponential decay to stale :Pattern nodes and tombstone any that fall
    below min_confidence.  Returns (patterns_decayed, patterns_tombstoned).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog

from context_service.db.queries import (
    CREATE_PATTERN,
    DECAY_STALE_PATTERNS,
    DETECT_CAUSAL_CHAINS,
    DETECT_CO_OCCURRING_FACTS,
    DETECT_TEMPORAL_CORRELATIONS,
    GET_PATTERN_BY_TYPE_AND_SUBJECT,
    TOMBSTONE_LOW_CONFIDENCE_PATTERNS,
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

# Minimum chain length (hops) required for a causal_chain pattern.
# A 2-hop path is just one direct edge; below 3 there is no real chain.
CAUSAL_CHAIN_MIN_HOPS: int = 2  # means A->B->C (3 nodes, 2 edges)
CAUSAL_CHAIN_MAX_HOPS: int = 6

# Decay factor applied per scheduled period (exponential: confidence *= 0.9).
DEFAULT_DECAY_FACTOR: float = 0.9

# Patterns below this threshold after decay are tombstoned.
DEFAULT_MIN_CONFIDENCE: float = 0.1


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

    if pattern_type == "co_occurrence":
        rows = await store.execute_query(
            DETECT_CO_OCCURRING_FACTS,
            {
                "silo_id": silo_id,
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

    if pattern_type == "causal_chain":
        query = DETECT_CAUSAL_CHAINS.format(
            min_hops=CAUSAL_CHAIN_MIN_HOPS,
            max_hops=CAUSAL_CHAIN_MAX_HOPS,
        )
        rows = await store.execute_query(
            query,
            {
                "silo_id": silo_id,
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

    logger.warning(
        "pattern_detection_unknown_type",
        pattern_type=pattern_type,
        silo_id=silo_id,
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


def _description_for_co_occurrence(row: dict[str, Any]) -> str:
    """Build a stable description string for a co_occurrence pattern row."""
    a = str(row.get("content_a", row.get("fact_id_a", "?")))[:80]
    b = str(row.get("content_b", row.get("fact_id_b", "?")))[:80]
    cluster_id = str(row.get("cluster_id", "unknown"))
    # Sort so the description is symmetric (same pair regardless of row order).
    pair = sorted([a, b])
    return f"co_occurrence:{cluster_id}:{pair[0]}|{pair[1]}"


def _description_for_causal_chain(row: dict[str, Any]) -> str:
    """Build a stable description string for a causal_chain pattern row."""
    start = str(row.get("chain_start", "?"))
    end = str(row.get("chain_end", "?"))
    length = int(row.get("chain_length", 0))
    return f"causal_chain:len{length}:{start}->{end}"


async def process_co_occurrence_candidates(
    store: HyperGraphStore,
    silo_id: str,
    candidates: list[dict[str, Any]],
) -> int:
    """Materialise :Pattern nodes from co_occurrence candidate rows.

    Parameters
    ----------
    store:
        A HyperGraphStore implementation.
    silo_id:
        Silo scope.
    candidates:
        Rows returned by :func:`detect_patterns` for ``"co_occurrence"``.

    Returns
    -------
    int
        Number of patterns created or updated.
    """
    count = 0
    for row in candidates:
        description = _description_for_co_occurrence(row)
        node_ids = [
            str(row["fact_id_a"]),
            str(row["fact_id_b"]),
        ]
        await create_or_update_pattern(
            store,
            "co_occurrence",
            description,
            node_ids,
            silo_id,
        )
        count += 1
    return count


async def process_causal_chain_candidates(
    store: HyperGraphStore,
    silo_id: str,
    candidates: list[dict[str, Any]],
) -> int:
    """Materialise :Pattern nodes from causal_chain candidate rows.

    Only chains with at least 3 nodes (2+ hops) are materialised.

    Parameters
    ----------
    store:
        A HyperGraphStore implementation.
    silo_id:
        Silo scope.
    candidates:
        Rows returned by :func:`detect_patterns` for ``"causal_chain"``.

    Returns
    -------
    int
        Number of patterns created or updated.
    """
    count = 0
    for row in candidates:
        chain_length = int(row.get("chain_length", 0))
        # chain_length is the number of edges; we need at least 2 edges (3 nodes).
        if chain_length < 2:
            continue
        description = _description_for_causal_chain(row)
        chain_node_ids: list[str] = [str(n) for n in row.get("chain_node_ids", [])]
        if not chain_node_ids:
            chain_node_ids = [str(row["chain_start"]), str(row["chain_end"])]
        await create_or_update_pattern(
            store,
            "causal_chain",
            description,
            chain_node_ids,
            silo_id,
        )
        count += 1
    return count


async def decay_patterns(
    store: HyperGraphStore,
    silo_id: str,
    *,
    decay_factor: float = DEFAULT_DECAY_FACTOR,
    stale_before_iso: str,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> tuple[int, int]:
    """Apply exponential confidence decay to stale :Pattern nodes.

    Patterns not re-observed since *stale_before_iso* have their ``confidence``
    multiplied by *decay_factor*.  Patterns whose confidence drops below
    *min_confidence* are tombstoned.

    Parameters
    ----------
    store:
        A HyperGraphStore implementation.
    silo_id:
        Silo scope.
    decay_factor:
        Multiplier applied to each stale pattern's confidence (default 0.9).
    stale_before_iso:
        ISO-8601 datetime string; patterns last observed before this are
        considered stale.
    min_confidence:
        Patterns with confidence below this value after decay are tombstoned.

    Returns
    -------
    tuple[int, int]
        ``(patterns_decayed, patterns_tombstoned)``
    """
    now = datetime.now(UTC).isoformat()

    decay_rows = await store.execute_write(
        DECAY_STALE_PATTERNS,
        {
            "silo_id": silo_id,
            "stale_before": stale_before_iso,
            "decay_factor": decay_factor,
            "now": now,
        },
    )
    patterns_decayed = int(decay_rows[0].get("patterns_decayed", 0)) if decay_rows else 0

    tombstone_rows = await store.execute_write(
        TOMBSTONE_LOW_CONFIDENCE_PATTERNS,
        {
            "silo_id": silo_id,
            "min_confidence": min_confidence,
            "now": now,
        },
    )
    patterns_tombstoned = (
        int(tombstone_rows[0].get("patterns_tombstoned", 0)) if tombstone_rows else 0
    )

    logger.info(
        "pattern_decay_run",
        silo_id=silo_id,
        patterns_decayed=patterns_decayed,
        patterns_tombstoned=patterns_tombstoned,
        decay_factor=decay_factor,
        stale_before=stale_before_iso,
    )
    return patterns_decayed, patterns_tombstoned
