"""MCP tool: context_store - Unified write tool for all EAG layers."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from context_service.api.metrics import record_store_latency
from context_service.config.settings import get_settings
from context_service.engine.exceptions import SupersessionCycleError
from context_service.mcp.server import (
    get_context_service,
    get_evidence_validator,
    get_mcp_auth_context,
    get_mcp_identity_context,
    get_postgres_store,
    get_silo_service,
)
from context_service.models.mcp import (
    Crystallization,
    DecayClass,
    ReasoningStep,
    SourceType,
    SPOClaim,
)
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import (
    commit as brain_commit,
)
from context_service.sage.transactions import (
    store_claim,
    store_memory,
)
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import validate_silo_ownership
from context_service.services.source_tier_resolver import resolve_source_tier

# Query to get embedding for contradiction check
_GET_NODE_EMBEDDING = """
MATCH (n {id: $node_id, silo_id: $silo_id})
RETURN n.embedding AS embedding
"""

logger = structlog.get_logger(__name__)

REASONING_CHAINS_COLLECTION = "reasoning_chains"


async def validate_supersession_target(
    silo_id: str,
    supersedes_id: str,
) -> dict[str, Any] | None:
    """Validate that a supersession target is the current head of its chain.

    Returns None if valid, or an error dict if the target is already superseded.
    The error dict includes head_id so the caller can retry with the correct target.
    """
    ctx_svc = get_context_service()
    try:
        target_uuid = uuid.UUID(supersedes_id)
    except ValueError:
        return {
            "error": "invalid_supersedes_id",
            "message": f"supersedes must be a valid UUID, got: {supersedes_id}",
        }

    head_id = await ctx_svc.graph_store.resolve_current_head(target_uuid, silo_id)
    if head_id is None:
        return {
            "error": "supersedes_not_found",
            "message": f"Node {supersedes_id} not found in silo",
        }

    if head_id != target_uuid:
        return {
            "error": "already_superseded",
            "message": f"Node {supersedes_id} was already superseded",
            "head_id": str(head_id),
            "hint": "Supersede the head node instead",
        }

    return None


async def create_supersession(
    new_node_id: uuid.UUID,
    supersedes_id: str,
    silo_id: str,
    reason: str = "author_update",
) -> bool:
    """Create a SUPERSEDES edge from new_node to supersedes_id.

    Raises SupersessionCycleError if new_node is already downstream in the
    target's supersession chain (which can happen when content-hash dedup
    returns an existing node that's already in the chain).
    """
    from context_service.engine.queries import CHECK_SUPERSESSION_CYCLE

    ctx_svc = get_context_service()

    if str(new_node_id) == supersedes_id:
        raise SupersessionCycleError(f"Cannot supersede self: {new_node_id}")

    result = await ctx_svc.graph_store.execute_query(
        CHECK_SUPERSESSION_CYCLE,
        {
            "target_id": supersedes_id,
            "new_id": str(new_node_id),
            "silo_id": silo_id,
        },
    )
    if result and result[0].get("would_cycle"):
        raise SupersessionCycleError(
            f"Supersession would create cycle: {new_node_id} is already "
            f"downstream of {supersedes_id} in the supersession chain"
        )

    success = await ctx_svc.graph_store.create_supersedes_edge(
        from_id=new_node_id,
        to_id=uuid.UUID(supersedes_id),
        silo_id=silo_id,
        valid_from=datetime.now(UTC),
        source="agent",
        reason=reason,
    )

    # Remove superseded node from Qdrant so it won't be returned in searches
    if success:
        try:
            await ctx_svc.vector_store.delete(supersedes_id)
        except Exception as e:
            # Log but don't fail - the edge is already created
            import structlog

            structlog.get_logger(__name__).warning(
                "supersession_qdrant_delete_failed",
                supersedes_id=supersedes_id,
                error=str(e),
            )

    return success


async def embed(text: str) -> list[float]:
    """Embed text using the configured embedding service."""
    from context_service.embeddings import build_embedding_service

    svc = build_embedding_service()
    return await svc.embed_single(text)


async def _upsert_chain_embedding(
    chain_id: uuid.UUID,
    silo_id: str,
    embedding: list[float],
    evidence_used: list[str] | None = None,
) -> None:
    """Upsert a query embedding for a reasoning chain into Qdrant.

    Creates the reasoning_chains collection on first use.
    Failures are logged but do not propagate — the embedding is
    enhancement metadata, not a hard requirement.

    Args:
        chain_id: The chain's UUID.
        silo_id: Tenant isolation ID.
        embedding: Query embedding vector.
        evidence_used: List of evidence node IDs referenced by this chain (for Layer 3 check).
    """
    from qdrant_client.http import models as qdrant_models
    from qdrant_client.http.exceptions import UnexpectedResponse

    ctx_svc = get_context_service()
    try:
        raw_client = await ctx_svc._qdrant._get_client()
        vector_size = len(embedding)

        # Ensure collection exists.
        collections = await raw_client.get_collections()
        existing = {c.name for c in collections.collections}
        if REASONING_CHAINS_COLLECTION not in existing:
            await raw_client.create_collection(
                collection_name=REASONING_CHAINS_COLLECTION,
                vectors_config=qdrant_models.VectorParams(
                    size=vector_size,
                    distance=qdrant_models.Distance.COSINE,
                ),
            )
            logger.info(
                "reasoning_chains_collection_created",
                collection=REASONING_CHAINS_COLLECTION,
                vector_size=vector_size,
            )

        await raw_client.upsert(
            collection_name=REASONING_CHAINS_COLLECTION,
            points=[
                qdrant_models.PointStruct(
                    id=str(chain_id),
                    vector=embedding,
                    payload={
                        "silo_id": silo_id,
                        "node_id": str(chain_id),
                        "evidence_used": evidence_used or [],
                        # step_embeddings computed async - placeholder for future enhancement
                        "step_embeddings": [],
                    },
                )
            ],
        )
        logger.debug("chain_query_embedding_upserted", chain_id=str(chain_id))
    except UnexpectedResponse as exc:
        logger.warning(
            "chain_query_embedding_upsert_failed",
            chain_id=str(chain_id),
            silo_id=silo_id,
            error=str(exc),
        )
    except Exception as exc:
        logger.warning(
            "chain_query_embedding_upsert_failed",
            chain_id=str(chain_id),
            silo_id=silo_id,
            error=str(exc),
        )


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


_VALID_SOURCE_TIERS = ("authoritative", "validated", "community", "unknown")


async def _context_remember(
    silo_id: str | None,
    content: str,
    content_type: str = "text",
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    decay_class: str = "standard",
    observed_from: str | None = None,
    supersedes: str | None = None,
    memory_type: str | None = None,
    about: list[str] | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    auth = await get_mcp_auth_context()

    if silo_id is not None:
        err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
        if err is not None:
            return err

    validated_silo_id = derive_silo_id(auth.org_id)

    if supersedes is not None:
        err = await validate_supersession_target(str(validated_silo_id), supersedes)
        if err is not None:
            return err

    try:
        DecayClass(decay_class)
    except ValueError:
        return {
            "error": "invalid_decay_class",
            "message": f"decay_class must be one of: {[e.value for e in DecayClass]}",
        }

    ctx_svc = get_context_service()
    identity = await get_mcp_identity_context()
    agent_id = identity.agent_id
    _start = time.perf_counter()

    effective_metadata: dict[str, Any] = dict(metadata or {})
    if observed_from is not None:
        effective_metadata["observed_from"] = observed_from

    result_tx, events = await store_memory(
        store=ctx_svc.graph_store,
        content=content,
        silo_id=str(validated_silo_id),
        agent_id=agent_id,
        layer="memory",
        tags=tags,
        content_type=content_type,
        decay_class=decay_class,
        metadata=effective_metadata,
        session_id=identity.session_id,
        owner_id=identity.agent_id,
        model_id=identity.model_id,
        memory_type=memory_type,
        about=about,
    )

    for event in events:
        await emit_reaction(event)

    record_store_latency(time.perf_counter() - _start, silo_id=validated_silo_id, layer="memory")
    node_id = result_tx.node_id

    if supersedes is not None:
        try:
            await create_supersession(node_id, supersedes, str(validated_silo_id))
        except SupersessionCycleError as e:
            return {
                "error": "supersession_cycle",
                "message": str(e),
                "node_id": str(node_id),
                "supersedes": supersedes,
                "hint": "Content-hash dedup returned a node already in the chain. "
                "Use a different claim text or omit supersedes.",
            }

    memory_vector: list[float] | None = None
    try:
        memory_vector = await embed(content)
        await ctx_svc.vector_store.upsert(
            node_id=str(node_id),
            vector=memory_vector,
            payload={"type": "Document", "layer": "memory", "agent_id": agent_id},
            silo_id=str(validated_silo_id),
        )
    except Exception:
        logger.warning(
            "sync_embedding_failed",
            exc_info=True,
            node_id=str(node_id),
            layer="memory",
        )

    # Cross-agent conflict detection (fire-and-forget)
    if memory_vector:
        try:
            from context_service.engine.conflict_detection import detect_conflicts

            raw_qdrant = await ctx_svc._qdrant._get_client()
            conflict_edge_ids = await detect_conflicts(
                store=ctx_svc.graph_store,
                node_id=str(node_id),
                node_embedding=memory_vector,
                ctx=identity,
                qdrant_client=raw_qdrant,
            )
            if conflict_edge_ids:
                logger.info(
                    "cross_agent_conflicts_detected",
                    node_id=str(node_id),
                    conflict_count=len(conflict_edge_ids),
                    layer="memory",
                )
        except Exception as exc:
            logger.debug("conflict_detection_skipped", error=str(exc), node_id=str(node_id))

    from context_service.services.identity_service import fire_and_forget_identity_writes

    fire_and_forget_identity_writes(
        identity,
        action="asserted",
        target_node_id=str(node_id),
    )

    result: dict[str, Any] = {
        "node_id": str(node_id),
        "layer": "memory",
        "decay_class": decay_class,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if supersedes is not None:
        result["supersedes"] = supersedes
    return result


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
    supersedes: str | None = None,
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

    if supersedes is not None:
        err = await validate_supersession_target(str(expected_silo_id), supersedes)
        if err is not None:
            return err

    try:
        SourceType(source_type)
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
        validation_results = await asyncio.gather(
            *[ev_validator.validate(ev_ref, str(expected_silo_id)) for ev_ref in evidence_list]
        )
        for ev_ref, ev_result in zip(evidence_list, validation_results, strict=True):
            if ev_result.status != "valid":
                return {
                    "error": "invalid_evidence",
                    "evidence": ev_ref,
                    "reason": ev_result.reason,
                }
            if ev_result.node_id:
                evidence_nodes.append(ev_result.node_id)

    identity = await get_mcp_identity_context()
    agent_id = identity.agent_id
    _start = time.perf_counter()
    # Use validated node IDs if available, else fall back to raw refs
    evidence_refs = [f"node:{nid}" for nid in evidence_nodes] if evidence_nodes else evidence_list

    # Resolve source tier if not provided by the caller
    resolved_tier = source_tier
    if resolved_tier is None:
        tier_enum, _resolution_layer = await resolve_source_tier(
            silo_id=str(expected_silo_id),
            evidence_refs=evidence_refs,
            agent_hint=None,
        )
        resolved_tier = tier_enum.value

    subject: str | None = None
    predicate: str | None = None
    object_value: str | None = None
    if isinstance(parsed_claim, SPOClaim):
        claim_text = f"{parsed_claim.subject} {parsed_claim.predicate} {parsed_claim.object}"
        subject = parsed_claim.subject
        predicate = parsed_claim.predicate
        object_value = parsed_claim.object
    else:
        claim_text = parsed_claim

    result, events = await store_claim(
        store=ctx_svc.graph_store,
        content=claim_text,
        evidence_refs=evidence_refs,
        silo_id=str(expected_silo_id),
        agent_id=agent_id,
        source_tier=resolved_tier,
        confidence=confidence,
        tags=tags,
        metadata=metadata,
        supersedes=supersedes,
        subject=subject,
        predicate=predicate,
        object_value=object_value,
        session_id=identity.session_id,
        owner_id=identity.agent_id,
        model_id=identity.model_id,
    )

    for event in events:
        await emit_reaction(event)

    record_store_latency(time.perf_counter() - _start, silo_id=expected_silo_id, layer="knowledge")
    node_id = result.node_id

    claim_vector: list[float] | None = None
    try:
        claim_vector = await embed(claim_text)
        await ctx_svc.vector_store.upsert(
            node_id=str(node_id),
            vector=claim_vector,
            payload={"type": "Claim", "layer": "knowledge", "agent_id": agent_id},
            silo_id=str(expected_silo_id),
        )
    except Exception:
        logger.warning(
            "sync_embedding_failed",
            exc_info=True,
            node_id=str(node_id),
            layer="knowledge",
        )

    # Fetch embedding once for both contradiction and affinity checks
    settings = get_settings()
    node_embedding: list[float] | None = claim_vector
    if node_embedding is None and (
        settings.contradiction_flagging_enabled or settings.affinity_computation_enabled
    ):
        try:
            emb_result = await ctx_svc.graph_store.execute_query(
                _GET_NODE_EMBEDDING,
                {"node_id": str(node_id), "silo_id": str(expected_silo_id)},
            )
            if emb_result and emb_result[0].get("embedding"):
                node_embedding = emb_result[0]["embedding"]
        except Exception as exc:
            logger.debug("embedding_fetch_failed", error=str(exc))

    # Inline contradiction flagging (non-blocking, best-effort)
    contradiction_candidates: list[str] = []
    if settings.contradiction_flagging_enabled and node_embedding:
        try:
            from context_service.engine.contradiction import maybe_flag_contradiction

            raw_qdrant = await ctx_svc._qdrant._get_client()
            contradiction_candidates = await maybe_flag_contradiction(
                store=ctx_svc.graph_store,
                silo_id=str(expected_silo_id),
                node_id=str(node_id),
                embedding=node_embedding,
                qdrant_client=raw_qdrant,
            )
        except Exception as exc:
            logger.debug("contradiction_check_skipped", error=str(exc))

    # Inline affinity computation (non-blocking, best-effort)
    if settings.affinity_computation_enabled and node_embedding:
        try:
            from context_service.engine.affinity import compute_affinities, store_affinity_edges

            raw_client = await ctx_svc._qdrant._get_client()
            collection_name = f"ctx_{expected_silo_id}"
            affinity_edges = await compute_affinities(
                qdrant=raw_client,
                source_id=node_id,
                embedding=node_embedding,
                silo_id=str(expected_silo_id),
                collection_name=collection_name,
                embedding_model=settings.models.litellm_embedding_model,
            )
            if affinity_edges:
                await store_affinity_edges(
                    store=ctx_svc.graph_store,
                    edges=affinity_edges,
                    silo_id=str(expected_silo_id),
                )
        except Exception as exc:
            logger.warning(
                "affinity_computation_failed",
                error=str(exc),
                node_id=str(node_id),
                silo_id=str(expected_silo_id),
            )

    # Cross-agent conflict detection (fire-and-forget)
    if node_embedding:
        try:
            from context_service.engine.conflict_detection import detect_conflicts

            raw_qdrant = await ctx_svc._qdrant._get_client()
            conflict_edge_ids = await detect_conflicts(
                store=ctx_svc.graph_store,
                node_id=str(node_id),
                node_embedding=node_embedding,
                ctx=identity,
                qdrant_client=raw_qdrant,
            )
            if conflict_edge_ids:
                logger.info(
                    "cross_agent_conflicts_detected",
                    node_id=str(node_id),
                    conflict_count=len(conflict_edge_ids),
                    layer="knowledge",
                )
        except Exception as exc:
            logger.debug("conflict_detection_skipped", error=str(exc), node_id=str(node_id))

    from context_service.services.identity_service import fire_and_forget_identity_writes

    fire_and_forget_identity_writes(
        identity,
        action="asserted",
        target_node_id=str(node_id),
    )

    response: dict[str, Any] = {
        "node_id": str(node_id),
        "layer": "knowledge",
        "claim_type": claim_type,
        "evidence_status": "verified" if evidence_mode == "sync" else "pending",
        "evidence_nodes": evidence_nodes,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if supersedes is not None:
        response["supersedes"] = supersedes
    if contradiction_candidates:
        response["contradiction_candidates"] = contradiction_candidates
    return response


async def _context_commit(
    silo_id: str | None,
    belief: str,
    about: list[str],
    confidence: float = 0.8,
    reasoning: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    chain_id: str | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Internal implementation."""
    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()

    if silo_id is not None:
        err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
        if err is not None:
            return err

    expected_silo_id = derive_silo_id(auth.org_id)

    if supersedes is not None:
        err = await validate_supersession_target(str(expected_silo_id), supersedes)
        if err is not None:
            return err

    if not about:
        return {"error": "missing_about", "message": "about must reference at least one node"}

    agent_id = auth.agent_id or auth.org_id

    effective_metadata: dict[str, Any] = dict(metadata or {})
    if reasoning is not None:
        effective_metadata["reasoning"] = reasoning
    if tags:
        effective_metadata["tags"] = tags

    _start = time.perf_counter()
    commit_result, events = await brain_commit(
        store=ctx_svc.graph_store,
        content=belief,
        about_refs=about,
        silo_id=str(expected_silo_id),
        agent_id=agent_id,
        confidence=confidence,
        metadata=effective_metadata or None,
    )
    for event in events:
        await emit_reaction(event)
    record_store_latency(time.perf_counter() - _start, silo_id=expected_silo_id, layer="wisdom")

    result: dict[str, Any] = {
        "node_id": str(commit_result.commitment_id),
        "layer": "wisdom",
        "declared_by": agent_id,
        "about_nodes": about,
        "created_at": commit_result.created_at.isoformat(),
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
                silo_id=str(expected_silo_id),
            )

    if supersedes is not None:
        try:
            await create_supersession(
                commit_result.commitment_id, supersedes, str(expected_silo_id)
            )
            result["supersedes"] = supersedes
        except SupersessionCycleError as e:
            return {
                "error": "supersession_cycle",
                "message": str(e),
                "node_id": str(commit_result.commitment_id),
                "supersedes": supersedes,
                "hint": "Content-hash dedup returned a node already in the chain. "
                "Use a different claim text or omit supersedes.",
            }

    # Inline contradiction flagging for beliefs (non-blocking, best-effort)
    try:
        from context_service.engine.contradiction import maybe_flag_contradiction

        settings = get_settings()
        if settings.contradiction_flagging_enabled:
            emb_result = await ctx_svc.graph_store.execute_query(
                _GET_NODE_EMBEDDING,
                {"node_id": str(commit_result.commitment_id), "silo_id": str(expected_silo_id)},
            )
            if emb_result and emb_result[0].get("embedding"):
                raw_qdrant = await ctx_svc._qdrant._get_client()
                contradiction_candidates = await maybe_flag_contradiction(
                    store=ctx_svc.graph_store,
                    silo_id=str(expected_silo_id),
                    node_id=str(commit_result.commitment_id),
                    embedding=emb_result[0]["embedding"],
                    qdrant_client=raw_qdrant,
                )
                if contradiction_candidates:
                    result["contradiction_candidates"] = contradiction_candidates
    except Exception as exc:
        logger.debug("contradiction_check_skipped", error=str(exc))

    return result


