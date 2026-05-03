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
    CREATE_BELIEF_FROM_FACTS,
    GET_FACTS_IN_CLUSTER,
    UPDATE_BELIEF_CENTROID,
)

if TYPE_CHECKING:
    from context_service.embeddings.base import EmbeddingService
    from context_service.engine.protocols import HyperGraphStore
    from context_service.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

# Minimum number of facts required to synthesise a belief.
# Reads from settings so it can be tuned via BELIEF_DENSITY_THRESHOLD env var.
MIN_FACTS_FOR_BELIEF: int = get_settings().belief_density_threshold

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
        lines.append(f"  {i}. [{conf:.2f}] {f.get('content', '')}")
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

    if len(fact_rows) < MIN_FACTS_FOR_BELIEF:
        raise InsufficientEvidenceError(
            f"Cluster {cluster_id!r} has {len(fact_rows)} fact(s); "
            f"minimum required is {MIN_FACTS_FOR_BELIEF}."
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

    rows = await store.execute_write(
        CREATE_BELIEF_FROM_FACTS,
        {
            "belief_id": belief_id,
            "silo_id": silo_id,
            "content": belief_text,
            "confidence": confidence,
            "evidence_count": len(fact_ids),
            "created_at": now.isoformat(),
            "valid_from": now.isoformat(),
            "fact_ids": fact_ids,
        },
    )

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

    edges_created = rows[0].get("edges_created", 0) if rows else 0
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
