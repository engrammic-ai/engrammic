"""Sage transactions: Core write path with invariant enforcement.

Implements TX0, TX2, TX3, TX17 per brain-transactions-pseudocode.md.

Design:
- Each transaction enforces its invariants at write time
- Returns a typed result or raises a domain error
- Emits async reaction events for downstream processing
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

import structlog

from context_service.db.schema import LABEL_MEMORY
from context_service.reactions.events import ReactionEvent, ReactionEventType, emit_reaction
from context_service.sage.confidence import compute_credibility
from context_service.sage.epistemology import propagate_incremental

if TYPE_CHECKING:
    from context_service.embeddings.base import EmbeddingService
    from context_service.engine.protocols import HyperGraphStore
    from context_service.llm.base import LLMProvider

logger = structlog.get_logger(__name__)


class NodeState(StrEnum):
    """Node lifecycle states per brain-transactions-overview.md Section 2."""

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TOMBSTONED = "TOMBSTONED"
    DELETED = "DELETED"


class SupersedeReason(StrEnum):
    """Reasons for supersession per TX3 spec."""

    CONTRADICTION = "contradiction"
    EVIDENCE_SHIFT = "evidence_shift"
    AUTHOR_UPDATE = "author_update"
    EVIDENCE_ERASED = "evidence_erased"


class ConflictStatus(StrEnum):
    """Conflict status for nodes."""

    NONE = "none"
    UNRESOLVED = "unresolved"
    RESOLVED_SUPERSEDE = "resolved_supersede"
    RESOLVED_MERGE = "resolved_merge"
    RESOLVED_COEXIST = "resolved_coexist"


class LinkType(StrEnum):
    """Allowed edge types for TX17 LINK."""

    RELATED_TO = "RELATED_TO"
    CONTRADICTS = "CONTRADICTS"
    SUPPORTS = "SUPPORTS"
    REFINES = "REFINES"
    GENERALIZES = "GENERALIZES"
    CAUSED_BY = "CAUSED_BY"
    TEMPORAL_BEFORE = "TEMPORAL_BEFORE"
    TEMPORAL_AFTER = "TEMPORAL_AFTER"
    REFERENCES = "REFERENCES"
    DERIVED_FROM = "DERIVED_FROM"
    CAUSES = "CAUSES"
    PREVENTS = "PREVENTS"
    SUPERSEDES = "SUPERSEDES"


HIERARCHICAL_EDGE_TYPES = frozenset({LinkType.REFINES, LinkType.GENERALIZES, LinkType.CAUSED_BY})

PROMOTION_THRESHOLD = 3
SYNTHESIS_THRESHOLD = 3
EVIDENCE_THRESHOLD = 3
SYNTHESIS_CONFIDENCE_THRESHOLD = 0.6
SPO_SIMILARITY_THRESHOLD = 0.80  # Cosine similarity for semantic SPO matching
MAX_CLUSTER_SIZE = 1000
MAX_SYNTHESIS_RETRIES = 3
CANCEL_WINDOW_DURATION_SECONDS = 3600  # 60 minutes
MAX_CASCADE_DEPTH = 10


class SynthesisState(StrEnum):
    """Belief synthesis states per brain-transactions-overview.md Section 4."""

    FRESH = "FRESH"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"


class ClusterState(StrEnum):
    """Cluster states per brain-transactions-overview.md Section 4.5."""

    SPARSE = "SPARSE"
    READY = "READY"
    SYNTHESIZED = "SYNTHESIZED"
    STALE = "STALE"


class BrainError(Exception):
    """Base error for brain transaction failures."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(f"{code}: {message}")


class InvariantViolation(BrainError):
    """Raised when a write would violate an invariant."""

    pass


class ConflictError(BrainError):
    """Raised when a conflict is detected (INV1)."""

    def __init__(self, winner_id: str, message: str = "Conflict detected") -> None:
        super().__init__("CONFLICT_DETECTED", message, winner_id=winner_id)
        self.winner_id = winner_id


class CrossSiloViolation(InvariantViolation):
    """Raised when an operation would create a cross-silo edge (INV5)."""

    def __init__(self, source_silo: str, target_silo: str) -> None:
        super().__init__(
            "CROSS_SILO_VIOLATION",
            f"Cannot create edge between silos {source_silo} and {target_silo}",
            source_silo=source_silo,
            target_silo=target_silo,
        )


class CycleError(InvariantViolation):
    """Raised when an operation would create a cycle (INV4)."""

    def __init__(self, edge_type: str, source_id: str, target_id: str) -> None:
        super().__init__(
            "WOULD_CREATE_CYCLE",
            f"Creating {edge_type} edge from {source_id} to {target_id} would create a cycle",
            edge_type=edge_type,
            source_id=source_id,
            target_id=target_id,
        )


@dataclass
class StoreMemoryResult:
    """Result of TX0 STORE_MEMORY."""

    node_id: uuid.UUID
    created_at: datetime
    layer: str = "memory"
    state: NodeState = NodeState.ACTIVE


@dataclass
class StoreClaimResult:
    """Result of TX2 STORE_CLAIM."""

    node_id: uuid.UUID
    created_at: datetime
    layer: str = "knowledge"
    state: NodeState = NodeState.ACTIVE
    superseded_id: uuid.UUID | None = None
    corroboration_count: int = 1
    promoted: bool = False


@dataclass
class SupersedeResult:
    """Result of TX3 SUPERSEDE."""

    edge_id: uuid.UUID
    winner_id: uuid.UUID
    loser_id: uuid.UUID
    reason: SupersedeReason


@dataclass
class LinkResult:
    """Result of TX17 LINK."""

    edge_id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    edge_type: LinkType


@dataclass
class CommitResult:
    """Result of TX8 COMMIT."""

    commitment_id: uuid.UUID
    silo_id: str
    created_at: datetime
    confidence: float


@dataclass
class CrystallizeResult:
    """Result of TX14 CRYSTALLIZE."""

    commitment_id: uuid.UUID
    hypothesis_id: uuid.UUID
    silo_id: str
    created_at: datetime
    confidence: float


@dataclass
class AcceptProposalResult:
    """Result of accept_proposal transaction."""

    belief_id: uuid.UUID
    proposal_id: uuid.UUID
    accepted: bool
    accepted_at: datetime
    confidence: float


@dataclass
class SynthesizeResult:
    """Result of TX4 SYNTHESIZE.

    Note: belief_id is a ProposedBelief ID. Agent must call accept_proposal
    to promote it to a full Belief.

    .. deprecated::
        cluster_id and cluster_state are deprecated. Use SynthesizeFromFactsResult
        for v2 synthesis.
    """

    belief_id: uuid.UUID | None
    cluster_id: str  # Deprecated: v2 synthesis uses SynthesizeFromFactsResult
    cluster_state: ClusterState  # Deprecated
    fact_count: int
    confidence: float | None
    timed_out: bool = False


@dataclass
class SynthesizeFromFactsResult:
    """Result of v2 SYNTHESIZE_FROM_FACTS.

    Note: belief_id is a ProposedBelief ID. Agent must call accept_proposal
    to promote it to a full Belief.
    """

    belief_id: str | None
    fact_count: int
    confidence: float | None
    timed_out: bool = False


@dataclass
class ReviseBeliefResult:
    """Result of TX5 REVISE_BELIEF."""

    new_belief_id: uuid.UUID | None
    old_belief_id: uuid.UUID
    content_changed: bool
    invalidated: bool = False


@dataclass
class LLMSynthesisResult:
    """Result from LLM synthesis call."""

    success: bool
    content: str | None
    caveats: list[str]
    timed_out: bool
    error: str | None = None


@dataclass
class ForgetResult:
    """Result of TX15 FORGET."""

    node_id: uuid.UUID
    state: NodeState
    tombstoned_at: datetime
    cancel_window_expires: datetime
    cascade_count: int = 0


@dataclass
class CancelForgetResult:
    """Result of TX16 CANCEL_FORGET."""

    node_id: uuid.UUID
    restored_at: datetime
    previous_state: NodeState


@dataclass
class HardDeleteResult:
    """Result of TX10 HARD_DELETE."""

    deleted_count: int
    skipped_count: int
    deleted_ids: list[str]


@dataclass
class PromoteResult:
    """Result of TX18 PROMOTE."""

    claim_id: uuid.UUID
    promoted_at: datetime
    new_confidence: float
    corroboration_count: int


@dataclass
class DemoteResult:
    """Result of TX19 DEMOTE."""

    fact_id: uuid.UUID
    demoted_at: datetime
    new_confidence: float
    corroboration_count: int


def noisy_or_aggregate(confidences: list[float]) -> float:
    """Compute noisy-or aggregation of confidence values.

    Formula: 1 - product(1 - c_i)
    Gives higher aggregate when multiple independent sources agree.
    """
    if not confidences:
        return 0.0
    product = 1.0
    for c in confidences:
        product *= 1.0 - max(0.0, min(1.0, c))
    return 1.0 - product


