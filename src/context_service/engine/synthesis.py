"""Belief synthesis: derive Wisdom-layer :Belief nodes from fact clusters.

A belief is synthesised from a set of :Fact nodes that share cluster
membership.  The synthesis logic:

1. Fetch facts in the cluster via GET_FACTS_IN_CLUSTER.
2. Enforce the minimum density threshold (MIN_FACTS_FOR_BELIEF = 3).
3. Call the LLM to produce a single synthesised belief statement.
4. Persist the :Belief node and SYNTHESIZED_FROM edges via
   CREATE_BELIEF_FROM_FACTS.

Public API
----------
synthesize_belief(store, cluster_id, silo_id, llm_client) -> str
    Synthesise a belief from a fact cluster.  Returns the new Belief id.
    Raises InsufficientEvidenceError when fewer than MIN_FACTS_FOR_BELIEF
    facts are found.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from context_service.config.settings import get_settings
from context_service.db.queries import (
    CHECK_BELIEF_COVERAGE,
    CREATE_BELIEF_FACT_EDGES,
    CREATE_BELIEF_FROM_FACTS,
    CREATE_MERGED_BELIEF,
    CREATE_MERGED_BELIEF_FACT_EDGES,
    CREATE_MERGED_FROM_EDGES,
    FIND_SIMILAR_BELIEFS,
    GET_FACTS_IN_CLUSTER,
    MARK_BELIEF_STALE,
    UPDATE_BELIEF_CENTROID,
)
from context_service.llm.sanitize import escape_for_prompt

if TYPE_CHECKING:
    from context_service.embeddings.base import EmbeddingService
    from context_service.engine.protocols import HyperGraphStore
    from context_service.llm.base import LLMProvider

logger = structlog.get_logger(__name__)


def _get_min_facts_for_belief() -> int:
    """Get minimum facts threshold, supporting hot-reload."""
    return get_settings().belief_density_threshold


MIN_FACTS_FOR_BELIEF: int = (
    3  # Default for docs/type hints; use _get_min_facts_for_belief() at runtime
)

_SYNTHESIS_SYSTEM_PROMPT = (
    "You are a knowledge synthesis agent. Given a list of verified facts, "
    "produce a single concise belief statement (one or two sentences) that "
    "captures the key insight shared across those facts. Do not speculate "
    "beyond what the facts support. Return only the belief statement — no "
    "preamble, no bullet points, no explanation."
)


class InsufficientEvidenceError(ValueError):
    """Raised when a cluster has fewer than MIN_FACTS_FOR_BELIEF facts."""


def _make_belief_id(cluster_id: str, silo_id: str) -> str:
    """Deterministic belief id derived from cluster + silo."""
    return hashlib.blake2b(f"belief:{silo_id}:{cluster_id}".encode(), digest_size=32).hexdigest()


def _build_synthesis_prompt(facts: list[dict[str, Any]]) -> str:
    """Format facts into a numbered list for the LLM user turn."""
    lines = ["Facts:"]
    for i, f in enumerate(facts, start=1):
        conf = f.get("confidence", 1.0)
        content = escape_for_prompt(f.get("content", ""))
        lines.append(f"  {i}. [{conf:.2f}] {content}")
    return "\n".join(lines)


def _average_confidence(facts: list[dict[str, Any]]) -> float:
    """Return the mean confidence across a list of fact dicts."""
    if not facts:
        return 0.0
    total = sum(float(f.get("confidence", 1.0)) for f in facts)
    return total / len(facts)


def _centroid(embeddings: list[list[float]]) -> list[float]:
    """Compute the element-wise mean of a list of embeddings."""
    if not embeddings:
        return []
    dim = len(embeddings[0])
    total = [0.0] * dim
    for vec in embeddings:
        for i, v in enumerate(vec):
            total[i] += v
    n = len(embeddings)
    return [v / n for v in total]


async def synthesize_belief(
    store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
    llm_client: LLMProvider,
    embedding_client: EmbeddingService | None = None,
) -> str:
    """Synthesise a :Belief node from the facts in a cluster.

    Parameters
    ----------
    store:
        A HyperGraphStore implementation (real or fake).
    cluster_id:
        ID of the :Cluster whose :Fact members to synthesise from.
    silo_id:
        Silo scope.
    llm_client:
        LLM provider used to generate the belief statement.

    Returns
    -------
    str
        The id of the newly created :Belief node.

    Raises
    ------
    InsufficientEvidenceError
        If fewer than MIN_FACTS_FOR_BELIEF facts exist in the cluster.
    """
    fact_rows = await store.execute_query(
        GET_FACTS_IN_CLUSTER,
        {"cluster_id": cluster_id, "silo_id": silo_id},
    )

    min_facts = _get_min_facts_for_belief()
    if len(fact_rows) < min_facts:
        raise InsufficientEvidenceError(
            f"Cluster {cluster_id!r} has {len(fact_rows)} fact(s); minimum required is {min_facts}."
        )

    fact_ids = [row["fact_id"] for row in fact_rows]
    confidence = _average_confidence(fact_rows)
    prompt = _build_synthesis_prompt(fact_rows)

    belief_text, _usage = await llm_client.complete(
        messages=[
            {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    belief_text = belief_text.strip()

    now = datetime.now(UTC)
    belief_id = _make_belief_id(cluster_id, silo_id)

    await store.execute_write(
        CREATE_BELIEF_FROM_FACTS,
        {
            "belief_id": belief_id,
            "silo_id": silo_id,
            "content": belief_text,
            "confidence": confidence,
            "evidence_count": len(fact_ids),
            "created_at": now.isoformat(),
            "valid_from": now.isoformat(),
        },
    )

    edges_created = 0
    if fact_ids:
        rows = await store.execute_write(
            CREATE_BELIEF_FACT_EDGES,
            {"belief_id": belief_id, "silo_id": silo_id, "fact_ids": fact_ids},
        )
        edges_created = rows[0].get("edges_created", 0) if rows else 0

    if embedding_client is not None:
        contents = [row.get("content", "") for row in fact_rows if row.get("content")]
        embeddings = await embedding_client.embed(contents)
        centroid = _centroid(embeddings)
        await store.execute_write(
            UPDATE_BELIEF_CENTROID,
            {
                "belief_id": belief_id,
                "silo_id": silo_id,
                "centroid_embedding": centroid,
                "last_revision_check": now.isoformat(),
                "revision_count": 0,
            },
        )

    logger.info(
        "belief_synthesised",
        belief_id=belief_id,
        cluster_id=cluster_id,
        silo_id=silo_id,
        evidence_count=len(fact_ids),
        edges_created=edges_created,
        confidence=confidence,
    )
    return belief_id


def _make_merged_belief_id(source_ids: list[str], silo_id: str) -> str:
    """Deterministic id for a merged belief derived from a sorted set of source belief ids."""
    key = "merged:" + silo_id + ":" + ":".join(sorted(source_ids))
    return hashlib.blake2b(key.encode(), digest_size=32).hexdigest()


async def detect_overlapping_beliefs(
    store: HyperGraphStore,
    silo_id: str,
    subject: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return active :Belief nodes whose content contains *subject*.

    Parameters
    ----------
    store:
        A HyperGraphStore implementation.
    silo_id:
        Silo scope.
    subject:
        Subject string for case-insensitive substring match.
    limit:
        Maximum candidates to return (default 20).

    Returns
    -------
    list[dict]
        Each entry: ``{"belief_id", "content", "confidence", "fact_ids"}``.
        Empty list when fewer than two matching beliefs exist (no overlap to merge).
    """
    now = datetime.now(UTC)
    rows = await store.execute_query(
        FIND_SIMILAR_BELIEFS,
        {"silo_id": silo_id, "subject": subject, "as_of": now.isoformat(), "limit": limit},
    )
    # Only report overlap when there are at least two candidates.
    if len(rows) < 2:
        return []
    return list(rows)


