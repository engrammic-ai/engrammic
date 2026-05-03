"""Belief revision: detect semantic drift and supersede stale beliefs.

When new facts join a belief's source cluster the centroid of that cluster
may shift.  If the cosine distance between the stored centroid and the new
centroid exceeds REVISION_THRESHOLD (15 %), a revised belief is synthesised
and a :SUPERSEDES edge links the new belief to the old one.

Public API
----------
check_belief_revision(store, belief_id, silo_id, embedding_client)
    -> RevisionCheckResult
    Compute the current cluster centroid and compare it to the stored one.
    Returns a dataclass that reports whether revision is needed and why.

revise_belief(store, old_belief_id, silo_id, llm_client, embedding_client)
    -> str
    Synthesise a replacement :Belief, wire the SUPERSEDES edge, mark the old
    belief stale, and update the centroid on the new belief.  Returns the new
    belief id.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from context_service.config.settings import get_settings
from context_service.db.queries import (
    CREATE_BELIEF_FROM_FACTS,
    CREATE_BELIEF_SUPERSEDES,
    GET_FACTS_IN_CLUSTER,
    MARK_BELIEF_STALE,
    UPDATE_BELIEF_CENTROID,
)
from context_service.engine.auto_reflection import (
    create_auto_reflection,
    make_revision_content,
)
from context_service.engine.synthesis import (
    _SYNTHESIS_SYSTEM_PROMPT,
    InsufficientEvidenceError,
    _average_confidence,
    _build_synthesis_prompt,
    _get_min_facts_for_belief,
)

if TYPE_CHECKING:
    from context_service.embeddings.base import EmbeddingService
    from context_service.engine.protocols import HyperGraphStore
    from context_service.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

def _get_revision_threshold() -> float:
    """Get revision threshold, supporting hot-reload."""
    return get_settings().revision_cosine_threshold


REVISION_THRESHOLD: float = 0.15  # Default for docs; use _get_revision_threshold() at runtime

_GET_BELIEF_FOR_REVISION = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
RETURN
    b.id AS belief_id,
    b.content AS content,
    b.confidence AS confidence,
    b.centroid_embedding AS centroid_embedding,
    b.revision_count AS revision_count,
    b.wisdom_status AS wisdom_status
"""

_GET_BELIEF_CLUSTER = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})-[:SYNTHESIZED_FROM]->(f:Fact)
      -[:MEMBER_OF]->(c:Cluster {silo_id: $silo_id})
RETURN DISTINCT c.id AS cluster_id
LIMIT 1
"""

_GET_FACT_CONTENTS_IN_CLUSTER = """
MATCH (f:Fact)-[:MEMBER_OF]->(c:Cluster {id: $cluster_id, silo_id: $silo_id})
RETURN f.id AS fact_id, f.content AS content,
       coalesce(f.confidence, 1.0) AS confidence,
       f.valid_from AS valid_from