async def llm_synthesize(
    llm: Any,  # LLMProvider
    facts: list[dict[str, Any]],
    timeout: float,
    previous_belief: str | None = None,
) -> LLMSynthesisResult:
    """Call LLM to synthesize a belief from facts.

    Args:
        llm: LLM provider instance.
        facts: List of fact dicts with 'content' and 'confidence' keys.
        timeout: Timeout in seconds.
        previous_belief: For revisions, the previous belief content.

    Returns:
        LLMSynthesisResult with synthesis output or error.
    """
    import asyncio

    from context_service.engine.synthesis import _SYNTHESIS_SYSTEM_PROMPT, _build_synthesis_prompt

    prompt = _build_synthesis_prompt(facts)
    if previous_belief:
        prompt += f"\n\nPrevious belief (now stale): {previous_belief}"

    try:
        response_text, _usage = await asyncio.wait_for(
            llm.complete(
                messages=[
                    {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            ),
            timeout=timeout,
        )
        return LLMSynthesisResult(
            success=True,
            content=response_text.strip(),
            caveats=[],
            timed_out=False,
        )
    except TimeoutError:
        return LLMSynthesisResult(
            success=False,
            content=None,
            caveats=[],
            timed_out=True,
            error="synthesis timed out",
        )
    except Exception as e:
        return LLMSynthesisResult(
            success=False,
            content=None,
            caveats=[],
            timed_out=False,
            error=str(e),
        )


async def synthesize(
    store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
    llm: LLMProvider,
    _embedder: EmbeddingService,
    *,
    mode: Literal["async", "sync"] = "async",
    timeout_seconds: float = 30.0,
    emit: bool = True,
) -> tuple[SynthesizeResult, list[ReactionEvent]]:
    """Create Belief from fact cluster (TX4).

    Per brain-transactions-pseudocode.md:
    - Modes: ASYNC (30s timeout), SYNC (2s timeout for query-time)
    - Enforces INV3: Every Belief has >= N SYNTHESIZED_FROM to ACTIVE Facts

    .. deprecated::
        Use synthesize_from_facts() instead. Cluster-based synthesis is
        deprecated in CITE v2.
    """
    import warnings

    warnings.warn(
        "synthesize() is deprecated. Use synthesize_from_facts() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from context_service.db import queries as q

    effective_timeout = 2.0 if mode == "sync" else timeout_seconds

    # Acquire lock on cluster
    lock_result = await store.execute_query(
        q.GET_CLUSTER_FOR_SYNTHESIS,
        {
            "cluster_id": cluster_id,
            "silo_id": silo_id,
        },
    )

    if not lock_result:
        return SynthesizeResult(
            belief_id=None,
            cluster_id=cluster_id,
            cluster_state=ClusterState.SPARSE,
            fact_count=0,
            confidence=None,
        ), []

    cluster_state = lock_result[0].get("state", "SPARSE")

    try:
        # Fetch facts in cluster
        facts_result = await store.execute_query(
            q.GET_FACTS_IN_CLUSTER,
            {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
            },
        )
        facts = list(facts_result) if facts_result else []
        fact_count = len(facts)

        # Check threshold
        if fact_count < SYNTHESIS_THRESHOLD:
            await store.execute_write(
                q.RELEASE_CLUSTER_LOCK,
                {
                    "cluster_id": cluster_id,
                    "silo_id": silo_id,
                    "state": ClusterState.SPARSE.value,
                },
            )
            return SynthesizeResult(
                belief_id=None,
                cluster_id=cluster_id,
                cluster_state=ClusterState.SPARSE,
                fact_count=fact_count,
                confidence=None,
            ), []

        # Compute aggregate confidence
        confidences = [float(f.get("confidence", 0.8)) for f in facts]
        aggregate_confidence = noisy_or_aggregate(confidences)

        if aggregate_confidence < SYNTHESIS_CONFIDENCE_THRESHOLD:
            await store.execute_write(
                q.RELEASE_CLUSTER_LOCK,
                {
                    "cluster_id": cluster_id,
                    "silo_id": silo_id,
                    "state": ClusterState.READY.value,
                },
            )
            return SynthesizeResult(
                belief_id=None,
                cluster_id=cluster_id,
                cluster_state=ClusterState.READY,
                fact_count=fact_count,
                confidence=aggregate_confidence,
            ), []

        # Call LLM
        synthesis_result = await llm_synthesize(llm, facts, effective_timeout)

        if synthesis_result.timed_out or not synthesis_result.success:
            await store.execute_write(
                q.RELEASE_CLUSTER_LOCK,
                {
                    "cluster_id": cluster_id,
                    "silo_id": silo_id,
                    "state": ClusterState.READY.value,
                },
            )
            return SynthesizeResult(
                belief_id=None,
                cluster_id=cluster_id,
                cluster_state=ClusterState.READY,
                fact_count=fact_count,
                confidence=aggregate_confidence,
                timed_out=synthesis_result.timed_out,
            ), []

        # Create ProposedBelief (not Belief directly - requires agent accept)
        belief_id = uuid.uuid4()
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(days=7)  # 7-day expiry for unreviewed proposals
        fact_ids = [f["fact_id"] for f in facts]

        await store.execute_write(
            q.CREATE_PROPOSED_BELIEF,
            {
                "id": str(belief_id),
                "silo_id": silo_id,
                "content": synthesis_result.content,
                "confidence": aggregate_confidence,
                "created_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "synthesized_from_ids": fact_ids,
            },
        )

        # Update cluster
        await store.execute_write(
            q.UPDATE_CLUSTER_AFTER_SYNTHESIS,
            {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "state": ClusterState.SYNTHESIZED.value,
                "belief_id": str(belief_id),
                "synthesized_at": created_at.isoformat(),
            },
        )

        events: list[ReactionEvent] = [
            ReactionEvent(
                event_type=ReactionEventType.COMPUTE_EMBEDDING,
                node_id=str(belief_id),
                silo_id=silo_id,
            ),
            ReactionEvent(
                event_type=ReactionEventType.UPDATE_HEAT,
                node_id=str(belief_id),
                silo_id=silo_id,
                payload={"access_type": "SYNTHESIS"},
            ),
            # Notify agents that a proposal is ready for review
            ReactionEvent(
                event_type=ReactionEventType.PROPOSAL_READY,
                node_id=str(belief_id),
                silo_id=silo_id,
            ),
        ]

        if emit:
            for event in events:
                await emit_reaction(event)

        logger.debug(
            "synthesize_complete",
            belief_id=str(belief_id),
            cluster_id=cluster_id,
            fact_count=fact_count,
        )

        return SynthesizeResult(
            belief_id=belief_id,
            cluster_id=cluster_id,
            cluster_state=ClusterState.SYNTHESIZED,
            fact_count=fact_count,
            confidence=aggregate_confidence,
        ), events

    except Exception:
        await store.execute_write(
            q.RELEASE_CLUSTER_LOCK,
            {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "state": cluster_state,
            },
        )
        raise


async def synthesize_from_facts(
    store: HyperGraphStore,
    fact_ids: list[str],
    silo_id: str,
    llm: LLMProvider,
    *,
    mode: Literal["async", "sync"] = "async",
    timeout_seconds: float = 30.0,
) -> tuple[SynthesizeFromFactsResult, list[ReactionEvent]]:
    """Create ProposedBelief from corroborating facts (v2).

    Unlike v1 synthesize(), this takes fact_ids directly instead of cluster_id.
    Enforces INV3: Every Belief has >= N SYNTHESIZED_FROM to ACTIVE Facts.

    Args:
        store: Graph store for queries.
        fact_ids: List of Fact node IDs to synthesize from.
        silo_id: Tenant isolation ID.
        llm: LLM provider for synthesis.
        mode: "async" (30s timeout) or "sync" (2s for query-time).
        timeout_seconds: Override timeout for async mode.

    Returns:
        SynthesizeFromFactsResult with belief_id if successful.
    """
    from context_service.db import queries as q

    effective_timeout = 2.0 if mode == "sync" else timeout_seconds

    # Validate minimum facts
    if len(fact_ids) < SYNTHESIS_THRESHOLD:
        return SynthesizeFromFactsResult(
            belief_id=None,
            fact_count=len(fact_ids),
            confidence=None,
        ), []

    # Fetch fact content
    facts_result = await store.execute_query(
        q.GET_FACTS_BY_IDS,
        {"fact_ids": fact_ids, "silo_id": silo_id},
    )
    facts = list(facts_result) if facts_result else []

    if len(facts) < SYNTHESIS_THRESHOLD:
        return SynthesizeFromFactsResult(
            belief_id=None,
            fact_count=len(facts),
            confidence=None,
        ), []

    # Aggregate confidence
    confidences = [float(f.get("confidence", 0.8)) for f in facts]
    aggregate_confidence = noisy_or_aggregate(confidences)

    if aggregate_confidence < SYNTHESIS_CONFIDENCE_THRESHOLD:
        return SynthesizeFromFactsResult(
            belief_id=None,
            fact_count=len(facts),
            confidence=aggregate_confidence,
        ), []

    # Call LLM
    synthesis_result = await llm_synthesize(llm, facts, effective_timeout)

    if synthesis_result.timed_out or not synthesis_result.success:
        return SynthesizeFromFactsResult(
            belief_id=None,
            fact_count=len(facts),
            confidence=aggregate_confidence,
            timed_out=synthesis_result.timed_out,
        ), []

    # Create ProposedBelief with SYNTHESIZED_FROM edges
    belief_id = uuid.uuid4()
    created_at = datetime.now(UTC)
    expires_at = created_at + timedelta(days=7)

    await store.execute_write(
        q.CREATE_PROPOSED_BELIEF_V2,
        {
            "id": str(belief_id),
            "silo_id": silo_id,
            "content": synthesis_result.content,
            "confidence": aggregate_confidence,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "fact_ids": fact_ids,
        },
    )

    events = [
        ReactionEvent(
            event_type=ReactionEventType.COMPUTE_EMBEDDING,
            node_id=str(belief_id),
            silo_id=silo_id,
        ),
    ]

    logger.info(
        "synthesize_from_facts_complete",
        belief_id=str(belief_id),
        fact_count=len(facts),
        confidence=aggregate_confidence,
    )

    return SynthesizeFromFactsResult(
        belief_id=str(belief_id),
        fact_count=len(facts),
        confidence=aggregate_confidence,
    ), events


async def _sync_to_postgres(
    node_id: uuid.UUID,
    silo_id: str,
    layer: str,
    content: str,
    state: str = "ACTIVE",
) -> None:
    """Sync node to Postgres shadow table for text search.

    Best-effort: logs warning on failure, does not raise.
    Memgraph remains source of truth.
    """
    import time

    from context_service.telemetry.recorder import (
        get_db_pool,
        record_postgres_sync_error,
        record_postgres_sync_latency,
    )

    pool = get_db_pool()
    if pool is None:
        logger.warning("postgres_sync_skip_no_pool", node_id=str(node_id))
        return

    t0 = time.monotonic()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO nodes (id, silo_id, layer, content, state, created_at)
                VALUES ($1, $2::uuid, $3, $4, $5, now())
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    state = EXCLUDED.state
                """,
                node_id,
                uuid.UUID(silo_id) if isinstance(silo_id, str) else silo_id,
                layer,
                content,
                state,
            )
        record_postgres_sync_latency((time.monotonic() - t0) * 1000, "upsert")
    except Exception as exc:
        record_postgres_sync_error("upsert")
        logger.warning(
            "postgres_sync_failed",
            node_id=str(node_id),
            silo_id=silo_id,
            error=str(exc),
        )


async def _sync_postgres_state(
    node_id: str,
    silo_id: str,
    state: str,
) -> None:
    """Update only the state of an existing node in Postgres.

    For supersession: update loser state without touching content.
    """
    import time

    from context_service.telemetry.recorder import (
        get_db_pool,
        record_postgres_sync_error,
        record_postgres_sync_latency,
    )

    pool = get_db_pool()
    if pool is None:
        return

    t0 = time.monotonic()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE nodes SET state = $1
                WHERE id = $2::uuid AND silo_id = $3::uuid
                """,
                state,
                uuid.UUID(node_id) if isinstance(node_id, str) else node_id,
                uuid.UUID(silo_id) if isinstance(silo_id, str) else silo_id,
            )
        record_postgres_sync_latency((time.monotonic() - t0) * 1000, "state_update")
    except Exception as exc:
        record_postgres_sync_error("state_update")
        logger.warning(
            "postgres_state_sync_failed",
            node_id=node_id,
            silo_id=silo_id,
            state=state,
            error=str(exc),
        )


async def store_memory(
    store: HyperGraphStore,
    content: str,
    silo_id: str,
    agent_id: str,
    *,
    layer: str = "memory",
    tags: list[str] | None = None,
    content_type: str = "text",
    decay_class: str = "standard",
    metadata: dict[str, Any] | None = None,
    emit: bool = True,
) -> tuple[StoreMemoryResult, list[ReactionEvent]]:
    """Store an observation to Memory layer (TX0).

    Per brain-transactions-pseudocode.md:
    - No invariants beyond silo membership (simplest write path)
    - Async reactions: compute_embedding, update_heat, check_extraction_trigger

    Args:
        store: Graph store instance.
        content: What to remember.
        silo_id: Tenant isolation ID.
        agent_id: Agent performing the write.
        tags: Optional categorization tags.
        content_type: Type of content (text, utterance, event).
        decay_class: How long to keep (ephemeral, standard, durable, permanent).
        metadata: Additional properties to store.

    Returns:
        Tuple of (result, reaction_events).
    """
    node_id = uuid.uuid4()
    created_at = datetime.now(UTC)

    label = _CONTENT_TYPE_TO_LABEL.get(content_type, LABEL_MEMORY)

    props: dict[str, Any] = {
        "layer": layer,
        "state": NodeState.ACTIVE.value,
        "content_type": content_type,
        "decay_class": decay_class,
        "created_by": agent_id,
        "embedding_pending": False,
        **(metadata or {}),
    }
    if tags:
        props["tags"] = tags

    # Build Cypher with literal label (labels can't be parameterized in Cypher)
    # Must include all fields expected by _node_from_record in memgraph_store.py
    cypher = f"""
    CREATE (n:Node:{label} {{
        id: $id,
        type: $type,
        silo_id: $silo_id,
        content: $content,
        created_at: $created_at,
        updated_at: $updated_at,
        valid_from: $valid_from,
        properties: $props,
        committed: true,
        version: 1
    }})
    RETURN n.id AS id
    """

    await store.execute_write(
        cypher,
        {
            "id": str(node_id),
            "type": label,
            "silo_id": silo_id,
            "content": content,
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
            "valid_from": created_at.isoformat(),
            "props": props,
        },
    )

    result = StoreMemoryResult(
        node_id=node_id,
        created_at=created_at,
    )

    await _sync_to_postgres(node_id, silo_id, layer, content)

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type=ReactionEventType.COMPUTE_EMBEDDING,
            node_id=str(node_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(node_id),
            silo_id=silo_id,
            payload={"access_type": "WRITE"},
        ),
    ]

    if len(content) > _EXTRACTION_THRESHOLD:
        events.append(
            ReactionEvent(
                event_type=ReactionEventType.CHECK_EXTRACTION_TRIGGER,
                node_id=str(node_id),
                silo_id=silo_id,
            )
        )

    if emit:
        for event in events:
            await emit_reaction(event)

    logger.debug(
        "store_memory_complete",
        node_id=str(node_id),
        silo_id=silo_id,
        reaction_count=len(events),
    )

    return result, events


_CONTENT_TYPE_TO_LABEL: dict[str, str] = {
    "text": LABEL_MEMORY,
    "utterance": LABEL_MEMORY,
    "event": LABEL_MEMORY,
    "observation": LABEL_MEMORY,
}

_EXTRACTION_THRESHOLD = 500


async def store_claim(
    store: HyperGraphStore,
    content: str,
    evidence_refs: list[str],
    silo_id: str,
    agent_id: str,
    *,
    subject: str | None = None,
    predicate: str | None = None,
    object_value: str | None = None,
    source_tier: str | None = None,
    confidence: float = 0.8,
    supersedes: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    emit: bool = True,
    embedding_service: EmbeddingService | None = None,
) -> tuple[StoreClaimResult, list[ReactionEvent]]:
    """Store a claim to Knowledge layer with evidence (TX2).

    Per brain-transactions-pseudocode.md:
    - Enforces INV1: No contradicting ACTIVE claims (same silo, s, p, different o)
    - Enforces INV2: Every Fact has >= 1 DERIVED_FROM to Memory
    - Enforces INV5: No cross-silo edges
    - Uses optimistic locking on (silo_id, subject, predicate)
    - Sync reaction: CHECK_CORROBORATION (may trigger TX18 PROMOTE)

    Args:
        store: Graph store instance.
        content: The claim text.
        evidence_refs: References to evidence (node:<uuid> or URIs).
        silo_id: Tenant isolation ID.
        agent_id: Agent performing the write.
        subject: Subject of the claim (SPO triple).
        predicate: Predicate of the claim (SPO triple).
        object_value: Object of the claim (SPO triple). Named to avoid shadowing builtin.
        source_tier: Quality tier (authoritative, validated, community, unknown).
        confidence: Confidence score 0.0-1.0.
        supersedes: Node ID this claim replaces.
        metadata: Additional properties.
        tags: Categorization tags.

    Returns:
        Tuple of (result, reaction_events).

    Raises:
        InvariantViolation: If INV2 violated (no evidence).
        CrossSiloViolation: If evidence is from different silo.
        ConflictError: If conflicting claim exists and new claim loses.
    """
    if not evidence_refs:
        raise InvariantViolation(
            "NO_EVIDENCE",
            "evidence_refs must be non-empty (INV2)",
        )

    evidence_node_ids = [ref[5:] for ref in evidence_refs if ref.startswith("node:")]

    if evidence_node_ids:
        validation = await _validate_evidence_nodes(store, evidence_node_ids, silo_id)
        if validation["error"]:
            raise InvariantViolation(
                validation["error"],
                validation["message"],
                **validation.get("details", {}),
            )

        if not validation["has_memory_layer"]:
            raise InvariantViolation(
                "NO_MEMORY_EVIDENCE",
                "At least one evidence ref must be from Memory layer (INV2)",
            )

    node_id = uuid.uuid4()
    created_at = datetime.now(UTC)

    credibility_breakdown = compute_credibility(
        source_tier=source_tier,
        method=None,  # Default to direct for MCP calls
        raw_confidence=confidence,
    )

    props: dict[str, Any] = {
        "layer": "knowledge",
        "state": NodeState.ACTIVE.value,
        "claim_status": "UNPROMOTED",
        "confidence": confidence,
        "credibility": credibility_breakdown.credibility,
        "credibility_factors": credibility_breakdown.to_dict(),
        "source_tier": source_tier or "unknown",
        "created_by": agent_id,
        "evidence": evidence_refs,
        "embedding_pending": False,
        **(metadata or {}),
    }
    if tags:
        props["tags"] = tags
    if subject and predicate and object_value:
        props["subject"] = subject
        props["predicate"] = predicate
        props["object"] = object_value

    cypher = """
    CREATE (n:Node:Claim {
        id: $id,
        type: $type,
        silo_id: $silo_id,
        content: $content,
        created_at: $created_at,
        updated_at: $updated_at,
        valid_from: $valid_from,
        properties: $props,
        committed: true,
        version: 1
    })
    RETURN n.id AS id
    """

    await store.execute_write(
        cypher,
        {
            "id": str(node_id),
            "type": "Claim",
            "silo_id": silo_id,
            "content": content,
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
            "valid_from": created_at.isoformat(),
            "props": props,
        },
    )

    if evidence_node_ids:
        await _create_derived_from_edges(store, str(node_id), evidence_node_ids, silo_id)

    superseded_id: uuid.UUID | None = None
    if supersedes:
        await _create_supersedes_edge(
            store,
            str(node_id),
            supersedes,
            silo_id,
            SupersedeReason.AUTHOR_UPDATE,
        )
        superseded_id = uuid.UUID(supersedes)

    corroboration_count, _ = await _check_corroboration(
        store, str(node_id), silo_id, embedding_service
    )

    # FLAG_CONTRADICTION: detect and flag structural conflicts
    conflict_events = await detect_spo_conflict(
        store, str(node_id), subject, predicate, object_value, silo_id
    )

    result = StoreClaimResult(
        node_id=node_id,
        created_at=created_at,
        superseded_id=superseded_id,
        corroboration_count=corroboration_count,
    )

    await _sync_to_postgres(node_id, silo_id, "knowledge", content)

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type=ReactionEventType.COMPUTE_EMBEDDING,
            node_id=str(node_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(node_id),
            silo_id=silo_id,
            payload={"access_type": "WRITE"},
        ),
    ]

    if supersedes:
        events.append(
            ReactionEvent(
                event_type=ReactionEventType.CASCADE_STALENESS,
                node_id=supersedes,
                silo_id=silo_id,
                payload={"depth": 1},
            )
        )

    events.extend(conflict_events)

    if emit:
        for event in events:
            await emit_reaction(event)

    logger.debug(
        "store_claim_complete",
        node_id=str(node_id),
        silo_id=silo_id,
        corroboration_count=corroboration_count,
        reaction_count=len(events),
    )

    return result, events


