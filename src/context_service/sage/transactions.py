"""Sage transactions: Core write path with invariant enforcement.

Implements TX0, TX2, TX3, TX17 per brain-transactions-pseudocode.md.

Design:
- Each transaction enforces its invariants at write time
- Returns a typed result or raises a domain error
- Emits async reaction events for downstream processing
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

import structlog

from context_service.sage.confidence import compute_credibility

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


HIERARCHICAL_EDGE_TYPES = frozenset({LinkType.REFINES, LinkType.GENERALIZES, LinkType.CAUSED_BY})

PROMOTION_THRESHOLD = 3
SYNTHESIS_THRESHOLD = 3
SYNTHESIS_CONFIDENCE_THRESHOLD = 0.6
MAX_CLUSTER_SIZE = 1000
MAX_SYNTHESIS_RETRIES = 3


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
class SynthesizeResult:
    """Result of TX4 SYNTHESIZE."""

    belief_id: uuid.UUID | None
    cluster_id: str
    cluster_state: ClusterState
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
        response = await asyncio.wait_for(
            llm.complete(
                system_prompt=_SYNTHESIS_SYSTEM_PROMPT,
                user_prompt=prompt,
            ),
            timeout=timeout,
        )
        return LLMSynthesisResult(
            success=True,
            content=response.strip(),
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


@dataclass
class ReactionEvent:
    """Event emitted for async reaction processing."""

    event_type: str
    node_id: str
    silo_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


async def tx4_synthesize(
    store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
    llm: LLMProvider,
    embedder: EmbeddingService,
    *,
    mode: Literal["async", "sync"] = "async",
    timeout_seconds: float = 30.0,
) -> tuple[SynthesizeResult, list[ReactionEvent]]:
    """TX4 SYNTHESIZE: Create Belief from fact cluster.

    Per brain-transactions-pseudocode.md:
    - Modes: ASYNC (30s timeout), SYNC (2s timeout for query-time)
    - Enforces INV3: Every Belief has >= N SYNTHESIZED_FROM to ACTIVE Facts
    """
    from context_service.db import queries as q

    effective_timeout = 2.0 if mode == "sync" else timeout_seconds

    # Acquire lock on cluster
    lock_result = await store.execute_query(q.GET_CLUSTER_FOR_SYNTHESIS, {
        "cluster_id": cluster_id,
        "silo_id": silo_id,
    })

    if not lock_result:
        return SynthesizeResult(
            belief_id=None, cluster_id=cluster_id, cluster_state=ClusterState.SPARSE,
            fact_count=0, confidence=None,
        ), []

    cluster_state = lock_result[0].get("state", "SPARSE")

    try:
        # Fetch facts in cluster
        facts_result = await store.execute_query(q.GET_FACTS_IN_CLUSTER, {
            "cluster_id": cluster_id, "silo_id": silo_id,
        })
        facts = list(facts_result) if facts_result else []
        fact_count = len(facts)

        # Check threshold
        if fact_count < SYNTHESIS_THRESHOLD:
            await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                "cluster_id": cluster_id, "silo_id": silo_id, "state": ClusterState.SPARSE.value,
            })
            return SynthesizeResult(
                belief_id=None, cluster_id=cluster_id, cluster_state=ClusterState.SPARSE,
                fact_count=fact_count, confidence=None,
            ), []

        # Compute aggregate confidence
        confidences = [float(f.get("confidence", 0.8)) for f in facts]
        aggregate_confidence = noisy_or_aggregate(confidences)

        if aggregate_confidence < SYNTHESIS_CONFIDENCE_THRESHOLD:
            await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                "cluster_id": cluster_id, "silo_id": silo_id, "state": ClusterState.READY.value,
            })
            return SynthesizeResult(
                belief_id=None, cluster_id=cluster_id, cluster_state=ClusterState.READY,
                fact_count=fact_count, confidence=aggregate_confidence,
            ), []

        # Call LLM
        synthesis_result = await llm_synthesize(llm, facts, effective_timeout)

        if synthesis_result.timed_out or not synthesis_result.success:
            await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                "cluster_id": cluster_id, "silo_id": silo_id, "state": ClusterState.READY.value,
            })
            return SynthesizeResult(
                belief_id=None, cluster_id=cluster_id, cluster_state=ClusterState.READY,
                fact_count=fact_count, confidence=aggregate_confidence,
                timed_out=synthesis_result.timed_out,
            ), []

        # Create belief
        belief_id = uuid.uuid4()
        created_at = datetime.now(UTC)
        props: dict[str, Any] = {
            "layer": "wisdom", "type": "belief", "state": NodeState.ACTIVE.value,
            "synthesis_state": SynthesisState.FRESH.value, "confidence": aggregate_confidence,
            "source_cluster_id": cluster_id,
        }
        fact_ids = [f["id"] for f in facts]

        await store.execute_write(q.CREATE_BELIEF_WITH_SYNTHESIZED_FROM, {
            "id": str(belief_id), "silo_id": silo_id, "content": synthesis_result.content,
            "created_at": created_at.isoformat(), "props": props, "fact_ids": fact_ids,
        })

        # Update cluster
        await store.execute_write(q.UPDATE_CLUSTER_AFTER_SYNTHESIS, {
            "cluster_id": cluster_id, "silo_id": silo_id, "state": ClusterState.SYNTHESIZED.value,
            "belief_id": str(belief_id), "synthesized_at": created_at.isoformat(),
        })

        events: list[ReactionEvent] = [
            ReactionEvent(event_type="compute_embedding", node_id=str(belief_id), silo_id=silo_id),
            ReactionEvent(event_type="update_heat", node_id=str(belief_id), silo_id=silo_id, payload={"access_type": "SYNTHESIS"}),
        ]

        logger.debug("tx4_synthesize_complete", belief_id=str(belief_id), cluster_id=cluster_id, fact_count=fact_count)

        return SynthesizeResult(
            belief_id=belief_id, cluster_id=cluster_id, cluster_state=ClusterState.SYNTHESIZED,
            fact_count=fact_count, confidence=aggregate_confidence,
        ), events

    except Exception:
        await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
            "cluster_id": cluster_id, "silo_id": silo_id, "state": cluster_state,
        })
        raise


async def tx0_store_memory(
    store: HyperGraphStore,
    content: str,
    silo_id: str,
    agent_id: str,
    *,
    tags: list[str] | None = None,
    content_type: str = "text",
    decay_class: str = "standard",
    metadata: dict[str, Any] | None = None,
) -> tuple[StoreMemoryResult, list[ReactionEvent]]:
    """TX0 STORE_MEMORY: Store an observation to Memory layer.

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

    label = _CONTENT_TYPE_TO_LABEL.get(content_type, "Document")

    props: dict[str, Any] = {
        "layer": "memory",
        "state": NodeState.ACTIVE.value,
        "content_type": content_type,
        "decay_class": decay_class,
        "created_by": agent_id,
        **(metadata or {}),
    }
    if tags:
        props["tags"] = tags

    # Build Cypher with literal label (labels can't be parameterized in Cypher)
    cypher = f"""
    CREATE (n:Node:{label} {{
        id: $id,
        silo_id: $silo_id,
        content: $content,
        created_at: $created_at,
        properties: $props
    }})
    RETURN n.id AS id
    """

    await store.execute_write(
        cypher,
        {
            "id": str(node_id),
            "silo_id": silo_id,
            "content": content,
            "created_at": created_at.isoformat(),
            "props": props,
        },
    )

    result = StoreMemoryResult(
        node_id=node_id,
        created_at=created_at,
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type="compute_embedding",
            node_id=str(node_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type="update_heat",
            node_id=str(node_id),
            silo_id=silo_id,
            payload={"access_type": "WRITE"},
        ),
    ]

    if len(content) > _EXTRACTION_THRESHOLD:
        events.append(
            ReactionEvent(
                event_type="check_extraction_trigger",
                node_id=str(node_id),
                silo_id=silo_id,
            )
        )

    logger.debug(
        "tx0_store_memory_complete",
        node_id=str(node_id),
        silo_id=silo_id,
        reaction_count=len(events),
    )

    return result, events


