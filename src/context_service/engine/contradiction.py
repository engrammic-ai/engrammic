"""Inline contradiction candidate flagging.

This module provides fast embedding similarity checks during writes to flag
potential contradictions for batch validator confirmation.

The flow:
1. Write new Claim/Belief node with embedding
2. check_contradiction_candidates() uses Qdrant to find similar existing nodes
3. flag_contradiction_candidate() sets flags on the new node in Memgraph
4. sage.validator batch job confirms via LLM and writes Contradiction markers
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from context_service.config.settings import get_settings

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


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
    qdrant_client: Any | None = None,
    threshold: float | None = None,
    max_candidates: int = 20,
) -> list[str]:
    """Find existing nodes with embeddings similar enough to be contradiction candidates.

    Uses Qdrant vector search to find similar nodes efficiently, then filters
    to exclude the current node.

    Args:
        store: Graph store connection (unused but kept for API compat)
        silo_id: Silo to search within
        node_id: ID of the new node (excluded from results)
        embedding: Embedding vector of the new node
        qdrant_client: Qdrant client for vector search
        threshold: Cosine similarity threshold (default from config)
        max_candidates: Maximum candidates to return

    Returns:
        List of node IDs that are candidates for contradiction (similarity >= threshold)
    """
    _ = store  # Unused; kept for API compatibility

    if threshold is None:
        threshold = get_settings().contradiction_candidate_threshold

    if not embedding or qdrant_client is None:
        return []

    collection_name = f"ctx_{silo_id}"

    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        # Search for similar vectors, fetch extra to allow for filtering
        search_result = await qdrant_client.search(
            collection_name=collection_name,
            query_vector=embedding,
            limit=max_candidates + 5,  # Extra buffer for self-exclusion
            score_threshold=threshold,
            query_filter=Filter(
                must_not=[
                    FieldCondition(key="node_id", match=MatchValue(value=node_id)),
                ]
            ),
        )

        candidates: list[str] = []
        for hit in search_result:
            candidate_id = hit.payload.get("node_id") if hit.payload else None
            if candidate_id and candidate_id != node_id:
                candidates.append(candidate_id)
                logger.debug(
                    "contradiction_candidate_found",
                    node_id=node_id,
                    candidate_id=candidate_id,
                    similarity=round(hit.score, 3),
                )
                if len(candidates) >= max_candidates:
                    break

        return candidates

    except Exception as exc:
        logger.warning(
            "contradiction_check_failed",
            error=str(exc),
            silo_id=silo_id,
            node_id=node_id,
        )
        return []


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
    qdrant_client: Any | None = None,
) -> list[str]:
    """Convenience function: check and flag in one call.

    Args:
        store: Graph store for flagging
        silo_id: Silo to search within
        node_id: New node ID
        embedding: Embedding vector for similarity search
        qdrant_client: Qdrant client for vector search

    Returns:
        List of candidate IDs if flagged, empty list otherwise.
    """
    settings = get_settings()
    if not settings.contradiction_flagging_enabled:
        return []

    candidates = await check_contradiction_candidates(
        store=store,
        silo_id=silo_id,
        node_id=node_id,
        embedding=embedding,
        qdrant_client=qdrant_client,
    )

    if candidates:
        await flag_contradiction_candidate(
            store=store,
            silo_id=silo_id,
            node_id=node_id,
            candidate_ids=candidates,
        )

    return candidates