async def supersede(
    store: HyperGraphStore,
    winner_id: str,
    loser_id: str,
    silo_id: str,
    reason: SupersedeReason,
    *,
    emit: bool = True,
) -> tuple[SupersedeResult, list[ReactionEvent]]:
    """Mark a node as superseded by another (TX3).

    Per brain-transactions-pseudocode.md:
    - Enforces INV4: SUPERSEDES edges are acyclic
    - Enforces INV5: No cross-silo edges
    - Updates loser state to SUPERSEDED, sets valid_to

    Args:
        store: Graph store instance.
        winner_id: ID of the superseding node.
        loser_id: ID of the node being superseded.
        silo_id: Tenant isolation ID.
        reason: Why the supersession is happening.

    Returns:
        Tuple of (result, reaction_events).

    Raises:
        CycleError: If supersession would create a cycle.
        CrossSiloViolation: If nodes are in different silos.
        BrainError: If nodes don't exist or are in wrong state.
    """
    validation = await _validate_supersession(store, winner_id, loser_id, silo_id)
    if validation["error"]:
        if validation["error"] == "WOULD_CREATE_CYCLE":
            raise CycleError("SUPERSEDES", winner_id, loser_id)
        if validation["error"] == "CROSS_SILO_VIOLATION":
            raise CrossSiloViolation(
                validation.get("winner_silo", silo_id),
                validation.get("loser_silo", silo_id),
            )
        raise BrainError(
            validation["error"],
            validation.get("message", "Supersession validation failed"),
        )

    edge_id = uuid.uuid4()
    await _create_supersedes_edge(store, winner_id, loser_id, silo_id, reason)

    result = SupersedeResult(
        edge_id=edge_id,
        winner_id=uuid.UUID(winner_id),
        loser_id=uuid.UUID(loser_id),
        reason=reason,
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type=ReactionEventType.CASCADE_STALENESS,
            node_id=loser_id,
            silo_id=silo_id,
            payload={"depth": 1},
        ),
    ]

    if emit:
        for event in events:
            await emit_reaction(event)

    logger.debug(
        "supersede_complete",
        winner_id=winner_id,
        loser_id=loser_id,
        reason=reason.value,
    )

    return result, events


async def link(
    store: HyperGraphStore,
    source_id: str,
    target_id: str,
    edge_type: LinkType,
    silo_id: str,
    agent_id: str,
    *,
    metadata: dict[str, Any] | None = None,
    weight: float = 1.0,
    emit: bool = True,
) -> tuple[LinkResult, list[ReactionEvent]]:
    """Create a typed relationship between nodes (TX17).

    Per brain-transactions-pseudocode.md:
    - Enforces INV5: No cross-silo edges
    - Enforces cycle detection for hierarchical types (REFINES, GENERALIZES, CAUSED_BY)
    - Checks for duplicate edges

    Args:
        store: Graph store instance.
        source_id: Source node ID.
        target_id: Target node ID.
        edge_type: Type of relationship.
        silo_id: Tenant isolation ID.
        agent_id: Agent creating the link.
        metadata: Additional edge properties.
        weight: Edge weight (0.0-1.0).

    Returns:
        Tuple of (result, reaction_events).

    Raises:
        CrossSiloViolation: If nodes are in different silos.
        CycleError: If edge would create a cycle (for hierarchical types).
        BrainError: If nodes don't exist or edge already exists.
    """
    validation = await _validate_link(store, source_id, target_id, edge_type, silo_id)
    if validation["error"]:
        if validation["error"] == "CROSS_SILO_VIOLATION":
            raise CrossSiloViolation(
                validation.get("source_silo", silo_id),
                validation.get("target_silo", silo_id),
            )
        if validation["error"] == "WOULD_CREATE_CYCLE":
            raise CycleError(edge_type.value, source_id, target_id)
        if validation["error"] == "DUPLICATE_EDGE":
            raise BrainError(
                "DUPLICATE_EDGE",
                f"Edge {edge_type.value} already exists between {source_id} and {target_id}",
                existing_id=validation.get("existing_id"),
            )
        raise BrainError(
            validation["error"],
            validation.get("message", "Link validation failed"),
        )

    edge_id = uuid.uuid4()
    created_at = datetime.now(UTC)

    cypher = f"""
    MATCH (s {{id: $source_id, silo_id: $silo_id}})
    MATCH (t {{id: $target_id, silo_id: $silo_id}})
    CREATE (s)-[e:{edge_type.value} {{
        id: $edge_id,
        weight: $weight,
        created_at: $created_at,
        created_by: $agent_id,
        metadata: $metadata
    }}]->(t)
    RETURN e.id AS id
    """

    await store.execute_write(
        cypher,
        {
            "source_id": source_id,
            "target_id": target_id,
            "silo_id": silo_id,
            "edge_id": str(edge_id),
            "weight": weight,
            "created_at": created_at.isoformat(),
            "agent_id": agent_id,
            "metadata": metadata or {},
        },
    )

    result = LinkResult(
        edge_id=edge_id,
        source_id=uuid.UUID(source_id),
        target_id=uuid.UUID(target_id),
        edge_type=edge_type,
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=source_id,
            silo_id=silo_id,
            payload={"access_type": "LINK"},
        ),
        ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=target_id,
            silo_id=silo_id,
            payload={"access_type": "LINK"},
        ),
    ]

    if edge_type == LinkType.CONTRADICTS:
        events.append(
            ReactionEvent(
                event_type=ReactionEventType.FLAG_CONTRADICTION,
                node_id=source_id,
                silo_id=silo_id,
                payload={"contradicting_node_id": target_id},
            )
        )

    if edge_type in (LinkType.SUPPORTS, LinkType.CONTRADICTS):
        await _run_incremental_propagation(store, target_id, silo_id)

    if emit:
        for event in events:
            await emit_reaction(event)

    logger.debug(
        "link_complete",
        edge_id=str(edge_id),
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type.value,
    )

    return result, events


