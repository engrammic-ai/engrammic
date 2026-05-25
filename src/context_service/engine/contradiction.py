"""Inline contradiction candidate flagging.

This module provides fast embedding similarity checks during writes to flag
potential contradictions for batch validator confirmation.

The flow:
1. Write new Claim/Belief node with embedding
2. check_contradiction_candidates() finds similar existing nodes
3. flag_contradiction_candidate() sets flags on the new node
4. sage.validator batch job confirms via LLM and writes Contradiction markers
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from context_service.config.settings import get_settings

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity for two equal-length vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# Query to get recent claims/beliefs with embeddings for similarity check
_GET_RECENT_EMBEDDED_NODES = """
MATCH (n {silo_id: $silo_id})
WHERE (n:Claim OR n:Belief OR n:Fact)
  AND n.id <> $exclude_id
  AND n.embedding IS NOT NULL
  AND n.created_at > $cutoff
RETURN n.id AS id, n.content AS content, n.embedding AS embedding
LIMIT $limit
"""

# Query to set contradiction candidate flags
_FLAG_CONTRADICTION_CANDIDATE = """
MATCH (n {id: $node_id, silo_id: $silo_id})
SET n.contradiction_candidate = true,
    n.contradiction_candidate_with = $candidate_ids,
    n.contradiction_candidate_at = $flagged_at
RETURN n.id AS id
"""

# Query to clear contradiction candidate flags
_CLEAR_CONTRADICTION_FLAGS = """
MATCH (n {id: $node_id, silo_id: $silo_id})
REMOVE n.contradiction_candidate, n.contradiction_candidate_with, n.contradiction_candidate_at
RETURN n.id AS id
"""


async def check_contradiction_candidates(
    store: HyperGraphStore,
    silo_id: str,
    node_id: str,
    embedding: list[float],
    threshold: float | None = None,
    lookback_days: int = 30,
    max_candidates: int = 100,
) -> list[str]:
    """Find existing nodes with embeddings similar enough to be contradiction candidates.

    Args:
        store: Graph store connection
        silo_id: Silo to search within
        node_id: ID of the new node (excluded from results)
        embedding: Embedding vector of the new node
        threshold: Cosine similarity threshold (default from config)
        lookback_days: Only check nodes created within this window
        max_candidates: Maximum nodes to check

    Returns:
        List of node IDs that are candidates for contradiction (similarity >= threshold)
    """
    if threshold is None:
        threshold = get_settings().contradiction_candidate_threshold

    if not embedding:
        return []

    cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = (
        cutoff.replace(day=cutoff.day - lookback_days)
        if cutoff.day > lookback_days
        else cutoff.replace(month=cutoff.month - 1, day=1)
    )
    cutoff_str = cutoff.isoformat()

    try:
        result = await store.execute_query(
            _GET_RECENT_EMBEDDED_NODES,
            {
                "silo_id": silo_id,
                "exclude_id": node_id,
                "cutoff": cutoff_str,
                "limit": max_candidates,
            },
        )
    except Exception as exc:
        logger.warning("contradiction_check_failed", error=str(exc), silo_id=silo_id)
        return []

    candidates: list[str] = []
    for row in result:
        stored_embedding = row.get("embedding")
        if not stored_embedding:
            continue
        similarity = _cosine_similarity(embedding, stored_embedding)
        if similarity >= threshold:
            candidates.append(row["id"])
            logger.debug(
                "contradiction_candidate_found",
                node_id=node_id,
                candidate_id=row["id"],
                similarity=round(similarity, 3),
            )

    return candidates


async def flag_contradiction_candidate(
    store: HyperGraphStore,
    silo_id: str,
    node_id: str,
    candidate_ids: list[str],
) -> bool:
    """Set contradiction candidate flags on a node.

    Args:
        store: Graph store connection
        silo_id: Silo the node belongs to
        node_id: Node to flag
        candidate_ids: IDs of nodes that might contradict this one

    Returns:
        True if flagging succeeded, False otherwise
    """
    if not candidate_ids:
        return False

    flagged_at = datetime.now(UTC).isoformat()

    try:
        result = await store.execute_write(
            _FLAG_CONTRADICTION_CANDIDATE,
            {
                "silo_id": silo_id,
                "node_id": node_id,
                "candidate_ids": candidate_ids,
                "flagged_at": flagged_at,
            },
        )
        flagged = bool(result)
        if flagged:
            logger.info(
                "contradiction_candidate_flagged",
                node_id=node_id,
                candidate_count=len(candidate_ids),
            )
        return flagged
    except Exception as exc:
        logger.warning("contradiction_flagging_failed", error=str(exc), node_id=node_id)
        return False


async def clear_contradiction_flags(
    store: HyperGraphStore,
    silo_id: str,
    node_id: str,
) -> bool:
    """Clear contradiction candidate flags from a node.

    Called by validator after processing, regardless of outcome.
    """
    try:
        result = await store.execute_write(
            _CLEAR_CONTRADICTION_FLAGS,
            {
                "silo_id": silo_id,
                "node_id": node_id,
            },
        )
        return bool(result)
    except Exception as exc:
        logger.warning("clear_flags_failed", error=str(exc), node_id=node_id)
        return False


async def maybe_flag_contradiction(
    store: HyperGraphStore,
    silo_id: str,
    node_id: str,
    embedding: list[float],
) -> list[str]:
    """Convenience function: check and flag in one call.

    Returns list of candidate IDs if flagged, empty list otherwise.
    """
    settings = get_settings()
    if not settings.contradiction_flagging_enabled:
        return []

    candidates = await check_contradiction_candidates(
        store=store,
        silo_id=silo_id,
        node_id=node_id,
        embedding=embedding,
    )

    if candidates:
        await flag_contradiction_candidate(
            store=store,
            silo_id=silo_id,
            node_id=node_id,
            candidate_ids=candidates,
        )

    return candidates
