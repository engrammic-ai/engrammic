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
from typing import TYPE_CHECKING, Any, Literal

import structlog

from context_service.config.settings import get_settings
from context_service.db.queries import (
    CLEAR_CASCADE_PENDING,
    CREATE_BELIEF_FACT_EDGES,
    CREATE_BELIEF_FROM_FACTS,
    CREATE_BELIEF_SUPERSEDES,
    FIND_BELIEFS_REFERENCING,
    FLAG_CASCADE_PENDING,
    GET_CASCADE_PENDING_BELIEFS,
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

_SPLIT_SYSTEM_PROMPT = """You are a belief-revision assistant.

Given a belief that is only partially invalidated by new evidence, your job is
to split it into two or more child beliefs:
  - one that reflects what remains valid
  - one (or more) that reflects what has changed or is no longer supported

Rules:
- Each child belief must be a self-contained, falsifiable statement.
- Do not fabricate claims; only use information present in the original belief and the revision note.
- Keep each child belief concise (one sentence).
- Return JSON with exactly one key: "children", which is an array of strings.
  Example: {"children": ["A is still true.", "B has been revised to C."]}
"""


def _build_split_prompt(original_content: str, revision_note: str) -> str:
    return (
        f"Original belief:\n{original_content}\n\n"
        f"Revision note (what changed):\n{revision_note}\n\n"
        "Split the original belief into child beliefs."
    )


_CREATE_CHILD_BELIEF = """
MERGE (b:Belief {id: $belief_id, silo_id: $silo_id})
ON CREATE SET
    b.content = $content,
    b.confidence = $confidence,
    b.evidence_count = $evidence_count,
    b.created_at = $created_at,
    b.valid_from = $valid_from,
    b.valid_to = null,
    b.wisdom_status = 'active'
RETURN b.id AS belief_id
"""

_CREATE_REVISED_FROM = """
MATCH (child:Belief {id: $child_id, silo_id: $silo_id})
MATCH (parent:Belief {id: $parent_id, silo_id: $silo_id})
MERGE (child)-[r:REVISED_FROM {
    created_at: $created_at,
    revision_note: $revision_note
}]->(parent)
RETURN r.created_at AS created_at
"""


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


def _make_revised_belief_id(
    old_belief_id: str,
    counter: int,
    operation: Literal["revision", "split"] = "revision",
) -> str:
    """Deterministic id for revised/split belief derived from its predecessor.

    Args:
        old_belief_id: Parent belief ID.
        counter: Revision count or split child index.
        operation: "revision" for revise_belief, "split" for split_belief.
    """
    return hashlib.blake2b(
        f"{operation}:{old_belief_id}:{counter}".encode(), digest_size=32
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
            },
        )

        if fact_ids:
            await store.execute_write(
                CREATE_BELIEF_FACT_EDGES,
                {"belief_id": new_belief_id, "silo_id": silo_id, "fact_ids": fact_ids},
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


@dataclass(frozen=True)
class SplitBeliefResult:
    """Outcome of split_belief."""

    parent_belief_id: str
    child_belief_ids: list[str]
    child_count: int


async def split_belief(
    store: HyperGraphStore,
    belief_id: str,
    silo_id: str,
    revision_note: str,
    llm_client: LLMProvider,
    embedding_client: EmbeddingService,
) -> SplitBeliefResult:
    """Split a belief into child beliefs when only part of it is being revised.

    Uses an LLM to decompose the original belief content into distinct child
    beliefs based on the revision note.  Each child is persisted as a new
    :Belief node and linked to the parent via a :REVISED_FROM edge.  The
    parent belief is NOT marked stale — it remains active unless the caller
    explicitly supersedes it.

    NOTE: This function has no feature flag gate — it runs LLM inference when
    called.  Callers are responsible for gating if needed (e.g., custodian
    should check its own enabled flags before invoking).

    Parameters
    ----------
    store:
        HyperGraphStore implementation.
    belief_id:
        ID of the :Belief to split.
    silo_id:
        Silo scope.
    revision_note:
        Human-readable description of what changed and why.
    llm_client:
        LLM provider for generating child belief text.
    embedding_client:
        Used to compute centroid embeddings for child beliefs.

    Returns
    -------
    SplitBeliefResult
        Contains the parent belief id and the list of new child belief ids.
    """
    import json

    belief_rows = await store.execute_query(
        _GET_BELIEF_FOR_REVISION,
        {"belief_id": belief_id, "silo_id": silo_id},
    )
    if not belief_rows:
        raise ValueError(f"Belief {belief_id!r} not found in silo {silo_id!r}.")

    belief = belief_rows[0]
    original_content = str(belief.get("content") or "")
    parent_confidence = float(belief.get("confidence") or 0.5)

    prompt = _build_split_prompt(original_content, revision_note)
    raw_response, _usage = await llm_client.complete(
        messages=[
            {"role": "system", "content": _SPLIT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    try:
        parsed = json.loads(raw_response.strip())
        children_text: list[str] = [str(s) for s in parsed.get("children", [])]
    except (json.JSONDecodeError, AttributeError):
        # Fallback: treat non-JSON response as a single child.
        children_text = [raw_response.strip()]

    if not children_text:
        raise ValueError("LLM returned no child beliefs for split.")

    now = datetime.now(UTC)
    child_belief_ids: list[str] = []

    for i, child_text in enumerate(children_text):
        child_id = _make_revised_belief_id(belief_id, i + 1, operation="split")
        child_embedding = await embedding_client.embed([child_text])
        child_centroid = child_embedding[0] if child_embedding else []

        async with store.transaction():
            await store.execute_write(
                _CREATE_CHILD_BELIEF,
                {
                    "belief_id": child_id,
                    "silo_id": silo_id,
                    "content": child_text,
                    "confidence": parent_confidence,
                    "evidence_count": 1,
                    "created_at": now.isoformat(),
                    "valid_from": now.isoformat(),
                },
            )

            await store.execute_write(
                UPDATE_BELIEF_CENTROID,
                {
                    "belief_id": child_id,
                    "silo_id": silo_id,
                    "centroid_embedding": child_centroid,
                    "last_revision_check": now.isoformat(),
                    "revision_count": 0,
                },
            )

            await store.execute_write(
                _CREATE_REVISED_FROM,
                {
                    "child_id": child_id,
                    "parent_id": belief_id,
                    "silo_id": silo_id,
                    "created_at": now.isoformat(),
                    "revision_note": revision_note,
                },
            )

        child_belief_ids.append(child_id)

    logger.info(
        "belief_split",
        parent_belief_id=belief_id,
        silo_id=silo_id,
        child_count=len(child_belief_ids),
    )

    return SplitBeliefResult(
        parent_belief_id=belief_id,
        child_belief_ids=child_belief_ids,
        child_count=len(child_belief_ids),
    )


# ---------------------------------------------------------------------------
# Partial revision: split + cascade flagging
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PartialRevisionResult:
    """Outcome of partial_revise_belief."""

    original_belief_id: str
    revised_id: str
    retained_id: str
    cascade_flagged_count: int


async def partial_revise_belief(
    store: HyperGraphStore,
    belief_id: str,
    silo_id: str,
    revision_note: str,
    llm_client: LLMProvider,
    embedding_client: EmbeddingService,
) -> PartialRevisionResult:
    """Partially revise a belief: split into revised + retained, then cascade-flag dependents.

    When new evidence partially contradicts a belief (some claims remain valid,
    some do not), this function:

    1. Calls split_belief to decompose the original into child beliefs.
       The first child is treated as the *revised* portion; the second (if any)
       is the *retained* portion.  When the LLM returns only one child,
       the original belief is also treated as the retained portion.
    2. Updates the confidence on the retained portion using the original
       belief's confidence unchanged (the split function already inherits it).
    3. Calls flag_cascade to mark all beliefs that reference the original
       belief for review.

    Parameters
    ----------
    store:
        HyperGraphStore implementation.
    belief_id:
        ID of the :Belief to partially revise.
    silo_id:
        Silo scope.
    revision_note:
        Human-readable description of what changed and why.
    llm_client:
        LLM provider for splitting belief content.
    embedding_client:
        Used to compute centroid embeddings for child beliefs.

    Returns
    -------
    PartialRevisionResult
        Contains the original belief id, the revised child id, the retained
        child id, and the number of downstream beliefs flagged for cascade review.
    """
    split_result = await split_belief(
        store=store,
        belief_id=belief_id,
        silo_id=silo_id,
        revision_note=revision_note,
        llm_client=llm_client,
        embedding_client=embedding_client,
    )

    if len(split_result.child_belief_ids) >= 2:
        revised_id = split_result.child_belief_ids[0]
        retained_id = split_result.child_belief_ids[1]
    else:
        # Single-child split: treat the child as revised, original as retained.
        revised_id = split_result.child_belief_ids[0]
        retained_id = belief_id

    flagged_count = await flag_cascade(
        store=store,
        revised_belief_id=belief_id,
        silo_id=silo_id,
    )

    logger.info(
        "belief_partially_revised",
        original_belief_id=belief_id,
        revised_id=revised_id,
        retained_id=retained_id,
        silo_id=silo_id,
        cascade_flagged_count=flagged_count,
    )

    return PartialRevisionResult(
        original_belief_id=belief_id,
        revised_id=revised_id,
        retained_id=retained_id,
        cascade_flagged_count=flagged_count,
    )


async def flag_cascade(
    store: HyperGraphStore,
    revised_belief_id: str,
    silo_id: str,
) -> int:
    """Flag downstream beliefs for review after a belief has been revised.

    Finds all :Belief nodes that reference ``revised_belief_id`` and sets
    ``revision_cascade_pending = true`` on each.  The custodian sensor then
    picks these up for re-evaluation.

    Parameters
    ----------
    store:
        HyperGraphStore implementation.
    revised_belief_id:
        ID of the belief that was just revised or split.
    silo_id:
        Silo scope.

    Returns
    -------
    int
        Number of downstream beliefs flagged.
    """
    referencing_rows = await store.execute_query(
        FIND_BELIEFS_REFERENCING,
        {"belief_id": revised_belief_id, "silo_id": silo_id},
    )
    if not referencing_rows:
        return 0

    belief_ids = [row["belief_id"] for row in referencing_rows]
    now = datetime.now(UTC)

    await store.execute_write(
        FLAG_CASCADE_PENDING,
        {
            "belief_ids": belief_ids,
            "silo_id": silo_id,
            "flagged_at": now.isoformat(),
        },
    )

    logger.info(
        "cascade_flagged",
        revised_belief_id=revised_belief_id,
        silo_id=silo_id,
        flagged_count=len(belief_ids),
    )

    return len(belief_ids)


async def get_cascade_pending(
    store: HyperGraphStore,
    silo_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return beliefs with revision_cascade_pending = true for custodian processing.

    Parameters
    ----------
    store:
        HyperGraphStore implementation.
    silo_id:
        Silo scope.
    limit:
        Maximum number of pending beliefs to return.

    Returns
    -------
    list[dict[str, Any]]
        Each dict contains belief_id, content, confidence, cascade_flagged_at,
        and wisdom_status.
    """
    return await store.execute_query(
        GET_CASCADE_PENDING_BELIEFS,
        {"silo_id": silo_id, "limit": limit},
    )


async def clear_cascade_pending(
    store: HyperGraphStore,
    belief_id: str,
    silo_id: str,
) -> None:
    """Clear the revision_cascade_pending flag after custodian processes a belief.

    Parameters
    ----------
    store:
        HyperGraphStore implementation.
    belief_id:
        ID of the belief to clear.
    silo_id:
        Silo scope.
    """
    now = datetime.now(UTC)
    await store.execute_write(
        CLEAR_CASCADE_PENDING,
        {"belief_id": belief_id, "silo_id": silo_id, "processed_at": now.isoformat()},
    )