async def _validate_about_refs(
    store: HyperGraphStore,
    about_refs: list[str],
    silo_id: str,
) -> dict[str, Any]:
    """Validate about_refs exist, are in same silo, and not tombstoned."""
    from context_service.db import queries as q

    if not about_refs:
        return {"error": "EMPTY_ABOUT_REFS", "message": "about_refs must be non-empty"}

    results = await store.execute_query(
        q.VALIDATE_ABOUT_REFS,
        {
            "node_ids": about_refs,
            "silo_id": silo_id,
        },
    )

    found_ids = {r["id"] for r in results}
    missing = set(about_refs) - found_ids
    if missing:
        return {
            "error": "ABOUT_REF_NOT_FOUND",
            "message": f"About refs not found: {missing}",
            "missing_ids": list(missing),
        }

    tombstoned = [r for r in results if r.get("state") == NodeState.TOMBSTONED.value]
    if tombstoned:
        return {
            "error": "ABOUT_REF_TOMBSTONED",
            "message": f"About refs are tombstoned: {[r['id'] for r in tombstoned]}",
        }

    return {"error": None}


async def commit(
    store: HyperGraphStore,
    content: str,
    about_refs: list[str],
    silo_id: str,
    agent_id: str,
    *,
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
    emit: bool = True,
) -> tuple[CommitResult, list[ReactionEvent]]:
    """Agent declares a stance directly (TX8).

    Per brain-transactions-pseudocode.md:
    - Enforces: about_refs non-empty, all exist in same silo (INV5), not tombstoned
    - Creates: Commitment node, ABOUT edges, DECLARED_BY edge (INV7)
    """
    from context_service.db import queries as q

    validation = await _validate_about_refs(store, about_refs, silo_id)
    if validation["error"]:
        raise InvariantViolation(
            validation["error"],
            validation["message"],
            **{k: v for k, v in validation.items() if k not in ("error", "message")},
        )

    commitment_id = uuid.uuid4()
    created_at = datetime.now(UTC)

    props: dict[str, Any] = {
        "layer": "wisdom",
        "type": "commitment",
        "state": NodeState.ACTIVE.value,
        "confidence": confidence,
        "created_by": agent_id,
        **(metadata or {}),
    }

    await store.execute_write(
        q.CREATE_COMMITMENT_WITH_ABOUT,
        {
            "id": str(commitment_id),
            "silo_id": silo_id,
            "content": content,
            "created_at": created_at.isoformat(),
            "props": props,
            "about_ids": about_refs,
            "agent_id": agent_id,
        },
    )

    result = CommitResult(
        commitment_id=commitment_id,
        silo_id=silo_id,
        created_at=created_at,
        confidence=confidence,
    )

    await _sync_to_postgres(commitment_id, silo_id, "wisdom", content)

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type=ReactionEventType.COMPUTE_EMBEDDING,
            node_id=str(commitment_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(commitment_id),
            silo_id=silo_id,
            payload={"access_type": "WRITE"},
        ),
    ]

    if emit:
        for event in events:
            await emit_reaction(event)

    logger.debug(
        "commit_complete",
        commitment_id=str(commitment_id),
        silo_id=silo_id,
        about_count=len(about_refs),
    )

    return result, events


async def _validate_hypothesis(
    store: HyperGraphStore,
    hypothesis_id: str,
    silo_id: str,
    session_id: str | None,
) -> dict[str, Any]:
    """Validate hypothesis exists, belongs to session, not crystallized, not tombstoned."""
    from context_service.db import queries as q

    params: dict[str, Any] = {
        "hypothesis_id": hypothesis_id,
        "silo_id": silo_id,
    }

    if session_id is not None:
        params["session_id"] = session_id
        results = await store.execute_query(
            q.GET_HYPOTHESIS_FOR_CRYSTALLIZE,
            params,
        )
    else:
        results = await store.execute_query(
            q.GET_HYPOTHESIS_BY_ID,
            params,
        )

    if not results:
        msg = (
            "Hypothesis not found"
            if session_id is None
            else "Hypothesis not found or wrong session"
        )
        return {"error": "HYPOTHESIS_NOT_FOUND", "message": msg}

    row = results[0]
    if row.get("state") == NodeState.TOMBSTONED.value:
        return {"error": "HYPOTHESIS_TOMBSTONED", "message": "Hypothesis is tombstoned"}

    if row.get("crystallized"):
        return {
            "error": "ALREADY_CRYSTALLIZED",
            "message": "Hypothesis already crystallized",
        }

    return {
        "error": None,
        "content": row.get("content"),
        "confidence": row.get("confidence", 0.8),
    }


async def crystallize(
    store: HyperGraphStore,
    hypothesis_id: str,
    silo_id: str,
    agent_id: str,
    session_id: str | None = None,
    *,
    emit: bool = True,
) -> tuple[CrystallizeResult, list[ReactionEvent]]:
    """Convert WorkingHypothesis to Commitment (TX14)."""
    from context_service.db import queries as q

    validation = await _validate_hypothesis(store, hypothesis_id, silo_id, session_id)
    if validation["error"]:
        raise InvariantViolation(validation["error"], validation["message"])

    content = validation["content"]
    confidence = float(validation["confidence"])

    # Get about_refs from hypothesis
    about_results = await store.execute_query(
        q.GET_HYPOTHESIS_ABOUT_REFS,
        {
            "hypothesis_id": hypothesis_id,
            "silo_id": silo_id,
        },
    )

    about_refs = [r["id"] for r in about_results]
    tombstoned = [r for r in about_results if r.get("state") == NodeState.TOMBSTONED.value]
    if tombstoned:
        raise InvariantViolation(
            "ABOUT_REF_TOMBSTONED",
            f"About refs are tombstoned: {[r['id'] for r in tombstoned]}",
        )

    commitment_id = uuid.uuid4()
    created_at = datetime.now(UTC)

    props: dict[str, Any] = {
        "layer": "wisdom",
        "type": "commitment",
        "state": NodeState.ACTIVE.value,
        "confidence": confidence,
        "created_by": agent_id,
        "source_hypothesis_id": hypothesis_id,
    }

    await store.execute_write(
        q.CREATE_COMMITMENT_WITH_ABOUT,
        {
            "id": str(commitment_id),
            "silo_id": silo_id,
            "content": content,
            "created_at": created_at.isoformat(),
            "props": props,
            "about_ids": about_refs,
            "agent_id": agent_id,
        },
    )

    await store.execute_write(
        q.CREATE_CRYSTALLIZED_FROM_EDGE,
        {
            "commitment_id": str(commitment_id),
            "hypothesis_id": hypothesis_id,
            "silo_id": silo_id,
            "created_at": created_at.isoformat(),
        },
    )

    result = CrystallizeResult(
        commitment_id=commitment_id,
        hypothesis_id=uuid.UUID(hypothesis_id),
        silo_id=silo_id,
        created_at=created_at,
        confidence=confidence,
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type=ReactionEventType.COMPUTE_EMBEDDING,
            node_id=str(commitment_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(commitment_id),
            silo_id=silo_id,
            payload={"access_type": "WRITE"},
        ),
    ]

    if emit:
        for event in events:
            await emit_reaction(event)

    logger.debug(
        "crystallize_complete",
        commitment_id=str(commitment_id),
        hypothesis_id=hypothesis_id,
        silo_id=silo_id,
    )

    return result, events


async def accept_proposal(
    store: HyperGraphStore,
    proposal_id: str,
    silo_id: str,
    agent_id: str,
    *,
    reason: str | None = None,
    override_confidence: float | None = None,
    emit: bool = True,
) -> tuple[AcceptProposalResult, list[ReactionEvent]]:
    """Accept a ProposedBelief, creating a full Belief.

    Uses existing ACCEPT_PROPOSED_BELIEF query which creates a NEW Belief node
    linked to ProposedBelief via PROMOTED_FROM edge.

    Args:
        store: Graph store instance.
        proposal_id: ProposedBelief node ID.
        silo_id: Tenant isolation ID.
        agent_id: Agent accepting the proposal.
        reason: Optional rationale for acceptance.
        override_confidence: Override the synthesized confidence.

    Returns:
        Tuple of (result, reaction_events).

    Raises:
        InvariantViolation: If proposal not found, already rejected, or invalid.
    """
    from context_service.db import queries as q

    # Check proposal exists and get status
    proposal_result = await store.execute_query(
        q.GET_PROPOSED_BELIEF,
        {"proposed_belief_id": proposal_id, "silo_id": silo_id},
    )

    if not proposal_result:
        raise InvariantViolation("PROPOSAL_NOT_FOUND", "ProposedBelief not found")

    row = proposal_result[0]
    status = row.get("status")

    # Already accepted - idempotent, find existing belief
    if status == "accepted":
        existing_belief = await store.execute_query(
            """
            MATCH (b:Belief)-[:PROMOTED_FROM]->(pb:ProposedBelief {id: $proposal_id, silo_id: $silo_id})
            RETURN b.id AS belief_id, b.confidence AS confidence
            """,
            {"proposal_id": proposal_id, "silo_id": silo_id},
        )
        if existing_belief:
            return AcceptProposalResult(
                belief_id=uuid.UUID(existing_belief[0]["belief_id"]),
                proposal_id=uuid.UUID(proposal_id),
                accepted=True,
                accepted_at=datetime.now(UTC),
                confidence=float(existing_belief[0].get("confidence", 0.8)),
            ), []
        raise InvariantViolation("INCONSISTENT_STATE", "Accepted proposal has no Belief")

    if status == "rejected":
        raise InvariantViolation(
            "PROPOSAL_REJECTED",
            "ProposedBelief was already rejected",
        )

    if status != "pending":
        raise InvariantViolation(
            "INVALID_STATUS",
            f"ProposedBelief has status {status!r}, expected 'pending'",
        )

    now = datetime.now(UTC)
    belief_id = uuid.uuid4()

    # Use existing ACCEPT_PROPOSED_BELIEF query
    accept_result = await store.execute_write(
        q.ACCEPT_PROPOSED_BELIEF,
        {
            "proposed_belief_id": proposal_id,
            "silo_id": silo_id,
            "accepted_at": now.isoformat(),
            "belief_id": str(belief_id),
            "override_confidence": override_confidence,
        },
    )

    if not accept_result:
        raise InvariantViolation("ACCEPT_FAILED", "Failed to accept proposal")

    final_confidence = float(accept_result[0].get("confidence", row.get("confidence", 0.8)))

    # Store acceptance metadata
    if reason:
        await store.execute_write(
            """
            MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
            SET b.acceptance_reason = $reason, b.accepted_by = $agent_id
            """,
            {
                "belief_id": str(belief_id),
                "silo_id": silo_id,
                "reason": reason,
                "agent_id": agent_id,
            },
        )

    result = AcceptProposalResult(
        belief_id=belief_id,
        proposal_id=uuid.UUID(proposal_id),
        accepted=True,
        accepted_at=now,
        confidence=final_confidence,
    )

    proposal_content = row.get("content", "")
    if proposal_content:
        await _sync_to_postgres(belief_id, silo_id, "wisdom", proposal_content)

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type=ReactionEventType.COMPUTE_EMBEDDING,
            node_id=str(belief_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(belief_id),
            silo_id=silo_id,
            payload={"access_type": "ACCEPT"},
        ),
        ReactionEvent(
            event_type=ReactionEventType.PROPAGATE_CONFIDENCE,
            node_id=str(belief_id),
            silo_id=silo_id,
        ),
    ]

    if emit:
        for event in events:
            await emit_reaction(event)

    logger.debug(
        "accept_proposal_complete",
        belief_id=str(belief_id),
        proposal_id=proposal_id,
        silo_id=silo_id,
        agent_id=agent_id,
    )

    return result, events