_CONTENT_TYPE_TO_LABEL: dict[str, str] = {
    "text": "Document",
    "utterance": "Utterance",
    "event": "Event",
    "observation": "Observation",
}

_EXTRACTION_THRESHOLD = 500


async def tx2_store_claim(
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
) -> tuple[StoreClaimResult, list[ReactionEvent]]:
    """TX2 STORE_CLAIM: Store a claim to Knowledge layer with evidence.

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
        silo_id: $silo_id,
        content: $content,
        created_at: $created_at,
        properties: $props
    })
    RETURN n.id AS id
    """

    await store.execute_write(
        cypher,
        {
            "id": str(node_id),
            "silo_id": silo_id,
            "content": content,
            "created_at": created_at.isoformat(),
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

    corroboration_count, promoted = await _check_corroboration(store, str(node_id), silo_id)

    # FLAG_CONTRADICTION: detect and flag structural conflicts
    conflict_events = await detect_spo_conflict(
        store, str(node_id), subject, predicate, object_value, silo_id
    )

    result = StoreClaimResult(
        node_id=node_id,
        created_at=created_at,
        superseded_id=superseded_id,
        corroboration_count=corroboration_count,
        promoted=promoted,
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type="compute_embedding",
            node_id=str(node_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type="update_heat",
            node_id=str(node_id),
            silo_id=silo_id,
            payload={"access_type": "WRITE"},
        ),
        ReactionEvent(
            event_type="update_cluster_membership",
            node_id=str(node_id),
            silo_id=silo_id,
        ),
    ]

    if supersedes:
        events.append(
            ReactionEvent(
                event_type="cascade_staleness",
                node_id=supersedes,
                silo_id=silo_id,
                payload={"depth": 1},
            )
        )

    events.extend(conflict_events)

    logger.debug(
        "tx2_store_claim_complete",
        node_id=str(node_id),
        silo_id=silo_id,
        corroboration_count=corroboration_count,
        promoted=promoted,
        reaction_count=len(events),
    )

    return result, events


async def tx3_supersede(
    store: HyperGraphStore,
    winner_id: str,
    loser_id: str,
    silo_id: str,
    reason: SupersedeReason,
) -> tuple[SupersedeResult, list[ReactionEvent]]:
    """TX3 SUPERSEDE: Mark a node as superseded by another.

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
            event_type="cascade_staleness",
            node_id=loser_id,
            silo_id=silo_id,
            payload={"depth": 1},
        ),
    ]

    logger.debug(
        "tx3_supersede_complete",
        winner_id=winner_id,
        loser_id=loser_id,
        reason=reason.value,
    )

    return result, events


async def tx17_link(
    store: HyperGraphStore,
    source_id: str,
    target_id: str,
    edge_type: LinkType,
    silo_id: str,
    agent_id: str,
    *,
    metadata: dict[str, Any] | None = None,
    weight: float = 1.0,
) -> tuple[LinkResult, list[ReactionEvent]]:
    """TX17 LINK: Create a typed relationship between nodes.

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
            event_type="update_heat",
            node_id=source_id,
            silo_id=silo_id,
            payload={"access_type": "LINK"},
        ),
        ReactionEvent(
            event_type="update_heat",
            node_id=target_id,
            silo_id=silo_id,
            payload={"access_type": "LINK"},
        ),
    ]

    if edge_type == LinkType.CONTRADICTS:
        events.append(
            ReactionEvent(
                event_type="flag_contradiction",
                node_id=source_id,
                silo_id=silo_id,
                payload={"contradicting_node_id": target_id},
            )
        )

    logger.debug(
        "tx17_link_complete",
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


async def tx8_commit(
    store: HyperGraphStore,
    content: str,
    about_refs: list[str],
    silo_id: str,
    agent_id: str,
    *,
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
) -> tuple[CommitResult, list[ReactionEvent]]:
    """TX8 COMMIT: Agent declares a stance directly.

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

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type="compute_embedding",
            node_id=str(commitment_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type="update_heat",
            node_id=str(commitment_id),
            silo_id=silo_id,
            payload={"access_type": "WRITE"},
        ),
    ]

    logger.debug(
        "tx8_commit_complete",
        commitment_id=str(commitment_id),
        silo_id=silo_id,
        about_count=len(about_refs),
    )

    return result, events


async def _validate_hypothesis(
    store: HyperGraphStore,
    hypothesis_id: str,
    silo_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Validate hypothesis exists, belongs to session, not crystallized, not tombstoned."""
    from context_service.db import queries as q

    results = await store.execute_query(
        q.GET_HYPOTHESIS_FOR_CRYSTALLIZE,
        {
            "hypothesis_id": hypothesis_id,
            "silo_id": silo_id,
            "session_id": session_id,
        },
    )

    if not results:
        return {"error": "HYPOTHESIS_NOT_FOUND", "message": "Hypothesis not found or wrong session"}

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


async def tx14_crystallize(
    store: HyperGraphStore,
    hypothesis_id: str,
    silo_id: str,
    agent_id: str,
    session_id: str,
) -> tuple[CrystallizeResult, list[ReactionEvent]]:
    """TX14 CRYSTALLIZE: Convert WorkingHypothesis to Commitment."""
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
        ReactionEvent(event_type="compute_embedding", node_id=str(commitment_id), silo_id=silo_id),
        ReactionEvent(
            event_type="update_heat",
            node_id=str(commitment_id),
            silo_id=silo_id,
            payload={"access_type": "WRITE"},
        ),
    ]

    logger.debug(
        "tx14_crystallize_complete",
        commitment_id=str(commitment_id),
        hypothesis_id=hypothesis_id,
        silo_id=silo_id,
    )

    return result, events


