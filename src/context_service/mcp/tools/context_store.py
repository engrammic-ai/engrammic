"""MCP tool: context_store - Unified write tool for all EAG layers."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog

from context_service.api.metrics import CONTEXT_STORE_LATENCY
from context_service.config.settings import get_settings
from context_service.mcp.server import (
    get_context_service,
    get_evidence_validator,
    get_mcp_auth_context,
    get_redis,
    get_silo_service,
)
from context_service.models.mcp import (
    Crystallization,
    DecayClass,
    ObservationType,
    ReasoningStep,
    SourceType,
    SPOClaim,
)
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import validate_silo_ownership
from context_service.signals import emit_access_event

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = structlog.get_logger(__name__)

_LAYER_TO_LABEL: dict[str, str] = {
    "memory": "Document",
    "knowledge": "Claim",
    "wisdom": "Commitment",
    "intelligence": "ReasoningChain",
    "meta": "MetaObservation",
    "belief": "WorkingHypothesis",
}


def _layer_to_label(layer: str) -> str:
    """Map EAG layer name to node label for heat tracking."""
    return _LAYER_TO_LABEL.get(layer, "Document")


# Minimum evidence count for R1 promotion. Per T5 spec, consensus requires
# multiple sources - single evidence should not auto-promote to Fact.
_R1_THRESHOLD = 3

_VALID_SOURCE_TIERS = ("authoritative", "validated", "community", "unknown")


async def _context_remember(
    silo_id: str | None,
    content: str,
    content_type: str = "text",
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    decay_class: str = "standard",
    observed_from: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    auth = await get_mcp_auth_context()

    if silo_id is not None:
        err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
        if err is not None:
            return err

    validated_silo_id = derive_silo_id(auth.org_id)

    try:
        decay = DecayClass(decay_class)
    except ValueError:
        return {
            "error": "invalid_decay_class",
            "message": f"decay_class must be one of: {[e.value for e in DecayClass]}",
        }

    ctx_svc = get_context_service()
    scope = ScopeContext(org_id=auth.org_id, silo_id=validated_silo_id)
    _start = time.perf_counter()
    node = await ctx_svc.remember(
        scope=scope,
        content=content,
        content_type=content_type,
        metadata=metadata,
        tags=tags,
        decay_class=decay,
        observed_from=observed_from,
        agent_id=auth.agent_id,
    )
    CONTEXT_STORE_LATENCY.labels(tool="context_remember").observe(time.perf_counter() - _start)

    return {
        "node_id": str(node.id),
        "layer": "memory",
        "decay_class": decay_class,
        "created_at": datetime.now(UTC).isoformat(),
    }


async def _context_assert(
    silo_id: str | None,
    claim: str | dict[str, Any],
    evidence: str | list[str],
    source_type: str,
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    evidence_mode: str = "sync",
    source_tier: str | None = None,
) -> dict[str, Any]:
    """Internal implementation."""
    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()
    ev_validator = get_evidence_validator()

    if silo_id is not None:
        err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
        if err is not None:
            return err

    expected_silo_id = derive_silo_id(auth.org_id)

    try:
        src_type = SourceType(source_type)
    except ValueError:
        return {
            "error": "invalid_source_type",
            "message": f"Must be one of: {[e.value for e in SourceType]}",
        }

    if source_tier is not None and source_tier not in _VALID_SOURCE_TIERS:
        return {
            "error": "invalid_source_tier",
            "message": f"Must be one of: {list(_VALID_SOURCE_TIERS)}",
        }

    if not 0.0 <= confidence <= 1.0:
        return {"error": "invalid_confidence", "message": "confidence must be between 0.0 and 1.0"}

    claim_type = "freeform"
    parsed_claim: str | SPOClaim
    if isinstance(claim, dict):
        try:
            parsed_claim = SPOClaim(**claim)
            claim_type = "structured"
        except Exception as e:
            return {"error": "invalid_claim", "message": str(e)}
    else:
        parsed_claim = claim

    evidence_list = [evidence] if isinstance(evidence, str) else list(evidence)

    evidence_nodes: list[str] = []
    if evidence_mode == "sync":
        for ev_ref in evidence_list:
            result = await ev_validator.validate(ev_ref, str(expected_silo_id))
            if result.status != "valid":
                return {
                    "error": "invalid_evidence",
                    "evidence": ev_ref,
                    "reason": result.reason,
                }
            if result.node_id:
                evidence_nodes.append(result.node_id)

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    node = await ctx_svc.assert_claim(
        scope=scope,
        claim=parsed_claim,
        evidence=evidence_list,
        source_type=src_type,
        confidence=confidence,
        metadata=metadata,
        tags=tags,
        agent_id=auth.agent_id,
        source_tier=source_tier,
    )

    promoted = False
    if len(evidence_list) >= _R1_THRESHOLD:
        try:
            promotion_result = await ctx_svc.promote_claim_to_fact(
                silo_id=str(expected_silo_id),
                claim_id=str(node.id),
                evidence_count=len(evidence_list),
            )
            if promotion_result is not None:
                promoted = True
        except Exception:
            logger.warning(
                "claim_assert_promotion_failed",
                exc_info=True,
                claim_id=str(node.id),
            )

    return {
        "node_id": str(node.id),
        "layer": "knowledge",
        "claim_type": claim_type,
        "evidence_status": "verified" if evidence_mode == "sync" else "pending",
        "evidence_nodes": evidence_nodes,
        "promoted_to_fact": promoted,
        "created_at": datetime.now(UTC).isoformat(),
    }


async def _context_commit(
    silo_id: str | None,
    belief: str,
    about: list[str],
    confidence: float = 0.8,
    reasoning: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    chain_id: str | None = None,
) -> dict[str, Any]:
    """Internal implementation."""
    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()

    if silo_id is not None:
        err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
        if err is not None:
            return err

    expected_silo_id = derive_silo_id(auth.org_id)

    if not about:
        return {"error": "missing_about", "message": "about must reference at least one node"}

    agent_id = auth.agent_id or auth.org_id

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    node = await ctx_svc.commit_belief(
        scope=scope,
        belief=belief,
        about=about,
        confidence=confidence,
        reasoning=reasoning,
        metadata=metadata,
        tags=tags,
        agent_id=agent_id,
    )

    result: dict[str, Any] = {
        "node_id": str(node.id),
        "layer": "wisdom",
        "declared_by": agent_id,
        "about_nodes": about,
        "created_at": datetime.now(UTC).isoformat(),
    }

    if chain_id is not None:
        try:
            from context_service.engine.compaction import compact_reasoning_chain

            event_id = await compact_reasoning_chain(
                ctx_svc.graph_store,
                chain_id=chain_id,
                silo_id=str(expected_silo_id),
                outcome="committed",
            )
            result["compacted_chain_id"] = chain_id
            result["compaction_event_id"] = event_id
        except ValueError as exc:
            logger.warning(
                "context_commit_compaction_skip",
                chain_id=chain_id,
                reason=str(exc),
            )

    return result


async def _context_reflect(
    silo_id: str | None,
    observation: str,
    observation_type: str,
    about: list[str],
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Internal implementation."""
    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()

    if silo_id is not None:
        err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
        if err is not None:
            return err

    expected_silo_id = derive_silo_id(auth.org_id)

    try:
        obs_type = ObservationType(observation_type)
    except ValueError:
        return {
            "error": "invalid_observation_type",
            "valid": [e.value for e in ObservationType],
        }

    agent_id = auth.agent_id or auth.org_id

    if agent_id is not None:
        try:
            await ctx_svc.graph_store.upsert_agent(
                agent_id,
                str(expected_silo_id),
                role="reflector",
            )
        except Exception:
            logger.warning(
                "context_reflect_agent_upsert_failed",
                exc_info=True,
                agent_id=agent_id,
            )

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    node = await ctx_svc.reflect(
        scope=scope,
        observation=observation,
        observation_type=obs_type,
        about=about,
        confidence=confidence,
        metadata=metadata,
        agent_id=agent_id,
    )

    return {
        "node_id": str(node.id),
        "observation_type": observation_type,
        "about_nodes": about,
        "created_at": datetime.now(UTC).isoformat(),
    }