async def _revise_belief_v2(
    store: HyperGraphStore,
    belief_id: str,
    silo_id: str,
    llm: LLMProvider,
    old_content: str,
    *,
    emit: bool = True,
) -> tuple[ReviseBeliefResult, list[ReactionEvent]]:
    """Inner revision logic for v2 beliefs (SYNTHESIZED_FROM edges, no cluster)."""
    from context_service.db import queries as q

    facts_result = await store.execute_query(
        q.GET_FACTS_VIA_SYNTHESIZED_FROM,
        {
            "belief_id": belief_id,
            "silo_id": silo_id,
        },
    )
    facts = list(facts_result) if facts_result else []
    fact_count = len(facts)

    if fact_count < SYNTHESIS_THRESHOLD:
        await store.execute_write(
            q.UPDATE_BELIEF_AFTER_REVISION,
            {
                "belief_id": belief_id,
                "silo_id": silo_id,
                "synthesis_state": SynthesisState.INVALIDATED.value,
            },
        )
        return ReviseBeliefResult(
            new_belief_id=None,
            old_belief_id=uuid.UUID(belief_id),
            content_changed=False,
            invalidated=True,
        ), []

    confidences = [float(f.get("confidence", 0.8)) for f in facts]
    aggregate_confidence = noisy_or_aggregate(confidences)

    if aggregate_confidence < SYNTHESIS_CONFIDENCE_THRESHOLD:
        await store.execute_write(
            q.UPDATE_BELIEF_AFTER_REVISION,
            {
                "belief_id": belief_id,
                "silo_id": silo_id,
                "synthesis_state": SynthesisState.INVALIDATED.value,
            },
        )
        return ReviseBeliefResult(
            new_belief_id=None,
            old_belief_id=uuid.UUID(belief_id),
            content_changed=False,
            invalidated=True,
        ), []

    synthesis_result = await llm_synthesize(llm, facts, 30.0, previous_belief=old_content)

    if not synthesis_result.success:
        await store.execute_write(
            q.UPDATE_BELIEF_AFTER_REVISION,
            {
                "belief_id": belief_id,
                "silo_id": silo_id,
                "synthesis_state": SynthesisState.STALE.value,
            },
        )
        return ReviseBeliefResult(
            new_belief_id=None,
            old_belief_id=uuid.UUID(belief_id),
            content_changed=False,
        ), []

    new_content = synthesis_result.content or ""
    if new_content.strip() == old_content.strip():
        await store.execute_write(
            q.UPDATE_BELIEF_AFTER_REVISION,
            {
                "belief_id": belief_id,
                "silo_id": silo_id,
                "synthesis_state": SynthesisState.FRESH.value,
            },
        )
        return ReviseBeliefResult(
            new_belief_id=None,
            old_belief_id=uuid.UUID(belief_id),
            content_changed=False,
        ), []

    new_belief_id = uuid.uuid4()
    created_at = datetime.now(UTC)
    props: dict[str, Any] = {
        "layer": "wisdom",
        "type": "belief",
        "state": NodeState.ACTIVE.value,
        "synthesis_state": SynthesisState.FRESH.value,
        "confidence": aggregate_confidence,
        "source_cluster_id": None,
    }
    fact_ids = [f["fact_id"] for f in facts]

    await store.execute_write(
        q.CREATE_BELIEF_WITH_SYNTHESIZED_FROM,
        {
            "id": str(new_belief_id),
            "silo_id": silo_id,
            "content": new_content,
            "created_at": created_at.isoformat(),
            "props": props,
            "fact_ids": fact_ids,
        },
    )

    await _create_supersedes_edge(
        store, str(new_belief_id), belief_id, silo_id, SupersedeReason.EVIDENCE_SHIFT
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type=ReactionEventType.COMPUTE_EMBEDDING,
            node_id=str(new_belief_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(new_belief_id),
            silo_id=silo_id,
            payload={"access_type": "SYNTHESIS"},
        ),
    ]

    if emit:
        for event in events:
            await emit_reaction(event)

    logger.debug(
        "revise_belief_complete",
        new_belief_id=str(new_belief_id),
        old_belief_id=belief_id,
    )

    return ReviseBeliefResult(
        new_belief_id=new_belief_id,
        old_belief_id=uuid.UUID(belief_id),
        content_changed=True,
    ), events


async def _revise_belief_v1(
    store: HyperGraphStore,
    belief_id: str,
    silo_id: str,
    llm: LLMProvider,
    old_content: str,
    cluster_id: str,
    *,
    emit: bool = True,
) -> tuple[ReviseBeliefResult, list[ReactionEvent]]:
    """Inner revision logic for v1 beliefs (cluster-based, legacy path)."""
    from context_service.db import queries as q

    await store.execute_query(
        q.GET_CLUSTER_FOR_SYNTHESIS,
        {
            "cluster_id": cluster_id,
            "silo_id": silo_id,
        },
    )

    try:
        facts_result = await store.execute_query(
            q.GET_FACTS_IN_CLUSTER,
            {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
            },
        )
        facts = list(facts_result) if facts_result else []
        fact_count = len(facts)

        if fact_count < SYNTHESIS_THRESHOLD:
            await store.execute_write(
                q.UPDATE_BELIEF_AFTER_REVISION,
                {
                    "belief_id": belief_id,
                    "silo_id": silo_id,
                    "synthesis_state": SynthesisState.INVALIDATED.value,
                },
            )
            await store.execute_write(
                q.RELEASE_CLUSTER_LOCK,
                {
                    "cluster_id": cluster_id,
                    "silo_id": silo_id,
                    "state": ClusterState.SPARSE.value,
                },
            )
            return ReviseBeliefResult(
                new_belief_id=None,
                old_belief_id=uuid.UUID(belief_id),
                content_changed=False,
                invalidated=True,
            ), []

        confidences = [float(f.get("confidence", 0.8)) for f in facts]
        aggregate_confidence = noisy_or_aggregate(confidences)

        if aggregate_confidence < SYNTHESIS_CONFIDENCE_THRESHOLD:
            await store.execute_write(
                q.UPDATE_BELIEF_AFTER_REVISION,
                {
                    "belief_id": belief_id,
                    "silo_id": silo_id,
                    "synthesis_state": SynthesisState.INVALIDATED.value,
                },
            )
            await store.execute_write(
                q.RELEASE_CLUSTER_LOCK,
                {
                    "cluster_id": cluster_id,
                    "silo_id": silo_id,
                    "state": ClusterState.READY.value,
                },
            )
            return ReviseBeliefResult(
                new_belief_id=None,
                old_belief_id=uuid.UUID(belief_id),
                content_changed=False,
                invalidated=True,
            ), []

        synthesis_result = await llm_synthesize(llm, facts, 30.0, previous_belief=old_content)

        if not synthesis_result.success:
            await store.execute_write(
                q.UPDATE_BELIEF_AFTER_REVISION,
                {
                    "belief_id": belief_id,
                    "silo_id": silo_id,
                    "synthesis_state": SynthesisState.STALE.value,
                },
            )
            await store.execute_write(
                q.RELEASE_CLUSTER_LOCK,
                {
                    "cluster_id": cluster_id,
                    "silo_id": silo_id,
                    "state": ClusterState.STALE.value,
                },
            )
            return ReviseBeliefResult(
                new_belief_id=None,
                old_belief_id=uuid.UUID(belief_id),
                content_changed=False,
            ), []

        new_content = synthesis_result.content or ""
        if new_content.strip() == old_content.strip():
            await store.execute_write(
                q.UPDATE_BELIEF_AFTER_REVISION,
                {
                    "belief_id": belief_id,
                    "silo_id": silo_id,
                    "synthesis_state": SynthesisState.FRESH.value,
                },
            )
            await store.execute_write(
                q.RELEASE_CLUSTER_LOCK,
                {
                    "cluster_id": cluster_id,
                    "silo_id": silo_id,
                    "state": ClusterState.SYNTHESIZED.value,
                },
            )
            return ReviseBeliefResult(
                new_belief_id=None,
                old_belief_id=uuid.UUID(belief_id),
                content_changed=False,
            ), []

        new_belief_id = uuid.uuid4()
        created_at = datetime.now(UTC)
        props: dict[str, Any] = {
            "layer": "wisdom",
            "type": "belief",
            "state": NodeState.ACTIVE.value,
            "synthesis_state": SynthesisState.FRESH.value,
            "confidence": aggregate_confidence,
            "source_cluster_id": cluster_id,
        }
        fact_ids = [f["fact_id"] for f in facts]

        await store.execute_write(
            q.CREATE_BELIEF_WITH_SYNTHESIZED_FROM,
            {
                "id": str(new_belief_id),
                "silo_id": silo_id,
                "content": new_content,
                "created_at": created_at.isoformat(),
                "props": props,
                "fact_ids": fact_ids,
            },
        )

        await _create_supersedes_edge(
            store, str(new_belief_id), belief_id, silo_id, SupersedeReason.EVIDENCE_SHIFT
        )

        await store.execute_write(
            q.UPDATE_CLUSTER_AFTER_SYNTHESIS,
            {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "state": ClusterState.SYNTHESIZED.value,
                "belief_id": str(new_belief_id),
                "synthesized_at": created_at.isoformat(),
            },
        )

        events: list[ReactionEvent] = [
            ReactionEvent(
                event_type=ReactionEventType.COMPUTE_EMBEDDING,
                node_id=str(new_belief_id),
                silo_id=silo_id,
            ),
            ReactionEvent(
                event_type=ReactionEventType.UPDATE_HEAT,
                node_id=str(new_belief_id),
                silo_id=silo_id,
                payload={"access_type": "SYNTHESIS"},
            ),
        ]

        if emit:
            for event in events:
                await emit_reaction(event)

        logger.debug(
            "revise_belief_complete",
            new_belief_id=str(new_belief_id),
            old_belief_id=belief_id,
        )

        return ReviseBeliefResult(
            new_belief_id=new_belief_id,
            old_belief_id=uuid.UUID(belief_id),
            content_changed=True,
        ), events

    except Exception:
        await store.execute_write(
            q.RELEASE_CLUSTER_LOCK,
            {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "state": ClusterState.STALE.value,
            },
        )
        raise