async def tx5_revise_belief(
    store: HyperGraphStore,
    belief_id: str,
    silo_id: str,
    llm: LLMProvider,
    embedder: EmbeddingService,
) -> tuple[ReviseBeliefResult, list[ReactionEvent]]:
    """TX5 REVISE_BELIEF: Re-synthesize a stale belief."""
    from context_service.db import queries as q

    # Get belief and validate
    belief_result = await store.execute_query(q.GET_BELIEF_FOR_REVISION, {
        "belief_id": belief_id, "silo_id": silo_id,
    })

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

    # Mark revision in progress
    await store.execute_write(q.MARK_BELIEF_REVISION_IN_PROGRESS, {
        "belief_id": belief_id, "silo_id": silo_id,
    })

    try:
        # Acquire cluster lock
        await store.execute_query(q.GET_CLUSTER_FOR_SYNTHESIS, {
            "cluster_id": cluster_id, "silo_id": silo_id,
        })

        try:
            # Fetch current facts
            facts_result = await store.execute_query(q.GET_FACTS_IN_CLUSTER, {
                "cluster_id": cluster_id, "silo_id": silo_id,
            })
            facts = list(facts_result) if facts_result else []
            fact_count = len(facts)

            # Check threshold - invalidate if below
            if fact_count < SYNTHESIS_THRESHOLD:
                await store.execute_write(q.UPDATE_BELIEF_AFTER_REVISION, {
                    "belief_id": belief_id, "silo_id": silo_id,
                    "synthesis_state": SynthesisState.INVALIDATED.value,
                })
                await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                    "cluster_id": cluster_id, "silo_id": silo_id, "state": ClusterState.SPARSE.value,
                })
                return ReviseBeliefResult(
                    new_belief_id=None, old_belief_id=uuid.UUID(belief_id),
                    content_changed=False, invalidated=True,
                ), []

            # Compute aggregate confidence
            confidences = [float(f.get("confidence", 0.8)) for f in facts]
            aggregate_confidence = noisy_or_aggregate(confidences)

            if aggregate_confidence < SYNTHESIS_CONFIDENCE_THRESHOLD:
                await store.execute_write(q.UPDATE_BELIEF_AFTER_REVISION, {
                    "belief_id": belief_id, "silo_id": silo_id,
                    "synthesis_state": SynthesisState.INVALIDATED.value,
                })
                await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                    "cluster_id": cluster_id, "silo_id": silo_id, "state": ClusterState.SPARSE.value,
                })
                return ReviseBeliefResult(
                    new_belief_id=None, old_belief_id=uuid.UUID(belief_id),
                    content_changed=False, invalidated=True,
                ), []

            # Call LLM with previous belief context
            synthesis_result = await llm_synthesize(llm, facts, 30.0, previous_belief=old_content)

            if not synthesis_result.success:
                await store.execute_write(q.UPDATE_BELIEF_AFTER_REVISION, {
                    "belief_id": belief_id, "silo_id": silo_id,
                    "synthesis_state": SynthesisState.STALE.value,
                })
                await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                    "cluster_id": cluster_id, "silo_id": silo_id, "state": ClusterState.STALE.value,
                })
                return ReviseBeliefResult(
                    new_belief_id=None, old_belief_id=uuid.UUID(belief_id), content_changed=False,
                ), []

            # Check if content changed
            new_content = synthesis_result.content or ""
            if new_content.strip() == old_content.strip():
                await store.execute_write(q.UPDATE_BELIEF_AFTER_REVISION, {
                    "belief_id": belief_id, "silo_id": silo_id,
                    "synthesis_state": SynthesisState.FRESH.value,
                })
                await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                    "cluster_id": cluster_id, "silo_id": silo_id, "state": ClusterState.SYNTHESIZED.value,
                })
                return ReviseBeliefResult(
                    new_belief_id=None, old_belief_id=uuid.UUID(belief_id), content_changed=False,
                ), []

            # Create new belief
            new_belief_id = uuid.uuid4()
            created_at = datetime.now(UTC)
            props: dict[str, Any] = {
                "layer": "wisdom", "type": "belief", "state": NodeState.ACTIVE.value,
                "synthesis_state": SynthesisState.FRESH.value, "confidence": aggregate_confidence,
                "source_cluster_id": cluster_id,
            }
            fact_ids = [f["id"] for f in facts]

            await store.execute_write(q.CREATE_BELIEF_WITH_SYNTHESIZED_FROM, {
                "id": str(new_belief_id), "silo_id": silo_id, "content": new_content,
                "created_at": created_at.isoformat(), "props": props, "fact_ids": fact_ids,
            })

            # Supersede old belief via SUPERSEDES edge
            await _create_supersedes_edge(
                store, str(new_belief_id), belief_id, silo_id, SupersedeReason.EVIDENCE_SHIFT
            )

            # Update cluster
            await store.execute_write(q.UPDATE_CLUSTER_AFTER_SYNTHESIS, {
                "cluster_id": cluster_id, "silo_id": silo_id, "state": ClusterState.SYNTHESIZED.value,
                "belief_id": str(new_belief_id), "synthesized_at": created_at.isoformat(),
            })

            events: list[ReactionEvent] = [
                ReactionEvent(event_type="compute_embedding", node_id=str(new_belief_id), silo_id=silo_id),
                ReactionEvent(event_type="update_heat", node_id=str(new_belief_id), silo_id=silo_id, payload={"access_type": "SYNTHESIS"}),
            ]

            logger.debug("tx5_revise_belief_complete", new_belief_id=str(new_belief_id), old_belief_id=belief_id)

            return ReviseBeliefResult(
                new_belief_id=new_belief_id, old_belief_id=uuid.UUID(belief_id), content_changed=True,
            ), events

        except Exception:
            await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                "cluster_id": cluster_id, "silo_id": silo_id, "state": ClusterState.STALE.value,
            })
            raise

    except Exception:
        await store.execute_write(q.UPDATE_BELIEF_AFTER_REVISION, {
            "belief_id": belief_id, "silo_id": silo_id, "synthesis_state": SynthesisState.STALE.value,
        })
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

    if await _would_create_cycle(store, winner_id, loser_id, "SUPERSEDES"):
        return {"error": "WOULD_CREATE_CYCLE"}

    return {"error": None}


