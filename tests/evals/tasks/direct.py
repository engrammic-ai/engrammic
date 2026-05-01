"""Direct MCP tool call task functions for evals.

These functions call ContextService methods directly without an LLM agent.
Used as the default mode for quality evaluation.
"""

from __future__ import annotations

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
