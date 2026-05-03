"""Direct MCP tool call task functions for evals.

These functions call ContextService methods directly without an LLM agent.
Used as the default mode for quality evaluation.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from context_service.services.context import ContextService
    from context_service.services.models import ScopeContext


async def recall_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
) -> list[dict[str, Any]]:
    """Seed corpus and query, return ranked results.

    inputs:
        corpus: list of {"id": str, "content": str}
        query: str

    returns:
        list of {"id": str, "score": float}
    """
    for doc in inputs["corpus"]:
        await context_service.remember(
            scope=scope,
            content=doc["content"],
            content_type="text",
            metadata={"eval_id": doc["id"]},
        )

    results = await context_service.query(scope, inputs["query"], top_k=10)
    return [
        {
            "id": r.properties.get("eval_id", str(r.node_id))
            if hasattr(r, "properties")
            else str(r.node_id),
            "score": r.relevance_score,
        }
        for r in results
    ]


async def claim_promotion_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
) -> dict[str, Any] | None:
    """Assert a claim and attempt promotion to Fact.

    inputs:
        claim: str
        evidence: list of evidence refs
        confidence: float
        source_tier: str (e.g., "authoritative")

    returns:
        {"id": str, "promoted": bool, "fact_id": str | None}
    """
    node = await context_service.assert_claim(
        scope=scope,
        claim=inputs["claim"],
        evidence=inputs.get("evidence", []),
        source_type="document",
        confidence=inputs.get("confidence", 0.8),
        source_tier=inputs.get("source_tier", "unknown"),
    )

    claim_id = str(node.id)
    silo_id = str(scope.silo_id)

    result = await context_service.promote_claim_to_fact(
        silo_id=silo_id,
        claim_id=claim_id,
        evidence_count=len(inputs.get("evidence", [])),
    )

    return {
        "id": claim_id,
        "promoted": result is not None,
        "fact_id": result.get("id") if result else None,
    }


async def cross_layer_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
) -> dict[str, Any]:
    """Create nodes across layers and verify graph linkage.

    inputs:
        memory_content: str
        claim_content: str

    returns:
        {"memory_id": str, "claim_id": str, "linked": bool}
    """
    memory_node = await context_service.remember(
        scope=scope,
        content=inputs["memory_content"],
        content_type="text",
    )

    claim_node = await context_service.assert_claim(
        scope=scope,
        claim=inputs["claim_content"],
        evidence=[f"node:{memory_node.id}"],
        source_type="document",
        confidence=0.9,
    )

    graph = await context_service.graph_traversal(
        silo_id=str(scope.silo_id),
        seed_nodes=[str(claim_node.id)],
        max_depth=2,
    )

    memory_node_ids = {n["id"] for n in graph.nodes} if graph.nodes else set()

    return {
        "memory_id": str(memory_node.id),
        "claim_id": str(claim_node.id),
        "linked": str(memory_node.id) in memory_node_ids or len(graph.nodes) > 1,
    }


async def freshness_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
) -> list[dict[str, Any]]:
    """Seed docs with different timestamps and query.

    inputs:
        corpus: list of {"id": str, "content": str, "age_days": int}
        query: str

    returns:
        list of {"id": str, "score": float}
    """
    now = datetime.now(UTC)

    for doc in inputs["corpus"]:
        age_days = doc.get("age_days", 0)
        created_at = now - timedelta(days=age_days)
        await context_service.remember(
            scope=scope,
            content=doc["content"],
            content_type="text",
            metadata={
                "eval_id": doc["id"],
                "created_at": created_at.isoformat(),
            },
        )

    results = await context_service.query(scope, inputs["query"], top_k=10)
    return [
        {
            "id": r.properties.get("eval_id", str(r.node_id))
            if hasattr(r, "properties")
            else str(r.node_id),
            "score": r.relevance_score,
        }
        for r in results
    ]


async def provenance_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
) -> dict[str, Any]:
    """Create doc -> claim chain and check provenance.

    inputs:
        doc_content: str
        claim_content: str

    returns:
        {"chain": list, "root_id": str | None, "expected_root": str}
    """
    doc_node = await context_service.remember(
        scope=scope,
        content=inputs["doc_content"],
        content_type="text",
    )

    claim_node = await context_service.assert_claim(
        scope=scope,
        claim=inputs["claim_content"],
        evidence=[f"node:{doc_node.id}"],
        source_type="document",
        confidence=0.9,
    )

    provenance = await context_service.provenance(
        silo_id=str(scope.silo_id),
        node_id=str(claim_node.id),
        max_depth=5,
    )

    chain = [
        {"id": step.node_id, "layer": step.layer, "relationship": step.relationship}
        for step in provenance.chain
    ]
    root_sources = provenance.root_sources
    root_id = root_sources[0]["node_id"] if root_sources else None

    return {
        "chain": chain,
        "root_id": root_id,
        "expected_root": str(doc_node.id),
    }


async def reflection_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
) -> dict[str, Any]:
    """Create node, reflect on it, retrieve reflections.

    inputs:
        content: str
        observation: str
        observation_type: str

    returns:
        {"node_id": str, "reflections": list}
    """
    node = await context_service.remember(
        scope=scope,
        content=inputs["content"],
        content_type="text",
    )

    await context_service.reflect(
        scope=scope,
        observation=inputs["observation"],
        observation_type=inputs.get("observation_type", "insight"),
        about=[str(node.id)],
        agent_id="eval",
    )

    reflections = await context_service.get_reflections(
        silo_id=str(scope.silo_id),
        node_id=str(node.id),
    )

    return {
        "node_id": str(node.id),
        "reflections": [
            {
                "id": r.get("node_id"),
                "observation": r.get("content"),
                "type": r.get("observation_type"),
            }
            for r in reflections
        ],
    }


async def evidence_validation_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
) -> dict[str, Any]:
    """Assert a claim with a mix of valid and invalid evidence refs.

    inputs:
        claim: str
        valid_evidence_contents: list of str -- seeded as memory nodes; their
            node IDs are resolved and passed as evidence
        invalid_evidence_refs: list of str -- raw invalid refs (e.g. "node:bad-uuid")
        confidence: float

    returns:
        {"claim_id": str | None, "error": str | None, "evidence_linked": int}
    """
    valid_ids: list[str] = []
    for content in inputs.get("valid_evidence_contents", []):
        node = await context_service.remember(
            scope=scope,
            content=content,
            content_type="text",
        )
        valid_ids.append(f"node:{node.id}")

    all_evidence = valid_ids + list(inputs.get("invalid_evidence_refs", []))

    try:
        claim_node = await context_service.assert_claim(
            scope=scope,
            claim=inputs["claim"],
            evidence=all_evidence,
            source_type="document",
            confidence=inputs.get("confidence", 0.8),
        )
        return {
            "claim_id": str(claim_node.id),
            "error": None,
            "evidence_linked": len(valid_ids),
        }
    except Exception as exc:
        return {
            "claim_id": None,
            "error": str(exc),
            "evidence_linked": 0,
        }


async def reasoning_coherence_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
) -> dict[str, Any]:
    """Store a reasoning chain and verify it persists correctly.

    inputs:
        steps: list of {"step": int, "reasoning": str, "confidence": float}
        conclusion: str
        crystallizations: list of {"claim": str, "confidence": float} | None

    returns:
        {"chain_id": str, "steps_count": int, "conclusion_stored": bool,
         "crystallizations_count": int}
    """
    from context_service.models.mcp import Crystallization, ReasoningStep

    parsed_steps = [ReasoningStep(**s) for s in inputs["steps"]]
    parsed_crystallizations: list[Crystallization] | None = None
    if inputs.get("crystallizations"):
        parsed_crystallizations = [Crystallization(**c) for c in inputs["crystallizations"]]

    result = await context_service.reason(
        silo_id=str(scope.silo_id),
        steps=parsed_steps,
        conclusion=inputs.get("conclusion"),
        crystallizations=parsed_crystallizations,
        session_id="eval-session",
        agent_id="eval",
    )

    chain_id = str(result.chain_id)

    # Retrieve the stored chain node to verify persistence.
    rows = await context_service._memgraph.execute_query(
        "MATCH (n:ReasoningChain {id: $id}) RETURN n.steps_count AS sc, n.conclusion AS conc",
        {"id": chain_id},
    )
    stored_count = rows[0]["sc"] if rows else 0
    stored_conclusion = rows[0]["conc"] if rows else None

    return {
        "chain_id": chain_id,
        "steps_count": stored_count,
        "conclusion_stored": stored_conclusion == inputs.get("conclusion"),
        "crystallizations_count": len(parsed_crystallizations) if parsed_crystallizations else 0,
    }


async def time_travel_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
) -> dict[str, Any]:
    """Seed nodes at known times and run temporal_query at specified as_of moments.

    inputs:
        content_before: str -- seeded before the checkpoint
        content_after: str -- seeded after the checkpoint (by advancing its
            created_at metadata only; temporal_query uses Memgraph valid_from)
        query: str
        as_of_before_update: bool -- if True query uses t_mid (between the two
            nodes), otherwise uses t_after (should see both)

    returns:
        {"results_count": int, "before_id_found": bool, "after_id_found": bool}
    """
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    t_past = now - timedelta(minutes=10)
    t_future = now + timedelta(minutes=10)

    node_before = await context_service.remember(
        scope=scope,
        content=inputs["content_before"],
        content_type="text",
        metadata={"eval_time_tag": "before"},
    )

    node_after = await context_service.remember(
        scope=scope,
        content=inputs["content_after"],
        content_type="text",
        metadata={"eval_time_tag": "after"},
    )

    as_of = t_past if inputs.get("as_of_before_update") else t_future

    results = await context_service.temporal_query(
        silo_id=str(scope.silo_id),
        as_of=as_of,
        query=inputs["query"],
        top_k=20,
    )

    result_ids = {r["node_id"] for r in results}
    return {
        "results_count": len(results),
        "before_id_found": str(node_before.id) in result_ids,
        "after_id_found": str(node_after.id) in result_ids,
    }


async def link_semantics_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
) -> dict[str, Any]:
    """Create two nodes with a typed link and verify traversal.

    inputs:
        source_content: str
        target_content: str
        relationship: str  (e.g. "SUPPORTS", "CONTRADICTS")
        traversal_depth: int

    returns:
        {"source_id": str, "target_id": str, "edge_id": str,
         "target_reachable": bool, "source_reachable_reverse": bool}
    """
    silo_id = str(scope.silo_id)

    source_node = await context_service.remember(
        scope=scope,
        content=inputs["source_content"],
        content_type="text",
    )
    target_node = await context_service.remember(
        scope=scope,
        content=inputs["target_content"],
        content_type="text",
    )

    edge_id = await context_service.link(
        silo_id=silo_id,
        from_node=str(source_node.id),
        to_node=str(target_node.id),
        relationship=inputs["relationship"],
    )

    depth = inputs.get("traversal_depth", 2)

    # Forward traversal from source.
    forward_graph = await context_service.graph_traversal(
        silo_id=silo_id,
        seed_nodes=[str(source_node.id)],
        max_depth=depth,
    )
    forward_ids = {n["id"] for n in (forward_graph.nodes or [])}

    # Reverse traversal from target.
    reverse_graph = await context_service.graph_traversal(
        silo_id=silo_id,
        seed_nodes=[str(target_node.id)],
        max_depth=depth,
    )
    reverse_ids = {n["id"] for n in (reverse_graph.nodes or [])}

    return {
        "source_id": str(source_node.id),
        "target_id": str(target_node.id),
        "edge_id": edge_id,
        "target_reachable": str(target_node.id) in forward_ids,
        "source_reachable_reverse": str(source_node.id) in reverse_ids,
    }


async def silo_isolation_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope_a: ScopeContext,
    scope_b: ScopeContext,
) -> dict[str, Any]:
    """Store in silo A, query from silo B, verify no leakage.

    inputs:
        content: str
        query: str

    returns:
        {"stored_in": str, "queried_from": str, "found": bool}
    """
    await context_service.remember(
        scope=scope_a,
        content=inputs["content"],
        content_type="text",
    )

    results = await context_service.query(scope_b, inputs["query"], top_k=10)

    return {
        "stored_in": str(scope_a.silo_id),
        "queried_from": str(scope_b.silo_id),
        "found": len(results) > 0,
    }


async def latency_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
) -> dict[str, Any]:
    """Measure wall-clock latency for a named operation.

    inputs:
        operation: str -- one of "context_get_cached", "context_query",
            "context_remember", "context_assert", "context_graph",
            "context_reason"
        seed_content: str | None -- content to seed before measuring
        query: str | None -- query string for context_query

    returns:
        {"operation": str, "elapsed_ms": float}
    """
    from context_service.models.mcp import ReasoningStep

    operation = inputs["operation"]
    silo_id = str(scope.silo_id)

    # Seed a node that multiple operations may need.
    seed_node = await context_service.remember(
        scope=scope,
        content=inputs.get("seed_content", "Latency eval seed node."),
        content_type="text",
    )

    t0 = time.perf_counter()

    if operation == "context_get_cached":
        # First get populates any in-process cache; measure second call.
        await context_service.get(seed_node.id, scope.silo_id)
        t0 = time.perf_counter()
        await context_service.get(seed_node.id, scope.silo_id)

    elif operation == "context_query":
        await context_service.query(scope, inputs.get("query", "latency eval"), top_k=10)

    elif operation == "context_remember":
        t0 = time.perf_counter()
        await context_service.remember(
            scope=scope,
            content="Latency measurement node for context_remember.",
            content_type="text",
        )

    elif operation == "context_assert":
        t0 = time.perf_counter()
        await context_service.assert_claim(
            scope=scope,
            claim="Latency measurement claim for context_assert.",
            evidence=[f"node:{seed_node.id}"],
            source_type="document",
            confidence=0.8,
        )

    elif operation == "context_graph":
        t0 = time.perf_counter()
        await context_service.graph_traversal(
            silo_id=silo_id,
            seed_nodes=[str(seed_node.id)],
            max_depth=2,
        )

    elif operation == "context_reason":
        steps = [
            ReasoningStep(step=1, reasoning="Premise one.", confidence=0.9),
            ReasoningStep(step=2, reasoning="Premise two.", confidence=0.9),
            ReasoningStep(step=3, reasoning="Conclusion follows.", confidence=0.85),
        ]
        t0 = time.perf_counter()
        await context_service.reason(
            silo_id=silo_id,
            steps=steps,
            conclusion="Latency measurement conclusion.",
            session_id="latency-eval",
            agent_id="eval",
        )

    else:
        raise ValueError(f"Unknown operation: {operation!r}")

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return {"operation": operation, "elapsed_ms": elapsed_ms}
