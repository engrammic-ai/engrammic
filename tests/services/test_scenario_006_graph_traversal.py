"""Scenario 006 regression: graph traversal across memory/knowledge/wisdom layers.

Verifies BUG-001 fix: context_recall with node_ids=[wisdom_node] and depth=2
must return edges_traversed > 0 and traverse back to memory-layer nodes.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from context_service.services.context import ContextService

MEMORY_ID = "mem-001"
KNOWLEDGE_ID = "know-001"
WISDOM_ID = "wis-001"


def _make_service() -> tuple[ContextService, list[tuple[str, dict[str, Any]]]]:
    captured: list[tuple[str, dict[str, Any]]] = []

    # Simulates the full three-layer node set: wisdom, knowledge, memory
    traversal_rows = [
        {
            "node_id": WISDOM_ID,
            "type": "context",
            "content": "social structures",
            "layer": "wisdom",
            "confidence": 0.9,
        },
        {
            "node_id": KNOWLEDGE_ID,
            "type": "context",
            "content": "evolutionary evidence",
            "layer": "knowledge",
            "confidence": 0.8,
        },
        {
            "node_id": MEMORY_ID,
            "type": "context",
            "content": "laryngeal muscles",
            "layer": "memory",
            "confidence": None,
        },
    ]

    edge_rows = [
        {
            "from_node": WISDOM_ID,
            "to_node": KNOWLEDGE_ID,
            "relationship": "DERIVED_FROM",
            "weight": 1.0,
            "inferred": False,
        },
        {
            "from_node": KNOWLEDGE_ID,
            "to_node": MEMORY_ID,
            "relationship": "DERIVED_FROM",
            "weight": 1.0,
            "inferred": False,
        },
    ]

    async def execute_query(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.append((query, params))
        # Edge query is identified by the MATCH (a:Node {id: nid}) pattern
        if "MATCH (a:Node {id: nid})" in query:
            return edge_rows
        return traversal_rows

    memgraph = MagicMock()
    memgraph.execute_query = AsyncMock(side_effect=execute_query)
    svc = ContextService(memgraph=memgraph, qdrant=MagicMock(), embedding=None, cache=None)
    return svc, captured


async def test_graph_traversal_edges_traversed_nonzero() -> None:
    """edges_traversed must be > 0 when DERIVED_FROM edges exist."""
    svc, _ = _make_service()

    result = await svc.graph_traversal(
        silo_id="silo-test",
        seed_nodes=[WISDOM_ID],
        max_depth=2,
    )

    assert result.edges_traversed > 0, (
        f"BUG-001: edges_traversed={result.edges_traversed}, expected > 0"
    )
    assert result.edges_traversed == 2


async def test_graph_traversal_reaches_memory_layer() -> None:
    """Traversal starting from wisdom must include memory-layer nodes."""
    svc, _ = _make_service()

    result = await svc.graph_traversal(
        silo_id="silo-test",
        seed_nodes=[WISDOM_ID],
        max_depth=2,
    )

    layers_found = {n["layer"] for n in result.nodes}
    assert "memory" in layers_found, (
        f"BUG-001: memory layer not reached; layers found: {layers_found}"
    )
    assert "wisdom" in layers_found


async def test_graph_traversal_includes_all_three_layers() -> None:
    """Full scenario 006: wisdom seed reaches knowledge and memory via depth=2."""
    svc, _ = _make_service()

    result = await svc.graph_traversal(
        silo_id="silo-test",
        seed_nodes=[WISDOM_ID],
        max_depth=2,
    )

    node_ids = {n["node_id"] for n in result.nodes}
    assert WISDOM_ID in node_ids
    assert KNOWLEDGE_ID in node_ids
    assert MEMORY_ID in node_ids

    edge_pairs = {(e["from_node"], e["to_node"]) for e in result.edges}
    assert (WISDOM_ID, KNOWLEDGE_ID) in edge_pairs
    assert (KNOWLEDGE_ID, MEMORY_ID) in edge_pairs