async def revise_belief(
    store: HyperGraphStore,
    belief_id: str,
    silo_id: str,
    llm: LLMProvider,
    _embedder: EmbeddingService,
    *,
    emit: bool = True,
) -> tuple[ReviseBeliefResult, list[ReactionEvent]]:
    """Re-synthesize a stale belief (TX5)."""
    from context_service.db import queries as q

    # Get belief and validate
    belief_result = await store.execute_query(
        q.GET_BELIEF_FOR_REVISION,
        {
            "belief_id": belief_id,
            "silo_id": silo_id,
        },
    )

    if not belief_result:
        raise InvariantViolation("BELIEF_NOT_FOUND", "Belief not found")

    belief = belief_result[0]
    if belief.get("state") != NodeState.ACTIVE.value:
        raise InvariantViolation("BELIEF_NOT_ACTIVE", "Belief is not active")

    if belief.get("synthesis_state") != SynthesisState.STALE.value:
        raise InvariantViolation(
            "BELIEF_NOT_STALE",
            f"Belief synthesis_state is {belief.get('synthesis_state')}, not STALE",
        )

    if belief.get("revision_in_progress"):
        raise InvariantViolation("REVISION_IN_PROGRESS", "Revision already in progress")

    cluster_id = belief.get("source_cluster_id")
    old_content = belief.get("content", "")
    is_v2 = cluster_id is None

    # Mark revision in progress
    await store.execute_write(
        q.MARK_BELIEF_REVISION_IN_PROGRESS,
        {
            "belief_id": belief_id,
            "silo_id": silo_id,
        },
    )

    try:
        if is_v2:
            return await _revise_belief_v2(
                store=store,
                belief_id=belief_id,
                silo_id=silo_id,
                llm=llm,
                old_content=old_content,
                emit=emit,
            )
        else:
            return await _revise_belief_v1(
                store=store,
                belief_id=belief_id,
                silo_id=silo_id,
                llm=llm,
                old_content=old_content,
                cluster_id=str(cluster_id),
                emit=emit,
            )

    except Exception:
        await store.execute_write(
            q.UPDATE_BELIEF_AFTER_REVISION,
            {
                "belief_id": belief_id,
                "silo_id": silo_id,
                "synthesis_state": SynthesisState.STALE.value,
            },
        )
        raise


async def _validate_evidence_nodes(
    store: HyperGraphStore,
    node_ids: list[str],
    silo_id: str,
) -> dict[str, Any]:
    """Validate evidence nodes exist, are in same silo, and include Memory layer."""
    if not node_ids:
        return {"error": None, "has_memory_layer": False}

    cypher = """
    UNWIND $node_ids AS nid
    MATCH (n {id: nid})
    RETURN n.id AS id, n.silo_id AS silo_id, n.properties.layer AS layer,
           n.properties.state AS state
    """
    results = await store.execute_query(cypher, {"node_ids": node_ids})

    found_ids = {r["id"] for r in results}
    missing = set(node_ids) - found_ids
    if missing:
        return {
            "error": "EVIDENCE_NOT_FOUND",
            "message": f"Evidence nodes not found: {missing}",
            "details": {"missing_ids": list(missing)},
        }

    cross_silo = [r for r in results if r.get("silo_id") != silo_id]
    if cross_silo:
        return {
            "error": "CROSS_SILO_VIOLATION",
            "message": f"Evidence nodes in different silo: {[r['id'] for r in cross_silo]}",
        }

    tombstoned = [r for r in results if r.get("state") == NodeState.TOMBSTONED.value]
    if tombstoned:
        return {
            "error": "EVIDENCE_TOMBSTONED",
            "message": f"Evidence nodes are tombstoned: {[r['id'] for r in tombstoned]}",
        }

    has_memory = any(r.get("layer") == "memory" for r in results)
    return {"error": None, "has_memory_layer": has_memory}


async def _create_derived_from_edges(
    store: HyperGraphStore,
    claim_id: str,
    evidence_ids: list[str],
    silo_id: str,
) -> None:
    """Create DERIVED_FROM edges from claim to evidence nodes."""
    cypher = """
    UNWIND $evidence_ids AS ev_id
    MATCH (c {id: $claim_id, silo_id: $silo_id})
    MATCH (e {id: ev_id, silo_id: $silo_id})
    MERGE (c)-[:DERIVED_FROM]->(e)
    """
    await store.execute_write(
        cypher,
        {"claim_id": claim_id, "evidence_ids": evidence_ids, "silo_id": silo_id},
    )


async def _validate_supersession(
    store: HyperGraphStore,
    winner_id: str,
    loser_id: str,
    silo_id: str,
) -> dict[str, Any]:
    """Validate supersession: both exist, same silo, correct states, no cycle."""
    cypher = """
    MATCH (w {id: $winner_id})
    MATCH (l {id: $loser_id})
    RETURN w.silo_id AS winner_silo, l.silo_id AS loser_silo,
           w.properties.state AS winner_state, l.properties.state AS loser_state
    """
    results = await store.execute_query(cypher, {"winner_id": winner_id, "loser_id": loser_id})

    if not results:
        return {"error": "NODE_NOT_FOUND", "message": "Winner or loser node not found"}

    row = results[0]
    if row["winner_silo"] != silo_id or row["loser_silo"] != silo_id:
        return {
            "error": "CROSS_SILO_VIOLATION",
            "winner_silo": row["winner_silo"],
            "loser_silo": row["loser_silo"],
        }

    if row["winner_state"] != NodeState.ACTIVE.value:
        return {"error": "WINNER_NOT_ACTIVE", "message": "Winner must be ACTIVE"}

    if row["loser_state"] != NodeState.ACTIVE.value:
        return {"error": "LOSER_NOT_ACTIVE", "message": "Loser must be ACTIVE"}

    if await _would_create_cycle(store, winner_id, loser_id, "SUPERSEDES", silo_id):
        return {"error": "WOULD_CREATE_CYCLE"}

    return {"error": None}


async def _would_create_cycle(
    store: HyperGraphStore,
    source_id: str,
    target_id: str,
    edge_type: str,
    silo_id: str,
) -> bool:
    """Check if adding edge would create a cycle (BFS from target to source)."""
    cypher = f"""
    MATCH path = (target {{id: $target_id, silo_id: $silo_id}})-[:{edge_type}*]->(source {{id: $source_id, silo_id: $silo_id}})
    RETURN count(path) > 0 AS would_cycle
    """
    results = await store.execute_query(
        cypher, {"source_id": source_id, "target_id": target_id, "silo_id": silo_id}
    )
    return results[0]["would_cycle"] if results else False


async def would_create_cycle(
    store: HyperGraphStore,
    source_id: str,
    target_id: str,
    silo_id: str,
    edge_type: str = "SUPERSEDES",
) -> bool:
    """Check if adding edge would create cycle in SUPERSEDES graph.

    Per brain-transactions-pseudocode.md WOULD_CREATE_CYCLE.
    Only checks SUPERSEDES cycles (INV4).
    """
    if edge_type != "SUPERSEDES":
        return False

    from context_service.db import queries as q

    # Check if path exists from target to source (would create cycle if we add source->target)
    result = await store.execute_query(
        q.CHECK_CYCLE_PATH,
        {
            "source_id": target_id,  # Start from target
            "target_id": source_id,  # See if we can reach source
            "silo_id": silo_id,
        },
    )

    return bool(result and result[0].get("would_cycle"))