async def _context_reason(
    silo_id: str | None,
    steps: list[dict[str, Any]],
    conclusion: str | None = None,
    evidence_used: list[str] | None = None,
    crystallizations: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    parent_chain_id: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.db import queries as q
    from context_service.engine.chain_saga import ChainSagaWriter
    from context_service.engine.postgres_store import PostgresStore
    from context_service.engine.sessions import attach_chain_to_session, create_or_join_session
    from context_service.models.inference import ChainStep

    auth = await get_mcp_auth_context()

    if silo_id is not None:
        err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
        if err is not None:
            return err

    expected_silo_id = derive_silo_id(auth.org_id)

    if not steps:
        return {"error": "missing_steps", "message": "steps must be a non-empty list"}

    try:
        parsed_steps = [ReasoningStep(**s) for s in steps]
    except Exception as e:
        return {"error": "invalid_steps", "message": str(e)}

    try:
        parsed_cryst = [Crystallization(**c) for c in (crystallizations or [])]
    except Exception as e:
        return {"error": "invalid_crystallizations", "message": str(e)}

    ctx_svc = get_context_service()

    resolved_session_id = session_id or auth.session_id or str(uuid.uuid4())
    agent_id = auth.agent_id

    store = ctx_svc.graph_store
    await create_or_join_session(store, resolved_session_id, str(expected_silo_id))

    if agent_id is not None:
        try:
            await store.upsert_agent(
                agent_id,
                str(expected_silo_id),
                role="reasoner",
            )
        except Exception:
            logger.warning(
                "context_reason_agent_upsert_failed",
                exc_info=True,
                agent_id=agent_id,
            )

    # Validate parent_chain_id before chain creation so we can fail fast.
    if parent_chain_id is not None:
        try:
            parent_rows = await store.execute_query(
                q.GET_REASONING_CHAIN_IN_SILO,
                {"chain_id": parent_chain_id, "silo_id": str(expected_silo_id)},
            )
        except Exception:
            logger.warning(
                "context_reason_parent_chain_lookup_failed",
                exc_info=True,
                parent_chain_id=parent_chain_id,
            )
            parent_rows = []

        if not parent_rows:
            return {
                "error": "invalid_parent_chain_id",
                "message": f"parent_chain_id {parent_chain_id!r} not found in silo",
            }

    # Generate chain_id here so it can be passed to both the saga and session
    # attachment. The saga writes Postgres first (full steps), then the Memgraph
    # summary projection via upsert_reasoning_chain. Compensation rolls back
    # the Postgres row on Memgraph failure.
    chain_id = uuid.uuid4()
    produced_by_model = "unknown"
    produced_by_agent_id = agent_id or auth.org_id

    chain_steps = [
        ChainStep(
            step_index=s.step,
            operation=s.reasoning[:80] if len(s.reasoning) > 80 else s.reasoning,
            conclusion=s.reasoning,
            confidence=s.confidence if s.confidence is not None else 0.8,
        )
        for s in parsed_steps
    ]

    postgres_store = PostgresStore()
    saga = ChainSagaWriter(postgres_store, store)

    from context_service.services.models import derive_org_uuid

    await saga.write_chain(
        chain_id=chain_id,
        silo_id=expected_silo_id,
        steps=chain_steps,
        produced_by_model=produced_by_model,
        produced_by_agent_id=produced_by_agent_id,
        status="draft",
        source="agent_explicit",
        conclusion=conclusion,
        evidence_used=evidence_used,
        org_id=derive_org_uuid(auth.org_id),
    )

    await attach_chain_to_session(store, str(chain_id), resolved_session_id, str(expected_silo_id))

    continues_parent: str | None = None
    if parent_chain_id is not None:
        try:
            await store.execute_write(
                q.CREATE_CONTINUES_EDGE,
                {
                    "child_chain_id": str(chain_id),
                    "parent_chain_id": parent_chain_id,
                    "silo_id": str(expected_silo_id),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            continues_parent = parent_chain_id
        except Exception:
            logger.warning(
                "context_reason_continues_edge_failed",
                exc_info=True,
                child_chain_id=str(chain_id),
                parent_chain_id=parent_chain_id,
            )

    # Crystallize reasoning to Wisdom layer via T7 (commit).
    # Per EAG spec, single-agent crystallizations create Commitments (Wisdom),
    # not Claims (Knowledge). T5 consensus is required for Knowledge promotion.
    crystallized_ids: list[str] = []
    if parsed_cryst:
        import asyncio

        scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)

        effective_agent_id = agent_id or auth.org_id

        async def create_commitment(cryst: Crystallization) -> str | None:
            try:
                # Convert claim to string if it's an SPOClaim
                if isinstance(cryst.claim, str):
                    belief_text = cryst.claim
                else:
                    belief_text = (
                        f"{cryst.claim.subject} {cryst.claim.predicate} {cryst.claim.object}"
                    )
                commitment_node = await ctx_svc.commit_belief(
                    scope=scope,
                    belief=belief_text,
                    about=[],  # No specific entity refs from reasoning
                    confidence=cryst.confidence,
                    reasoning=f"Crystallized from reasoning chain {chain_id}",
                    agent_id=effective_agent_id,
                )
                return str(commitment_node.id)
            except Exception:
                logger.warning(
                    "context_reason_crystallization_failed",
                    exc_info=True,
                    chain_id=str(chain_id),
                    claim=str(cryst.claim)[:100],
                )
                return None

        results = await asyncio.gather(*[create_commitment(c) for c in parsed_cryst])
        crystallized_ids = [r for r in results if r is not None]

        # Batch create all edges in one query
        if crystallized_ids:
            now = datetime.now(UTC).isoformat()
            edges = [
                {
                    "chain_id": str(chain_id),
                    "claim_id": commitment_id,  # Now commitment IDs
                    "silo_id": str(expected_silo_id),
                    "created_at": now,
                }
                for commitment_id in crystallized_ids
            ]
            await store.execute_write(q.BATCH_CREATE_CRYSTALLIZES_EDGES, {"edges": edges})

    response: dict[str, Any] = {
        "chain_id": str(chain_id),
        "layer": "intelligence",
        "steps_count": len(steps),
        "crystallized_claim_ids": crystallized_ids,
        "session_id": resolved_session_id,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if continues_parent is not None:
        response["continues_chain_id"] = continues_parent
    return response


async def _context_store_belief(
    silo_id: str,
    content: str,
    session_id: str,
    about: list[str],
    confidence: float = 0.8,
) -> dict[str, Any]:
    """Create a WorkingHypothesis node and run sync conflict detection."""
    if not 0.0 <= confidence <= 1.0:
        return {"error": "invalid_confidence", "message": "confidence must be between 0.0 and 1.0"}

    from context_service.db import queries as q
    from context_service.engine.sessions import create_or_join_session

    ctx_svc = get_context_service()
    store = ctx_svc.graph_store

    await create_or_join_session(store, session_id, silo_id)

    belief_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    await store.execute_write(
        q.CREATE_WORKING_HYPOTHESIS,
        {
            "id": belief_id,
            "silo_id": silo_id,
            "session_id": session_id,
            "content": content,
            "confidence": confidence,
            "created_at": now,
            "about_ids": about,
        },
    )

    conflict_rows = await store.execute_query(
        q.DETECT_CONFLICTING_WORKING_HYPOTHESES,
        {"new_belief_id": belief_id, "silo_id": silo_id},
    )
    conflict_ids = [row["conflict_id"] for row in conflict_rows]

    result: dict[str, Any] = {
        "belief_id": belief_id,
        "layer": "belief",
        "session_id": session_id,
        "created_at": now,
    }
    if conflict_ids:
        result["potential_conflicts"] = conflict_ids
    return result


async def _context_store(
    silo_id: str | None,
    content: str,
    layer: str,
    evidence: list[str] | None = None,
    source_type: str | None = None,
    confidence: float = 0.8,
    about: list[str] | None = None,
    reasoning: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    observation_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    decay_class: str = "standard",
    parent_chain_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    if layer == "belief":
        if not about:
            return {
                "error": "missing_about",
                "message": "about required for belief layer",
            }
        if not session_id:
            return {
                "error": "missing_session_id",
                "message": "session_id required for belief layer",
            }
        auth = await get_mcp_auth_context()
        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err
        resolved_silo = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_store_belief(
            silo_id=resolved_silo,
            content=content,
            session_id=session_id,
            about=about,
            confidence=confidence,
        )

    if layer == "memory":
        result = await _context_remember(
            silo_id=silo_id,
            content=content,
            metadata=metadata,
            tags=tags,
            decay_class=decay_class,
        )
        return result

    if layer == "knowledge":
        if not evidence:
            return {
                "error": "missing_evidence",
                "message": "evidence required for knowledge layer",
            }
        if not source_type:
            return {
                "error": "missing_source_type",
                "message": "source_type required for knowledge layer",
            }
        result = await _context_assert(
            silo_id=silo_id,
            claim=content,
            evidence=evidence,
            source_type=source_type,
            confidence=confidence,
            metadata=metadata,
            tags=tags,
        )
        if "layer" not in result:
            result["layer"] = "knowledge"
        return result

    if layer == "wisdom":
        if not about:
            return {
                "error": "missing_about",
                "message": "about required for wisdom layer",
            }
        result = await _context_commit(
            silo_id=silo_id,
            belief=content,
            about=about,
            confidence=confidence,
            reasoning=reasoning,
            metadata=metadata,
            tags=tags,
        )
        if "layer" not in result:
            result["layer"] = "wisdom"
        return result

    if layer == "intelligence":
        if not steps:
            return {
                "error": "missing_steps",
                "message": "steps required for intelligence layer",
            }
        result = await _context_reason(
            silo_id=silo_id,
            steps=steps,
            conclusion=content,
            evidence_used=evidence,
            parent_chain_id=parent_chain_id,
        )
        if "layer" not in result:
            result["layer"] = "intelligence"
        return result

    if layer == "meta":
        if not observation_type:
            return {
                "error": "missing_observation_type",
                "message": "observation_type required for meta layer",
            }
        if not about:
            return {
                "error": "missing_about",
                "message": "about required for meta layer",
            }
        result = await _context_reflect(
            silo_id=silo_id,
            observation=content,
            observation_type=observation_type,
            about=about,
            confidence=confidence,
            metadata=metadata,
        )
        if "layer" not in result:
            result["layer"] = "meta"
        return result

    return {
        "error": "invalid_layer",
        "valid": ["memory", "knowledge", "wisdom", "intelligence", "meta", "belief"],
    }


def register(mcp: FastMCP) -> None:
    """Register the context_store tool."""

    @mcp.tool(
        name="context_store",
        description=(
            "Unified write tool for all EAG layers. "
            "Routes to memory, knowledge, wisdom, intelligence, meta, or belief based on layer. "
            "knowledge requires evidence + source_type. "
            "wisdom requires about. "
            "intelligence requires steps. "
            "meta requires observation_type + about. "
            "belief requires about + session_id."
        ),
    )
    async def context_store(
        content: str,
        layer: Literal["memory", "knowledge", "wisdom", "intelligence", "meta", "belief"],
        evidence: list[str] | None = None,
        source_type: str | None = None,
        confidence: float = 0.8,
        about: list[str] | None = None,
        reasoning: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        observation_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        decay_class: str = "standard",
        silo_id: str | None = None,
        parent_chain_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Store to any EAG layer.

        Args:
            content: The content to store. For intelligence layer, this is the conclusion.
            layer: Target layer: memory|knowledge|wisdom|intelligence|meta|belief.
            evidence: Evidence refs (node:<uuid> or URI). Required for knowledge layer.
            source_type: Source type for knowledge layer: document|user|external|agent.
            confidence: 0.0-1.0, agent's confidence (default 0.8). Guidelines:
                0.95+ = near certain, verified from multiple sources
                0.8-0.95 = confident, single reliable source or strong reasoning
                0.6-0.8 = probable, reasonable inference with some uncertainty
                0.4-0.6 = uncertain, plausible but unverified
                <0.4 = speculative, weak evidence or tentative hypothesis
            about: Node IDs this content concerns. Required for wisdom, meta, and belief layers.
            reasoning: Reasoning behind a wisdom-layer belief.
            steps: Reasoning steps for intelligence layer. List of {step, reasoning, confidence?}.
            observation_type: Meta-observation type. Required for meta layer.
            metadata: Optional metadata dict.
            tags: Optional tags for filtering.
            decay_class: ephemeral|standard|durable|permanent (memory layer only).
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.
            parent_chain_id: Intelligence layer only. UUID of an existing ReasoningChain
                in the same silo that this chain continues. Creates a CONTINUES edge
                (child_chain -> parent_chain). One chain can continue only one parent.
            session_id: Belief layer only. ID of the ReasoningSession the WorkingBelief
                belongs to. Required for belief layer; ignored for all other layers.

        Returns:
            Layer-specific response dict with at minimum {node_id, layer, created_at}.
            Intelligence layer includes continues_chain_id when parent_chain_id is set.
            Belief layer returns {belief_id, layer, session_id, created_at} and includes
            potential_conflicts when other beliefs in the session target the same nodes.
        """
        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))

        result = await _context_store(
            silo_id=resolved_silo_id,
            content=content,
            layer=layer,
            evidence=evidence,
            source_type=source_type,
            confidence=confidence,
            about=about,
            reasoning=reasoning,
            steps=steps,
            observation_type=observation_type,
            metadata=metadata,
            tags=tags,
            decay_class=decay_class,
            parent_chain_id=parent_chain_id,
            session_id=session_id,
        )

        if "error" not in result and get_settings().write_events_enabled:
            redis = get_redis()
            if redis is not None:
                node_id = result.get("node_id") or result.get("chain_id") or result.get("belief_id")
                if node_id:
                    node_label = _layer_to_label(layer)
                    await emit_access_event(
                        redis, resolved_silo_id, str(node_id), event_type="write", layer=node_label
                    )

        return result