async def merge_beliefs(
    store: HyperGraphStore,
    silo_id: str,
    source_beliefs: list[dict[str, Any]],
    llm_client: LLMProvider,
) -> str:
    """Merge overlapping beliefs into a single :Belief with MERGED_FROM edges.

    Strategy:
    - Union the fact sets from all source beliefs.
    - Reconcile confidence as the weighted mean (weight = evidence_count).
    - Call the LLM to synthesise a fresh belief statement from the unioned facts.
    - Create the merged :Belief node and MERGED_FROM edges.
    - Mark each source belief stale.

    Parameters
    ----------
    store:
        A HyperGraphStore implementation.
    silo_id:
        Silo scope.
    source_beliefs:
        List of candidate dicts as returned by ``detect_overlapping_beliefs``.
        Each must carry ``belief_id``, ``confidence``, and ``fact_ids``.
    llm_client:
        LLM provider for re-synthesis of the merged statement.

    Returns
    -------
    str
        The id of the new merged :Belief node.

    Raises
    ------
    ValueError
        If fewer than two source beliefs are provided.
    """
    if len(source_beliefs) < 2:
        raise ValueError(
            f"merge_beliefs requires at least 2 source beliefs; got {len(source_beliefs)}."
        )

    # Union fact ids across all source beliefs (dedup).
    seen_fact_ids: set[str] = set()
    for sb in source_beliefs:
        seen_fact_ids.update(sb.get("fact_ids") or [])
    fact_ids = sorted(seen_fact_ids)

    # Weighted mean confidence: weight by number of fact ids per source.
    total_weight = 0.0
    weighted_conf = 0.0
    for sb in source_beliefs:
        w = float(len(sb.get("fact_ids") or []) or 1)
        weighted_conf += float(sb.get("confidence", 1.0)) * w
        total_weight += w
    confidence = weighted_conf / total_weight if total_weight else 0.0

    # Build synthesis input from unique belief texts across all source beliefs.
    # Each source belief contributes its own content (not duplicated per fact_id).
    seen_belief_ids: set[str] = set()
    unique_fact_rows: list[dict[str, Any]] = []
    for sb in source_beliefs:
        bid = sb.get("belief_id", "")
        if bid not in seen_belief_ids:
            seen_belief_ids.add(bid)
            unique_fact_rows.append(
                {
                    "fact_id": bid,
                    "content": sb.get("content", ""),
                    "confidence": sb.get("confidence", 1.0),
                }
            )

    prompt = _build_synthesis_prompt(unique_fact_rows)
    belief_text, _usage = await llm_client.complete(
        messages=[
            {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    belief_text = belief_text.strip()

    now = datetime.now(UTC)
    source_ids = [sb["belief_id"] for sb in source_beliefs]
    merged_id = _make_merged_belief_id(source_ids, silo_id)

    await store.execute_write(
        CREATE_MERGED_BELIEF,
        {
            "belief_id": merged_id,
            "silo_id": silo_id,
            "content": belief_text,
            "confidence": confidence,
            "evidence_count": len(fact_ids),
            "created_at": now.isoformat(),
            "valid_from": now.isoformat(),
        },
    )

    if fact_ids:
        await store.execute_write(
            CREATE_MERGED_BELIEF_FACT_EDGES,
            {
                "belief_id": merged_id,
                "silo_id": silo_id,
                "fact_ids": fact_ids,
            },
        )

    await store.execute_write(
        CREATE_MERGED_FROM_EDGES,
        {
            "merged_belief_id": merged_id,
            "silo_id": silo_id,
            "source_belief_ids": source_ids,
            "created_at": now.isoformat(),
        },
    )

    # Mark source beliefs stale.
    for sb in source_beliefs:
        await store.execute_write(
            MARK_BELIEF_STALE,
            {
                "belief_id": sb["belief_id"],
                "silo_id": silo_id,
                "valid_to": now.isoformat(),
            },
        )

    logger.info(
        "beliefs_merged",
        merged_belief_id=merged_id,
        silo_id=silo_id,
        source_count=len(source_ids),
        evidence_count=len(fact_ids),
        confidence=confidence,
    )
    return merged_id


async def check_belief_coverage(
    store: HyperGraphStore,
    silo_id: str,
    subject: str,
) -> dict[str, Any] | None:
    """Return an existing active belief that covers *subject*, or None.

    Parameters
    ----------
    store:
        A HyperGraphStore implementation.
    silo_id:
        Silo scope.
    subject:
        Subject string to search for (case-insensitive substring match).

    Returns
    -------
    dict or None
        ``{"belief_id": ..., "content": ..., "confidence": ...}`` if found,
        else ``None``.
    """
    now = datetime.now(UTC)
    rows = await store.execute_query(
        CHECK_BELIEF_COVERAGE,
        {"silo_id": silo_id, "subject": subject, "as_of": now.isoformat()},
    )
    return rows[0] if rows else None