async def _create_supersedes_edge(
    store: HyperGraphStore,
    winner_id: str,
    loser_id: str,
    silo_id: str,
    reason: SupersedeReason,
) -> None:
    """Create SUPERSEDES edge and update loser state."""
    cypher = """
    MATCH (w {id: $winner_id, silo_id: $silo_id})
    MATCH (l {id: $loser_id, silo_id: $silo_id})
    SET l.properties.state = $superseded_state,
        l.valid_to = $valid_to
    CREATE (w)-[:SUPERSEDES {reason: $reason, created_at: $created_at}]->(l)
    """
    await store.execute_write(
        cypher,
        {
            "winner_id": winner_id,
            "loser_id": loser_id,
            "silo_id": silo_id,
            "superseded_state": NodeState.SUPERSEDED.value,
            "valid_to": datetime.now(UTC).isoformat(),
            "reason": reason.value,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )

    await _sync_postgres_state(loser_id, silo_id, NodeState.SUPERSEDED.value)


async def check_corroboration(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    threshold: int = PROMOTION_THRESHOLD,
) -> tuple[int, bool]:
    """Atomic corroboration check using single query.

    Finds all claims with same (subject, predicate, object), counts distinct
    evidence sources, updates corroboration_count on all, returns result.

    Args:
        store: Graph store instance.
        node_id: The claim node to check.
        silo_id: Tenant isolation ID.
        threshold: Promotion threshold (default: 3).

    Returns:
        Tuple of (distinct_source_count, should_promote).
    """
    # Count distinct evidence URIs from properties.evidence lists across matching claims
    cypher = """
    MATCH (new:Claim {id: $node_id, silo_id: $silo_id})
    OPTIONAL MATCH (c:Claim {silo_id: $silo_id})
    WHERE c.properties.subject = new.properties.subject
      AND c.properties.predicate = new.properties.predicate
      AND c.properties.object = new.properties.object
      AND c.properties.state = 'ACTIVE'
    WITH new, collect(c) AS claims
    WITH new, CASE WHEN size(claims) = 0 THEN [new] ELSE claims END AS claims
    UNWIND claims AS claim
    UNWIND claim.properties.evidence AS ev
    WITH new, collect(DISTINCT ev) AS all_evidence
    RETURN size(all_evidence) AS count, size(all_evidence) >= $threshold AS should_promote
    """

    results = await store.execute_query(
        cypher,
        {"node_id": node_id, "silo_id": silo_id, "threshold": threshold},
    )

    if not results:
        return 1, False

    row = results[0]
    return row.get("count", 1), row.get("should_promote", False)


async def check_semantic_corroboration(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    embedding_service: EmbeddingService,
    threshold: int = PROMOTION_THRESHOLD,
    similarity_threshold: float = SPO_SIMILARITY_THRESHOLD,
) -> tuple[int, bool]:
    """Semantic corroboration check using embedding similarity.

    Instead of exact SPO string matching, this computes cosine similarity
    between SPO embeddings to find semantically equivalent claims.

    Args:
        store: Graph store instance.
        node_id: The claim node to check.
        silo_id: Tenant isolation ID.
        embedding_service: Service for computing embeddings.
        threshold: Promotion threshold (default: 3).
        similarity_threshold: Cosine similarity threshold for SPO matching.

    Returns:
        Tuple of (distinct_source_count, should_promote).
    """
    import numpy as np

    # Get the new claim's SPO
    new_claim_query = """
    MATCH (c:Claim {id: $node_id, silo_id: $silo_id})
    RETURN c.properties.subject AS subject,
           c.properties.predicate AS predicate,
           c.properties.object AS object,
           c.properties.evidence AS evidence
    """
    new_result = await store.execute_query(
        new_claim_query, {"node_id": node_id, "silo_id": silo_id}
    )
    if not new_result:
        return 1, False

    new_claim = new_result[0]
    new_subject = new_claim.get("subject")
    new_predicate = new_claim.get("predicate")
    new_object = new_claim.get("object")
    new_evidence = new_claim.get("evidence") or []

    # If no SPO, fall back to just counting own evidence
    if not all([new_subject, new_predicate, new_object]):
        return len(new_evidence), len(new_evidence) >= threshold

    # Compute embedding for new claim's SPO
    new_spo_text = f"{new_subject} {new_predicate} {new_object}"
    new_embedding = await embedding_service.embed_single(new_spo_text)
    new_vec = np.array(new_embedding)
    new_norm = np.linalg.norm(new_vec)
    if new_norm > 0:
        new_vec = new_vec / new_norm

    # Fetch all active claims with SPO in the silo
    candidates_query = """
    MATCH (c:Claim {silo_id: $silo_id})
    WHERE c.properties.state = 'ACTIVE'
      AND c.properties.subject IS NOT NULL
      AND c.properties.predicate IS NOT NULL
      AND c.properties.object IS NOT NULL
    RETURN c.id AS id,
           c.properties.subject AS subject,
           c.properties.predicate AS predicate,
           c.properties.object AS object,
           c.properties.evidence AS evidence
    """
    candidates = await store.execute_query(candidates_query, {"silo_id": silo_id})

    if not candidates:
        return len(new_evidence), len(new_evidence) >= threshold

    # Batch embed all candidate SPO texts
    spo_texts = [
        f"{c.get('subject')} {c.get('predicate')} {c.get('object')}"
        for c in candidates
    ]
    candidate_embeddings = await embedding_service.embed(spo_texts)

    # Find semantically similar claims
    evidence_set: set[str] = set()
    for i, c in enumerate(candidates):
        cand_vec = np.array(candidate_embeddings[i])
        cand_norm = np.linalg.norm(cand_vec)
        if cand_norm > 0:
            cand_vec = cand_vec / cand_norm

        similarity = float(np.dot(new_vec, cand_vec))
        if similarity >= similarity_threshold:
            # Include this claim's evidence
            cand_evidence = c.get("evidence") or []
            evidence_set.update(cand_evidence)

    corroboration_count = len(evidence_set)
    should_promote = corroboration_count >= threshold

    logger.debug(
        "semantic_corroboration_check",
        node_id=node_id,
        candidates_checked=len(candidates),
        matches_found=len(evidence_set),
        corroboration_count=corroboration_count,
        should_promote=should_promote,
    )

    return corroboration_count, should_promote


async def _check_corroboration(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    embedding_service: EmbeddingService | None = None,
) -> tuple[int, bool]:
    """Check corroboration count and whether promotion threshold is met (TX18).

    If embedding_service is provided, uses semantic SPO matching.
    Otherwise falls back to exact string matching.

    Returns (corroboration_count, should_promote).
    """
    if embedding_service is not None:
        return await check_semantic_corroboration(
            store, node_id, silo_id, embedding_service
        )
    return await check_corroboration(store, node_id, silo_id)


async def _validate_link(
    store: HyperGraphStore,
    source_id: str,
    target_id: str,
    edge_type: LinkType,
    silo_id: str,
) -> dict[str, Any]:
    """Validate link: both exist, same silo, no duplicate, no cycle for hierarchical."""
    cypher = """
    MATCH (s {id: $source_id})
    MATCH (t {id: $target_id})
    RETURN s.silo_id AS source_silo, t.silo_id AS target_silo,
           s.properties.state AS source_state, t.properties.state AS target_state
    """
    results = await store.execute_query(cypher, {"source_id": source_id, "target_id": target_id})

    if not results:
        return {"error": "NODE_NOT_FOUND", "message": "Source or target node not found"}

    row = results[0]
    if row["source_silo"] != silo_id or row["target_silo"] != silo_id:
        return {
            "error": "CROSS_SILO_VIOLATION",
            "source_silo": row["source_silo"],
            "target_silo": row["target_silo"],
        }

    if (
        row["source_state"] == NodeState.DELETED.value
        or row["target_state"] == NodeState.DELETED.value
    ):
        return {"error": "NODE_DELETED", "message": "Cannot link to deleted nodes"}

    dup_check = f"""
    MATCH (s {{id: $source_id}})-[e:{edge_type.value}]->(t {{id: $target_id}})
    RETURN e.id AS existing_id
    """
    dup_results = await store.execute_query(
        dup_check, {"source_id": source_id, "target_id": target_id}
    )
    if dup_results:
        return {"error": "DUPLICATE_EDGE", "existing_id": dup_results[0].get("existing_id")}

    if edge_type in HIERARCHICAL_EDGE_TYPES and await _would_create_cycle(
        store, source_id, target_id, edge_type.value, silo_id
    ):
        return {"error": "WOULD_CREATE_CYCLE"}

    return {"error": None}


async def detect_spo_conflict(
    store: HyperGraphStore,
    new_node_id: str,
    subject: str | None,
    predicate: str | None,
    object_value: str | None,
    silo_id: str,
) -> list[ReactionEvent]:
    """Detect and flag structural conflicts with existing claims.

    Creates bidirectional CONTRADICTS edges and emits ConflictDetected events.
    Only runs when all three SPO components are provided.

    This is the public API for conflict detection - call after storing a claim
    to check for contradicting claims with the same subject+predicate but
    different object value.
    """
    if not all([subject, predicate, object_value]):
        return []

    # Find conflicting claims (same subject+predicate, different object)
    cypher = """
    MATCH (c:Claim {silo_id: $silo_id})
    WHERE c.properties.subject = $subject
      AND c.properties.predicate = $predicate
      AND c.properties.object <> $object
      AND c.properties.state = 'ACTIVE'
      AND c.id <> $new_node_id
    RETURN c.id AS id
    """

    conflicts = await store.execute_query(
        cypher,
        {
            "silo_id": silo_id,
            "subject": subject,
            "predicate": predicate,
            "object": object_value,
            "new_node_id": new_node_id,
        },
    )

    if not conflicts:
        return []

    events: list[ReactionEvent] = []
    detected_at = datetime.now(UTC).isoformat()

    for conflict in conflicts:
        existing_id = conflict["id"]

        # Create bidirectional CONTRADICTS edges (INV8)
        await _create_bidirectional_contradicts(
            store, new_node_id, existing_id, silo_id, detected_at
        )

        # Update conflict_status on both nodes
        await _set_conflict_status(
            store, new_node_id, existing_id, silo_id, ConflictStatus.UNRESOLVED
        )

        events.append(
            ReactionEvent(
                event_type=ReactionEventType.CONFLICT_DETECTED,
                node_id=new_node_id,
                silo_id=silo_id,
                payload={
                    "node_a": new_node_id,
                    "node_b": existing_id,
                    "conflict_type": "structural",
                    "detected_at": detected_at,
                },
            )
        )

    return events


async def _create_bidirectional_contradicts(
    store: HyperGraphStore,
    node_a: str,
    node_b: str,
    silo_id: str,
    detected_at: str,
) -> None:
    """Create bidirectional CONTRADICTS edges (A->B and B->A)."""
    cypher = """
    MATCH (a {id: $node_a, silo_id: $silo_id})
    MATCH (b {id: $node_b, silo_id: $silo_id})
    MERGE (a)-[:CONTRADICTS {weight: 1.0, detected_at: $detected_at, conflict_type: 'structural'}]->(b)
    MERGE (b)-[:CONTRADICTS {weight: 1.0, detected_at: $detected_at, conflict_type: 'structural'}]->(a)
    """
    await store.execute_write(
        cypher,
        {"node_a": node_a, "node_b": node_b, "silo_id": silo_id, "detected_at": detected_at},
    )


async def _set_conflict_status(
    store: HyperGraphStore,
    node_a: str,
    node_b: str,
    silo_id: str,
    status: ConflictStatus,
) -> None:
    """Set conflict_status on both nodes."""
    cypher = """
    MATCH (n {silo_id: $silo_id})
    WHERE n.id IN $node_ids
    SET n.properties.conflict_status = $status
    """
    await store.execute_write(
        cypher,
        {"node_ids": [node_a, node_b], "silo_id": silo_id, "status": status.value},
    )


async def _run_incremental_propagation(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
) -> int:
    """Run depth-limited confidence propagation after SUPPORTS/CONTRADICTS edge creation.

    Fetches local neighborhood (depth 2), runs propagation, updates affected nodes.
    Target: <50ms for write-time budget.

    Returns:
        Number of nodes updated.
    """
    from context_service.db import queries as q

    results = await store.execute_query(
        q.GET_LOCAL_GRAPH_FOR_PROPAGATION,
        {"node_id": node_id, "silo_id": silo_id},
    )

    if not results:
        return 0

    row = results[0]
    nodes = row.get("nodes", [])
    supports = row.get("supports", [])
    contradictions = row.get("contradictions", [])

    if not nodes:
        return 0

    node_ids = [n["id"] for n in nodes if n.get("id")]
    credibility_scores = {n["id"]: n.get("credibility", 0.5) for n in nodes if n.get("id")}

    support_edges = [
        (e["source"], e["target"], e.get("weight", 1.0))
        for e in supports
        if e.get("source") and e.get("target")
    ]
    contra_edges = [
        (e["source"], e["target"], e.get("weight", 1.0))
        for e in contradictions
        if e.get("source") and e.get("target")
    ]

    if not support_edges and not contra_edges:
        return 0

    updated = propagate_incremental(
        target_id=node_id,
        node_ids=node_ids,
        credibility_scores=credibility_scores,
        support_edges=support_edges,
        contradiction_edges=contra_edges,
        depth=2,
    )

    updates = [{"node_id": nid, "confidence": conf} for nid, conf in updated.items()]

    if updates:
        await store.execute_write(
            q.UPDATE_PROPAGATED_CONFIDENCE,
            {
                "updates": updates,
                "silo_id": silo_id,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

    logger.debug(
        "incremental_propagation_complete",
        node_id=node_id,
        updated_count=len(updates),
    )

    return len(updates)


async def cascade_staleness(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    depth: int = 1,
    visited: set[str] | None = None,
) -> int:
    """CASCADE_STALENESS: Propagate staleness to dependent nodes.

    Depth-limited (MAX_CASCADE_DEPTH). Sync for depth 1, async events for deeper.
    Returns count of nodes marked stale.
    """
    from context_service.db import queries as q

    if depth > MAX_CASCADE_DEPTH:
        logger.warning("cascade_depth_limit_reached", node_id=node_id, depth=depth)
        return 0

    if visited is None:
        visited = set()

    if node_id in visited:
        return 0

    visited.add(node_id)

    # Find dependents
    dependents = await store.execute_query(
        q.GET_DEPENDENTS_FOR_CASCADE,
        {
            "node_id": node_id,
            "silo_id": silo_id,
        },
    )

    cascade_count = 0

    for dep in dependents:
        dep_id = dep["id"]
        layer = dep.get("layer")

        if layer == "wisdom":
            # Mark belief stale
            await store.execute_write(
                q.MARK_BELIEF_STALE_FOR_CASCADE,
                {
                    "node_id": dep_id,
                    "silo_id": silo_id,
                },
            )
            cascade_count += 1
        else:
            # Recurse into non-wisdom dependents (sync for depth 1, would be async for deeper in production)
            if depth == 1:
                cascade_count += await cascade_staleness(store, dep_id, silo_id, depth + 1, visited)

    logger.debug(
        "cascade_staleness_complete", node_id=node_id, cascade_count=cascade_count, depth=depth
    )

    return cascade_count


async def forget(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    agent_id: str,
    *,
    reason: str | None = None,
    cascade: bool = False,
    emit: bool = True,
) -> tuple[ForgetResult, list[ReactionEvent]]:
    """Soft-delete a node with cancel window (TX15).

    Per brain-transactions-pseudocode.md:
    - Preconditions: node exists, state is ACTIVE or SUPERSEDED
    - Sets state to TOMBSTONED, records cancel_window_expires
    - Optional cascade triggers CASCADE_STALENESS on dependents
    """
    from context_service.db import queries as q

    # Validate node exists and is not already tombstoned
    node_result = await store.execute_query(
        q.GET_NODE_FOR_FORGET,
        {
            "node_id": node_id,
            "silo_id": silo_id,
        },
    )

    if not node_result:
        raise InvariantViolation("NODE_NOT_FOUND", "Node not found")

    node = node_result[0]
    state = node.get("state")

    if state == NodeState.TOMBSTONED.value:
        raise InvariantViolation("ALREADY_TOMBSTONED", "Node is already tombstoned")

    if state == NodeState.DELETED.value:
        raise InvariantViolation("ALREADY_DELETED", "Node is already deleted")

    if state not in (NodeState.ACTIVE.value, NodeState.SUPERSEDED.value):
        raise InvariantViolation("INVALID_STATE", f"Cannot forget node in state {state}")

    now = datetime.now(UTC)
    cancel_window_expires = now + timedelta(seconds=CANCEL_WINDOW_DURATION_SECONDS)

    # Tombstone the node
    await store.execute_write(
        q.TOMBSTONE_NODE,
        {
            "node_id": node_id,
            "silo_id": silo_id,
            "tombstoned_at": now.isoformat(),
            "forget_requested_at": now.isoformat(),
            "agent_id": agent_id,
            "reason": reason,
            "cancel_window_expires": cancel_window_expires.isoformat(),
        },
    )

    cascade_count = 0
    events: list[ReactionEvent] = []

    # TX11: Emit CHAIN_TOMBSTONED only for ReasoningChain nodes
    # to trigger consensus Fact staleness cascade
    if node.get("node_type") == "ReasoningChain":
        events.append(
            ReactionEvent(
                event_type=ReactionEventType.CHAIN_TOMBSTONED,
                node_id=node_id,
                silo_id=silo_id,
                payload={"reason": reason},
            )
        )

    if cascade:
        # Trigger staleness cascade
        cascade_count = await cascade_staleness(store, node_id, silo_id, depth=1)
        events.append(
            ReactionEvent(
                event_type=ReactionEventType.CASCADE_STALENESS_COMPLETE,
                node_id=node_id,
                silo_id=silo_id,
                payload={"cascade_count": cascade_count},
            )
        )

    if emit:
        for event in events:
            await emit_reaction(event)

    result = ForgetResult(
        node_id=uuid.UUID(node_id),
        state=NodeState.TOMBSTONED,
        tombstoned_at=now,
        cancel_window_expires=cancel_window_expires,
        cascade_count=cascade_count,
    )

    logger.debug("forget_complete", node_id=node_id, silo_id=silo_id, cascade_count=cascade_count)

    return result, events


async def cancel_forget(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    agent_id: str,
) -> CancelForgetResult:
    """Restore a tombstoned node within cancel window (TX16)."""
    from context_service.db import queries as q

    node_result = await store.execute_query(
        q.GET_NODE_FOR_FORGET,
        {
            "node_id": node_id,
            "silo_id": silo_id,
        },
    )

    if not node_result:
        raise InvariantViolation("NODE_NOT_FOUND", "Node not found")

    node = node_result[0]
    state = node.get("state")

    if state != NodeState.TOMBSTONED.value:
        raise InvariantViolation("NOT_TOMBSTONED", f"Node is not tombstoned (state: {state})")

    cancel_expires = node.get("cancel_window_expires")
    if cancel_expires:
        expires_dt = datetime.fromisoformat(cancel_expires.replace("Z", "+00:00"))
        if datetime.now(UTC) > expires_dt:
            raise InvariantViolation("CANCEL_WINDOW_EXPIRED", "Cancel window has expired")

    now = datetime.now(UTC)

    restore_result = await store.execute_write(
        q.RESTORE_TOMBSTONED_NODE,
        {
            "node_id": node_id,
            "silo_id": silo_id,
            "now": now.isoformat(),
            "restored_at": now.isoformat(),
            "agent_id": agent_id,
        },
    )

    previous_state_str = (
        restore_result[0].get("previous_state", "ACTIVE") if restore_result else "ACTIVE"
    )
    previous_state = NodeState(previous_state_str)

    logger.debug("cancel_forget_complete", node_id=node_id, silo_id=silo_id)

    return CancelForgetResult(
        node_id=uuid.UUID(node_id),
        restored_at=now,
        previous_state=previous_state,
    )


async def hard_delete(
    store: HyperGraphStore,
    silo_id: str,
    batch_size: int = 100,
) -> HardDeleteResult:
    """Permanently remove tombstoned nodes past cancel window (TX10).

    Called by scheduled GC job, not by agents directly.
    """
    from context_service.db import queries as q

    now = datetime.now(UTC)

    # Find tombstoned nodes past cancel window
    candidates = await store.execute_query(
        q.GET_TOMBSTONED_FOR_GC,
        {
            "silo_id": silo_id,
            "now": now.isoformat(),
            "batch_size": batch_size,
        },
    )

    deleted_ids: list[str] = []
    skipped_count = 0

    for candidate in candidates:
        node_id = candidate["id"]

        try:
            # Delete edges first
            await store.execute_write(
                q.DELETE_EDGES_FOR_NODE,
                {
                    "node_id": node_id,
                    "silo_id": silo_id,
                },
            )

            # Delete node
            await store.execute_write(
                q.HARD_DELETE_NODE,
                {
                    "node_id": node_id,
                    "silo_id": silo_id,
                },
            )

            deleted_ids.append(node_id)

        except Exception as e:
            logger.warning("hard_delete_failed", node_id=node_id, error=str(e))
            skipped_count += 1

    logger.info(
        "hard_delete_complete",
        silo_id=silo_id,
        deleted_count=len(deleted_ids),
        skipped_count=skipped_count,
    )

    return HardDeleteResult(
        deleted_count=len(deleted_ids),
        skipped_count=skipped_count,
        deleted_ids=deleted_ids,
    )


async def promote(
    store: HyperGraphStore,
    claim_id: str,
    silo_id: str,
    *,
    corroboration_count: int | None = None,
    emit: bool = True,
) -> tuple[PromoteResult, list[ReactionEvent]]:
    """Promote Claim to Fact when corroboration threshold met (TX18).

    Per brain-transactions-pseudocode.md:
    - Preconditions: claim exists, state ACTIVE, claim_status UNPROMOTED
    - Preconditions: corroboration_count >= PROMOTION_THRESHOLD
    - Idempotent: already promoted returns success without modification
    """
    from context_service.db import queries as q

    # Fetch claim
    claim_result = await store.execute_query(
        q.GET_CLAIM_FOR_PROMOTE,
        {
            "claim_id": claim_id,
            "silo_id": silo_id,
        },
    )

    if not claim_result:
        raise InvariantViolation("CLAIM_NOT_FOUND", "Claim not found")

    claim = claim_result[0]
    state = claim.get("state")
    claim_status = claim.get("claim_status")
    current_confidence = claim.get("confidence", 0.8)

    # Use passed corroboration_count if provided, otherwise try to read from DB
    if corroboration_count is None:
        raw_corroboration = claim.get("corroboration_count")
        corroboration_count = int(raw_corroboration) if raw_corroboration is not None else 0

    if state != NodeState.ACTIVE.value:
        raise InvariantViolation("CLAIM_NOT_ACTIVE", f"Claim is not active (state: {state})")

    # Idempotent: already promoted
    if claim_status == "PROMOTED":
        return PromoteResult(
            claim_id=uuid.UUID(claim_id),
            promoted_at=datetime.now(UTC),
            new_confidence=current_confidence,
            corroboration_count=corroboration_count,
        ), []

    if corroboration_count < PROMOTION_THRESHOLD:
        raise InvariantViolation(
            "INSUFFICIENT_CORROBORATION",
            f"Corroboration count {corroboration_count} below threshold {PROMOTION_THRESHOLD}",
            count=corroboration_count,
            threshold=PROMOTION_THRESHOLD,
        )

    now = datetime.now(UTC)
    # Boost confidence based on corroboration
    new_confidence = min(
        1.0, current_confidence + 0.1 * (corroboration_count - PROMOTION_THRESHOLD + 1)
    )

    await store.execute_write(
        q.UPDATE_CLAIM_TO_PROMOTED,
        {
            "claim_id": claim_id,
            "silo_id": silo_id,
            "promoted_at": now.isoformat(),
            "new_confidence": new_confidence,
        },
    )

    result = PromoteResult(
        claim_id=uuid.UUID(claim_id),
        promoted_at=now,
        new_confidence=new_confidence,
        corroboration_count=corroboration_count,
    )

    logger.debug(
        "promote_complete",
        claim_id=claim_id,
        silo_id=silo_id,
        corroboration_count=corroboration_count,
    )

    return result, []


async def demote(
    store: HyperGraphStore,
    fact_id: str,
    silo_id: str,
    *,
    emit: bool = True,
) -> tuple[DemoteResult, list[ReactionEvent]]:
    """Demote Fact back to Claim when evidence withdrawn (TX19).

    Per brain-transactions-pseudocode.md:
    - Preconditions: fact exists, state ACTIVE, claim_status PROMOTED
    - Recounts corroboration; skips if still >= threshold
    - Idempotent: already demoted returns success without modification
    """
    from context_service.db import queries as q

    # Fetch fact
    fact_result = await store.execute_query(
        q.GET_FACT_FOR_DEMOTE,
        {
            "fact_id": fact_id,
            "silo_id": silo_id,
        },
    )

    if not fact_result:
        raise InvariantViolation("FACT_NOT_FOUND", "Fact not found")

    fact = fact_result[0]
    state = fact.get("state")
    claim_status = fact.get("claim_status")
    current_confidence = fact.get("confidence", 0.8)

    if state != NodeState.ACTIVE.value:
        raise InvariantViolation("FACT_NOT_ACTIVE", f"Fact is not active (state: {state})")

    # Idempotent: already demoted
    if claim_status != "PROMOTED":
        corroboration_count = fact.get("corroboration_count", 0)
        return DemoteResult(
            fact_id=uuid.UUID(fact_id),
            demoted_at=datetime.now(UTC),
            new_confidence=current_confidence,
            corroboration_count=corroboration_count,
        ), []

    # Recount corroboration
    recount_result = await store.execute_query(
        q.RECOUNT_CORROBORATION,
        {
            "claim_id": fact_id,
            "silo_id": silo_id,
        },
    )
    corroboration_count = recount_result[0].get("corroboration_count", 0) if recount_result else 0

    # Still corroborated - no demotion needed
    if corroboration_count >= PROMOTION_THRESHOLD:
        return DemoteResult(
            fact_id=uuid.UUID(fact_id),
            demoted_at=datetime.now(UTC),
            new_confidence=current_confidence,
            corroboration_count=corroboration_count,
        ), []

    now = datetime.now(UTC)
    # Reduce confidence without corroboration boost
    new_confidence = max(0.1, current_confidence - 0.1)

    await store.execute_write(
        q.UPDATE_FACT_TO_DEMOTED,
        {
            "fact_id": fact_id,
            "silo_id": silo_id,
            "demoted_at": now.isoformat(),
            "new_confidence": new_confidence,
        },
    )

    result = DemoteResult(
        fact_id=uuid.UUID(fact_id),
        demoted_at=now,
        new_confidence=new_confidence,
        corroboration_count=corroboration_count,
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type=ReactionEventType.CASCADE_STALENESS,
            node_id=fact_id,
            silo_id=silo_id,
            payload={"depth": 1},
        ),
    ]

    if emit:
        for event in events:
            await emit_reaction(event)

    logger.debug(
        "demote_complete",
        fact_id=fact_id,
        silo_id=silo_id,
        corroboration_count=corroboration_count,
    )

    return result, events
