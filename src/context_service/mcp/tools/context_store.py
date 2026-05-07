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
from context_service.mcp.tools.errors import error_response, success_response
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
    "belief": "WorkingBelief",
}


def _layer_to_label(layer: str) -> str:
    """Map EAG layer name to node label for heat tracking."""
    return _LAYER_TO_LABEL.get(layer, "Document")


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
        return error_response(
            "VALIDATION_ERROR",
            f"decay_class must be one of: {[e.value for e in DecayClass]}",
            details={"field": "decay_class", "valid_values": [e.value for e in DecayClass]},
        )

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

    return success_response({
        "node_id": str(node.id),
        "layer": "memory",
        "decay_class": decay_class,
        "created_at": datetime.now(UTC).isoformat(),
    })


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
        return error_response(
            "VALIDATION_ERROR",
            f"source_type must be one of: {[e.value for e in SourceType]}",
            details={"field": "source_type", "valid_values": [e.value for e in SourceType]},
        )

    if source_tier is not None and source_tier not in _VALID_SOURCE_TIERS:
        return error_response(
            "VALIDATION_ERROR",
            f"source_tier must be one of: {list(_VALID_SOURCE_TIERS)}",
            details={"field": "source_tier", "valid_values": list(_VALID_SOURCE_TIERS)},
        )

    if not 0.0 <= confidence <= 1.0:
        return error_response(
            "VALIDATION_ERROR",
            "confidence must be between 0.0 and 1.0",
            details={"field": "confidence"},
        )

    claim_type = "freeform"
    parsed_claim: str | SPOClaim
    if isinstance(claim, dict):
        try:
            parsed_claim = SPOClaim(**claim)
            claim_type = "structured"
        except Exception as e:
            return error_response("VALIDATION_ERROR", str(e), details={"field": "claim"})
    else:
        parsed_claim = claim

    evidence_list = [evidence] if isinstance(evidence, str) else list(evidence)

    evidence_nodes: list[str] = []
    if evidence_mode == "sync":
        for ev_ref in evidence_list:
            result = await ev_validator.validate(ev_ref, str(expected_silo_id))
            if result.status != "valid":
                return error_response(
                    "VALIDATION_ERROR",
                    f"Evidence reference {ev_ref!r} is not valid: {result.reason}",
                    details={"field": "evidence", "evidence_ref": ev_ref, "reason": result.reason},
                )
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

    return success_response({
        "node_id": str(node.id),
        "layer": "knowledge",
        "claim_type": claim_type,
        "evidence_status": "verified" if evidence_mode == "sync" else "pending",
        "evidence_nodes": evidence_nodes,
        "status": "pending_promotion",
        "created_at": datetime.now(UTC).isoformat(),
    })


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
        return error_response(
            "VALIDATION_ERROR",
            "about must reference at least one node",
            details={"field": "about"},
        )

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

    payload: dict[str, Any] = {
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
            payload["compacted_chain_id"] = chain_id
            payload["compaction_event_id"] = event_id
        except ValueError as exc:
            logger.warning(
                "context_commit_compaction_skip",
                chain_id=chain_id,
                reason=str(exc),
            )

    return success_response(payload)


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
        return error_response(
            "VALIDATION_ERROR",
            f"observation_type must be one of: {[e.value for e in ObservationType]}",
            details={"field": "observation_type", "valid_values": [e.value for e in ObservationType]},
        )

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

    return success_response({
        "node_id": str(node.id),
        "layer": "meta",
        "observation_type": observation_type,
        "about_nodes": about,
        "created_at": datetime.now(UTC).isoformat(),
    })


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
        return error_response(
            "VALIDATION_ERROR",
            "steps must be a non-empty list",
            details={"field": "steps"},
        )

    try:
        parsed_steps = [ReasoningStep(**s) for s in steps]
    except Exception as e:
        return error_response("VALIDATION_ERROR", str(e), details={"field": "steps"})

    try:
        parsed_cryst = [Crystallization(**c) for c in (crystallizations or [])]
    except Exception as e:
        return error_response("VALIDATION_ERROR", str(e), details={"field": "crystallizations"})

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
            return error_response(
                "NOT_FOUND",
                f"parent_chain_id {parent_chain_id!r} not found in silo",
                details={"field": "parent_chain_id", "parent_chain_id": parent_chain_id},
            )

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

    # Crystallize claims from reasoning (Intelligence -> Knowledge)
    # Parallel claim creation + batch edge write for performance
    crystallized_ids: list[str] = []
    if parsed_cryst:
        import asyncio

        scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)

        async def create_claim(cryst: Crystallization) -> str | None:
            try:
                claim_node = await ctx_svc.assert_claim(
                    scope=scope,
                    claim=cryst.claim,
                    evidence=[str(chain_id)],
                    source_type=SourceType.AGENT,
                    confidence=cryst.confidence,
                    agent_id=agent_id,
                    source_tier="validated",
                )
                return str(claim_node.id)
            except Exception:
                logger.warning(
                    "context_reason_crystallization_failed",
                    exc_info=True,
                    chain_id=str(chain_id),
                    claim=str(cryst.claim)[:100],
                )
                return None

        results = await asyncio.gather(*[create_claim(c) for c in parsed_cryst])
        crystallized_ids = [r for r in results if r is not None]

        # Batch create all edges in one query
        if crystallized_ids:
            now = datetime.now(UTC).isoformat()
            edges = [
                {
                    "chain_id": str(chain_id),
                    "claim_id": claim_id,
                    "silo_id": str(expected_silo_id),
                    "created_at": now,
                }
                for claim_id in crystallized_ids
            ]
            await store.execute_write(q.BATCH_CREATE_CRYSTALLIZES_EDGES, {"edges": edges})

    payload: dict[str, Any] = {
        "chain_id": str(chain_id),
        "layer": "intelligence",
        "steps_count": len(steps),
        "crystallized_claim_ids": crystallized_ids,
        "session_id": resolved_session_id,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if continues_parent is not None:
        payload["continues_chain_id"] = continues_parent
    return success_response(payload)


async def _context_store_belief(
    silo_id: str,
    content: str,
    session_id: str,
    about: list[str],
    confidence: float = 0.8,
) -> dict[str, Any]:
    """Create a WorkingBelief node and run sync conflict detection."""
    from context_service.db import queries as q
    from context_service.engine.sessions import create_or_join_session

    ctx_svc = get_context_service()
    store = ctx_svc.graph_store

    await create_or_join_session(store, session_id, silo_id)

    belief_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    await store.execute_write(
        q.CREATE_WORKING_BELIEF,
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
        q.DETECT_CONFLICTING_WORKING_BELIEFS,
        {"new_belief_id": belief_id, "silo_id": silo_id},
    )
    conflict_ids = [row["conflict_id"] for row in conflict_rows]

    payload: dict[str, Any] = {
        "belief_id": belief_id,
        "layer": "belief",
        "session_id": session_id,
        "created_at": now,
    }
    if conflict_ids:
        payload["potential_conflicts"] = conflict_ids
    return success_response(payload)


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
    _VALID_LAYERS = ["memory", "knowledge", "wisdom", "intelligence", "meta", "belief"]

    if layer == "belief":
        if not about:
            return error_response(
                "VALIDATION_ERROR",
                "Belief layer requires 'about' — a list of node IDs this working belief "
                "targets. Used for conflict detection within the session.",
                details={"field": "about"},
            )
        if not session_id:
            return error_response(
                "VALIDATION_ERROR",
                "Belief layer requires 'session_id' — the ID of the ReasoningSession "
                "this belief belongs to. Obtain one from context_belief_state.",
                details={"field": "session_id"},
            )
        auth = await get_mcp_auth_context()
        resolved_silo = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_store_belief(
            silo_id=resolved_silo,
            content=content,
            session_id=session_id,
            about=about,
            confidence=confidence,
        )

    if layer == "memory":
        return await _context_remember(
            silo_id=silo_id,
            content=content,
            metadata=metadata,
            tags=tags,
            decay_class=decay_class,
        )

    if layer == "knowledge":
        if not evidence:
            return error_response(
                "VALIDATION_ERROR",
                "Knowledge layer requires 'evidence' — a list of node IDs or URIs "
                "that support this claim. Use format ['node:<uuid>'] or ['https://...'].",
                details={"field": "evidence"},
            )
        if not source_type:
            return error_response(
                "VALIDATION_ERROR",
                "Knowledge layer requires 'source_type' — origin of this claim. "
                "Must be one of: document, user, external, agent.",
                details={"field": "source_type"},
            )
        return await _context_assert(
            silo_id=silo_id,
            claim=content,
            evidence=evidence,
            source_type=source_type,
            confidence=confidence,
            metadata=metadata,
            tags=tags,
        )

    if layer == "wisdom":
        if not about:
            return error_response(
                "VALIDATION_ERROR",
                "Wisdom layer requires 'about' — a list of node IDs (Claims or Documents) "
                "that this commitment synthesizes. Use node IDs from prior knowledge/memory stores.",
                details={"field": "about"},
            )
        return await _context_commit(
            silo_id=silo_id,
            belief=content,
            about=about,
            confidence=confidence,
            reasoning=reasoning,
            metadata=metadata,
            tags=tags,
        )

    if layer == "intelligence":
        if not steps:
            return error_response(
                "VALIDATION_ERROR",
                "Intelligence layer requires 'steps' — a list of reasoning steps. "
                "Each step must have {step: int, reasoning: str, confidence?: float}. "
                "Set 'content' to the overall conclusion of the chain.",
                details={"field": "steps"},
            )
        return await _context_reason(
            silo_id=silo_id,
            steps=steps,
            conclusion=content,
            evidence_used=evidence,
            parent_chain_id=parent_chain_id,
        )

    if layer == "meta":
        if not observation_type:
            return error_response(
                "VALIDATION_ERROR",
                "Meta layer requires 'observation_type' — the kind of meta-cognitive "
                "observation being recorded (e.g. contradiction, correction, uncertainty, pattern).",
                details={"field": "observation_type"},
            )
        if not about:
            return error_response(
                "VALIDATION_ERROR",
                "Meta layer requires 'about' — a list of node IDs that this observation "
                "targets. Must reference existing nodes in the silo.",
                details={"field": "about"},
            )
        return await _context_reflect(
            silo_id=silo_id,
            observation=content,
            observation_type=observation_type,
            about=about,
            confidence=confidence,
            metadata=metadata,
        )

    return error_response(
        "VALIDATION_ERROR",
        f"Layer {layer!r} is not valid. "
        "Choose one of: memory, knowledge, wisdom, intelligence, meta, belief. "
        "memory = raw observations; knowledge = evidence-backed claims; "
        "wisdom = synthesized commitments; intelligence = reasoning chains; "
        "meta = meta-cognitive observations; belief = working session beliefs.",
        details={"field": "layer", "valid_values": _VALID_LAYERS},
    )


def register(mcp: FastMCP) -> None:
    """Register the context_store tool."""

    @mcp.tool(
        name="context_store",
        description=(
            "Unified write tool for all EAG layers. "
            "Routes to memory, knowledge, wisdom, intelligence, meta, or belief based on 'layer'. "
            "Required params per layer: "
            "memory — content only; "
            "knowledge — content (the claim text), evidence (list of node IDs/URIs), source_type (document|user|external|agent); "
            "wisdom — content (the belief statement), about (node IDs this synthesizes); "
            "intelligence — content (conclusion), steps (list of {step, reasoning, confidence?}); "
            "meta — content (observation text), observation_type, about (target node IDs); "
            "belief — content, about (target node IDs), session_id."
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

        Examples:
            Memory (raw observation, no extra params required)::

                layer="memory", content="User prefers dark mode in the IDE"

            Knowledge (evidence-backed claim)::

                layer="knowledge", content="Redis cache reduces p95 latency by 40%",
                evidence=["node:abc123", "https://example.com/benchmark"],
                source_type="document", confidence=0.9

            Wisdom (synthesized commitment across claims)::

                layer="wisdom", content="Caching is essential for production performance",
                about=["node:abc123", "node:def456"], reasoning="Two independent studies confirm"

            Intelligence (reasoning chain with explicit steps)::

                layer="intelligence", content="The outage was caused by a missing index",
                steps=[{"step": 1, "reasoning": "Latency spiked at 14:32 UTC", "confidence": 0.95}]

            Meta (meta-cognitive observation about existing nodes)::

                layer="meta", content="This claim contradicts the earlier measurement",
                observation_type="contradiction", about=["node:abc123", "node:ghi789"]

            Belief (working session belief, for in-flight reasoning)::

                layer="belief", content="The bug is in the auth middleware",
                about=["node:abc123"], session_id="sess:xyz"

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
            Knowledge layer returns status="pending_promotion" — fact promotion is
            handled asynchronously by the custodian, not inline.
            Intelligence layer includes continues_chain_id when parent_chain_id is set.
            Belief layer returns {belief_id, layer, session_id, created_at} and includes
            potential_conflicts when other beliefs in the session target the same nodes.
        """
        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))

        # Determine which passed params are not applicable for the chosen layer.
        _LAYER_INAPPLICABLE: dict[str, set[str]] = {
            "memory": {"evidence", "source_type", "about", "steps", "observation_type", "parent_chain_id", "session_id"},
            "knowledge": {"about", "steps", "observation_type", "decay_class", "parent_chain_id", "session_id", "reasoning"},
            "wisdom": {"evidence", "source_type", "steps", "observation_type", "decay_class", "parent_chain_id", "session_id"},
            "intelligence": {"about", "source_type", "observation_type", "decay_class", "session_id"},
            "meta": {"evidence", "source_type", "steps", "decay_class", "parent_chain_id", "session_id", "reasoning"},
            "belief": {"evidence", "source_type", "steps", "observation_type", "decay_class", "parent_chain_id", "reasoning"},
        }
        _passed = {
            "evidence": evidence,
            "source_type": source_type,
            "about": about,
            "reasoning": reasoning,
            "steps": steps,
            "observation_type": observation_type,
            "decay_class": decay_class if decay_class != "standard" else None,
            "parent_chain_id": parent_chain_id,
            "session_id": session_id,
        }
        ignored_flags = [
            k for k, v in _passed.items()
            if v is not None and k in _LAYER_INAPPLICABLE.get(layer, set())
        ]

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

        if result.get("success") is not False and ignored_flags:
            result["ignored_flags"] = ignored_flags

        if result.get("success") is not False and get_settings().write_events_enabled:
            redis = get_redis()
            if redis is not None:
                node_id = result.get("node_id") or result.get("chain_id") or result.get("belief_id")
                if node_id:
                    node_label = _layer_to_label(layer)
                    await emit_access_event(
                        redis, resolved_silo_id, str(node_id), event_type="write", layer=node_label
                    )

        return result