ORDER BY coalesce(f.confidence, 1.0) DESC
"""


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Return 1 - cosine_similarity for two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)


def _centroid(embeddings: list[list[float]]) -> list[float]:
    """Return the element-wise mean of a list of equal-length vectors."""
    if not embeddings:
        return []
    dim = len(embeddings[0])
    total = [0.0] * dim
    for vec in embeddings:
        for i, v in enumerate(vec):
            total[i] += v
    n = len(embeddings)
    return [v / n for v in total]


def _make_revised_belief_id(old_belief_id: str, revision_count: int) -> str:
    """Deterministic id for the revised belief derived from its predecessor."""
    return hashlib.blake2b(
        f"revision:{old_belief_id}:{revision_count}".encode(), digest_size=32
    ).hexdigest()


@dataclass(frozen=True)
class RevisionCheckResult:
    """Outcome of check_belief_revision."""

    belief_id: str
    needs_revision: bool
    cosine_distance: float
    cluster_id: str | None
    reason: str


async def check_belief_revision(
    store: HyperGraphStore,
    belief_id: str,
    silo_id: str,
    embedding_client: EmbeddingService,
) -> RevisionCheckResult:
    """Check whether a belief's cluster centroid has drifted beyond the threshold.

    Parameters
    ----------
    store:
        HyperGraphStore implementation.
    belief_id:
        ID of the :Belief to inspect.
    silo_id:
        Silo scope.
    embedding_client:
        Used to embed current fact contents so we can compute the new centroid.

    Returns
    -------
    RevisionCheckResult
        ``needs_revision=True`` when cosine distance > REVISION_THRESHOLD.
        ``needs_revision=False`` when the centroid has not shifted, the belief
        has no stored centroid, or insufficient facts exist.
    """
    belief_rows = await store.execute_query(
        _GET_BELIEF_FOR_REVISION,
        {"belief_id": belief_id, "silo_id": silo_id},
    )
    if not belief_rows:
        return RevisionCheckResult(
            belief_id=belief_id,
            needs_revision=False,
            cosine_distance=0.0,
            cluster_id=None,
            reason="belief_not_found",
        )

    belief = belief_rows[0]

    if belief.get("wisdom_status") == "stale":
        return RevisionCheckResult(
            belief_id=belief_id,
            needs_revision=False,
            cosine_distance=0.0,
            cluster_id=None,
            reason="already_stale",
        )

    stored_centroid: list[float] | None = belief.get("centroid_embedding")
    if not stored_centroid:
        return RevisionCheckResult(
            belief_id=belief_id,
            needs_revision=False,
            cosine_distance=0.0,
            cluster_id=None,
            reason="no_centroid_stored",
        )

    cluster_rows = await store.execute_query(
        _GET_BELIEF_CLUSTER,
        {"belief_id": belief_id, "silo_id": silo_id},
    )
    if not cluster_rows:
        return RevisionCheckResult(
            belief_id=belief_id,
            needs_revision=False,
            cosine_distance=0.0,
            cluster_id=None,
            reason="cluster_not_found",
        )

    cluster_id: str = cluster_rows[0]["cluster_id"]

    fact_rows = await store.execute_query(
        _GET_FACT_CONTENTS_IN_CLUSTER,
        {"cluster_id": cluster_id, "silo_id": silo_id},
    )
    min_facts = _get_min_facts_for_belief()
    if len(fact_rows) < min_facts:
        return RevisionCheckResult(
            belief_id=belief_id,
            needs_revision=False,
            cosine_distance=0.0,
            cluster_id=cluster_id,
            reason="insufficient_facts",
        )

    contents = [row["content"] for row in fact_rows if row.get("content")]
    embeddings = await embedding_client.embed(contents)
    new_centroid = _centroid(embeddings)

    distance = _cosine_distance(stored_centroid, new_centroid)
    needs_revision = distance > _get_revision_threshold()

    logger.info(
        "belief_revision_check",
        belief_id=belief_id,
        silo_id=silo_id,
        cluster_id=cluster_id,
        cosine_distance=distance,
        needs_revision=needs_revision,
    )

    return RevisionCheckResult(
        belief_id=belief_id,
        needs_revision=needs_revision,
        cosine_distance=distance,
        cluster_id=cluster_id,
        reason="drift_detected" if needs_revision else "within_threshold",
    )


async def revise_belief(
    store: HyperGraphStore,
    old_belief_id: str,
    silo_id: str,
    llm_client: LLMProvider,
    embedding_client: EmbeddingService,
) -> str:
    """Synthesise a replacement belief and supersede the old one.

    Steps
    -----
    1. Fetch the old belief and its cluster.
    2. Fetch current facts in the cluster; raise InsufficientEvidenceError if
       fewer than MIN_FACTS_FOR_BELIEF.
    3. Call the LLM to produce a new belief statement.
    4. Compute the new centroid embedding.
    5. Write the new :Belief node with SYNTHESIZED_FROM edges.
    6. Store the centroid on the new belief.
    7. Create the :SUPERSEDES edge (new -> old).
    8. Mark the old belief ``wisdom_status = 'stale'``.

    Returns the new belief id.
    """
    belief_rows = await store.execute_query(
        _GET_BELIEF_FOR_REVISION,
        {"belief_id": old_belief_id, "silo_id": silo_id},
    )
    if not belief_rows:
        raise ValueError(f"Belief {old_belief_id!r} not found in silo {silo_id!r}.")

    old_belief: dict[str, Any] = belief_rows[0]
    revision_count = int(old_belief.get("revision_count") or 0) + 1

    cluster_rows = await store.execute_query(
        _GET_BELIEF_CLUSTER,
        {"belief_id": old_belief_id, "silo_id": silo_id},
    )
    if not cluster_rows:
        raise ValueError(f"No cluster found for belief {old_belief_id!r} in silo {silo_id!r}.")
    cluster_id: str = cluster_rows[0]["cluster_id"]

    fact_rows = await store.execute_query(
        GET_FACTS_IN_CLUSTER,
        {"cluster_id": cluster_id, "silo_id": silo_id},
    )
    min_facts = _get_min_facts_for_belief()
    if len(fact_rows) < min_facts:
        raise InsufficientEvidenceError(
            f"Cluster {cluster_id!r} has {len(fact_rows)} fact(s); "
            f"minimum required for revision is {min_facts}."
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

    contents = [row["content"] for row in fact_rows if row.get("content")]
    embeddings = await embedding_client.embed(contents)
    new_centroid = _centroid(embeddings)

    now = datetime.now(UTC)
    new_belief_id = _make_revised_belief_id(old_belief_id, revision_count)

    async with store.transaction():
        await store.execute_write(
            CREATE_BELIEF_FROM_FACTS,
            {
                "belief_id": new_belief_id,
                "silo_id": silo_id,
                "content": belief_text,
                "confidence": confidence,
                "evidence_count": len(fact_ids),
                "created_at": now.isoformat(),
                "valid_from": now.isoformat(),
                "fact_ids": fact_ids,
            },
        )

        await store.execute_write(
            UPDATE_BELIEF_CENTROID,
            {
                "belief_id": new_belief_id,
                "silo_id": silo_id,
                "centroid_embedding": new_centroid,
                "last_revision_check": now.isoformat(),
                "revision_count": revision_count,
            },
        )

        await store.execute_write(
            CREATE_BELIEF_SUPERSEDES,
            {
                "new_belief_id": new_belief_id,
                "old_belief_id": old_belief_id,
                "silo_id": silo_id,
                "reason": "evidence_shift",
                "created_at": now.isoformat(),
            },
        )

        await store.execute_write(
            MARK_BELIEF_STALE,
            {
                "belief_id": old_belief_id,
                "silo_id": silo_id,
                "valid_to": now.isoformat(),
            },
        )

    logger.info(
        "belief_revised",
        old_belief_id=old_belief_id,
        new_belief_id=new_belief_id,
        silo_id=silo_id,
        cluster_id=cluster_id,
        revision_count=revision_count,
        confidence=confidence,
    )

    # Auto-reflection hook: record the revision as a system-generated observation.
    # Errors are caught inside create_auto_reflection and only logged.
    _settings = get_settings()
    if _settings.auto_reflect.enabled and _settings.auto_reflect.on_revision:
        old_content = str(old_belief.get("content") or old_belief_id)
        # distance is not re-computed here; callers use check_belief_revision first.
        # We report 0.0 as a placeholder — the observation is still useful for
        # tracing that a revision occurred.
        magnitude_pct = 0.0
        obs_content = make_revision_content(
            subject=old_content,
            magnitude_pct=magnitude_pct,
        )
        await create_auto_reflection(
            store=store,
            observation_type="belief_change",
            content=obs_content,
            about_node_ids=[old_belief_id, new_belief_id],
            silo_id=silo_id,
        )

    return new_belief_id
