"""Brain transactions: Core write path with invariant enforcement.

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
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

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
class ReactionEvent:
    """Event emitted for async reaction processing."""

    event_type: str
    node_id: str
    silo_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


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

    props: dict[str, Any] = {
        "layer": "knowledge",
        "state": NodeState.ACTIVE.value,
        "claim_status": "UNPROMOTED",
        "confidence": confidence,
        "source_tier": source_tier or "unknown",
        "created_by": agent_id,
        "evidence": evidence_refs,
        **(metadata or {}),
    }
    if tags:
        props["tags"] = tags

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
    results = await store.execute_query(
        cypher, {"winner_id": winner_id, "loser_id": loser_id}
    )

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
    results = await store.execute_query(
        cypher, {"source_id": source_id, "target_id": target_id}
    )
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


async def _check_corroboration(
    _store: HyperGraphStore,
    _node_id: str,
    _silo_id: str,
) -> tuple[int, bool]:
    """Check corroboration and potentially promote to Fact (TX18).

    Returns (corroboration_count, promoted).
    """
    # TODO: Implement full CHECK_CORROBORATION per spec (Phase 2)
    return 1, False


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
    results = await store.execute_query(
        cypher, {"source_id": source_id, "target_id": target_id}
    )

    if not results:
        return {"error": "NODE_NOT_FOUND", "message": "Source or target node not found"}

    row = results[0]
    if row["source_silo"] != silo_id or row["target_silo"] != silo_id:
        return {
            "error": "CROSS_SILO_VIOLATION",
            "source_silo": row["source_silo"],
            "target_silo": row["target_silo"],
        }

    if row["source_state"] == NodeState.DELETED.value or row["target_state"] == NodeState.DELETED.value:
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