async def _context_reflect(
    silo_id: str | None,
    observation: str,
    observation_type: str,
    about: list[str],
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Internal implementation.

    Deprecated: Use remember(memory_type="reflection", about=[...]) instead.
    """
    import warnings

    warnings.warn(
        'layer="meta" is deprecated. Use remember(memory_type="reflection", about=[...]) instead.',
        DeprecationWarning,
        stacklevel=2,
    )
    logger.warning(
        "deprecated_meta_layer",
        hint='Use remember(memory_type="reflection", about=[...]) instead',
    )
    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()

    if silo_id is not None:
        err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
        if err is not None:
            return err

    expected_silo_id = derive_silo_id(auth.org_id)
    agent_id = auth.agent_id or auth.org_id

    _start = time.perf_counter()
    # ponytail: layer="meta" is deprecated, use memory_type="reflection" instead
    result, events = await store_memory(
        store=ctx_svc.graph_store,
        content=observation,
        silo_id=str(expected_silo_id),
        agent_id=agent_id,
        layer="memory",
        memory_type="reflection",
        about=about,
        metadata={
            **(metadata or {}),
            "confidence": confidence,
            "observation_type": observation_type,
        },
    )

    for event in events:
        await emit_reaction(event)

    record_store_latency(time.perf_counter() - _start, silo_id=expected_silo_id, layer="meta")

    try:
        vector = await embed(observation)
        await ctx_svc.vector_store.upsert(
            node_id=str(result.node_id),
            vector=vector,
            payload={"type": "Memory", "layer": "memory", "memory_type": "reflection"},
            silo_id=str(expected_silo_id),
        )
    except Exception:
        logger.warning(
            "sync_embedding_failed",
            exc_info=True,
            node_id=str(result.node_id),
            layer="meta",
        )

    return {
        "node_id": str(result.node_id),
        "observation_type": observation_type,
        "about_nodes": about,
        "created_at": result.created_at.isoformat(),
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
                silo_id=str(expected_silo_id),
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
                silo_id=str(expected_silo_id),
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

    postgres_store = get_postgres_store()
    saga = ChainSagaWriter(postgres_store, store)

    from context_service.services.models import derive_org_uuid

    _start = time.perf_counter()
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
    record_store_latency(
        time.perf_counter() - _start, silo_id=expected_silo_id, layer="intelligence"
    )

    # Attach query embedding to the chain for Layer 1 applicability matching.
    # Uses conclusion as the query text if no explicit query is available.
    query_text = conclusion
    if query_text:
        try:
            query_embedding = await embed(query_text)
            await _upsert_chain_embedding(
                chain_id,
                str(expected_silo_id),
                query_embedding,
                evidence_used=evidence_used,
            )
        except Exception:
            logger.warning(
                "chain_query_embedding_failed",
                exc_info=True,
                chain_id=str(chain_id),
                silo_id=str(expected_silo_id),
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
                silo_id=str(expected_silo_id),
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
                    silo_id=str(expected_silo_id),
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

    _start = time.perf_counter()
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
    record_store_latency(time.perf_counter() - _start, silo_id=silo_id, layer="belief")

    conflict_rows = await store.execute_query(
        q.DETECT_CONFLICTING_WORKING_HYPOTHESES,
        {"new_belief_id": belief_id, "silo_id": silo_id},
    )
    conflict_ids = [row["conflict_id"] for row in conflict_rows]

    try:
        vector = await embed(content)
        ctx_svc = get_context_service()
        await ctx_svc.vector_store.upsert(
            node_id=belief_id,
            vector=vector,
            payload={"type": "WorkingHypothesis", "layer": "belief"},
            silo_id=silo_id,
        )
    except Exception:
        logger.warning(
            "sync_embedding_failed",
            exc_info=True,
            node_id=belief_id,
            layer="belief",
        )

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