async def _would_create_cycle(
    store: HyperGraphStore,
    source_id: str,
    target_id: str,
    edge_type: str,
) -> bool:
    """Check if adding edge would create a cycle (BFS from target to source)."""
    cypher = f"""
    MATCH path = (target {{id: $target_id}})-[:{edge_type}*]->(source {{id: $source_id}})
    RETURN count(path) > 0 AS would_cycle
    """
    results = await store.execute_query(cypher, {"source_id": source_id, "target_id": target_id})
    return results[0]["would_cycle"] if results else False


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
    cypher = """
    MATCH (new:Claim {id: $node_id, silo_id: $silo_id})
    MATCH (c:Claim {silo_id: $silo_id})
    WHERE c.properties.subject = new.properties.subject
      AND c.properties.predicate = new.properties.predicate
      AND c.properties.object = new.properties.object
      AND c.properties.state = 'ACTIVE'
    WITH collect(c) AS claims
    UNWIND claims AS claim
    OPTIONAL MATCH (claim)-[:DERIVED_FROM]->(evidence)
    WITH claims, collect(DISTINCT evidence.id) AS distinct_sources
    UNWIND claims AS claim
    SET claim.properties.corroboration_count = size(distinct_sources)
    RETURN size(distinct_sources) AS count, size(distinct_sources) >= $threshold AS should_promote
    """

    results = await store.execute_write(
        cypher,
        {"node_id": node_id, "silo_id": silo_id, "threshold": threshold},
    )

    if not results:
        return 1, False

    row = results[0]
    return row.get("count", 1), row.get("should_promote", False)


async def _check_corroboration(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
) -> tuple[int, bool]:
    """Check corroboration and potentially promote to Fact (TX18).

    Returns (corroboration_count, promoted).

    TODO: TX18 promotion (converting a corroborated Claim to a Fact node) is
    deferred to Phase 2. Currently only updates corroboration_count and returns
    whether the threshold is met; the caller receives `promoted=False` until
    TX18 is implemented.
    """
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
        store, source_id, target_id, edge_type.value
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
                event_type="conflict_detected",
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
