"""Regression test for N-004 — graph_traversal must pass relationship_types
as a list parameter, not a pipe-joined string. See codebase-review-2026-04-28.md.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.services.context import ContextService


@pytest.fixture
def service_capturing_queries() -> tuple[ContextService, list[tuple[str, dict[str, Any]]]]:
    captured: list[tuple[str, dict[str, Any]]] = []

    async def execute_query(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.append((query, params))
        if "MATCH (a:Node {id: nid})" in query:
            return []
        return [
            {
                "node_id": "n1",
                "type": "context",
                "content": "x",
                "layer": "memory",
                "confidence": 1.0,
            },
            {
                "node_id": "n2",
                "type": "context",
                "content": "y",
                "layer": "memory",
                "confidence": 1.0,
            },
        ]

    memgraph = MagicMock()
    memgraph.execute_query = AsyncMock(side_effect=execute_query)
    svc = ContextService(memgraph=memgraph, qdrant=MagicMock(), embedding=None, cache=None)
    return svc, captured


async def test_graph_traversal_passes_rel_types_as_list(
    service_capturing_queries: tuple[ContextService, list[tuple[str, dict[str, Any]]]],
) -> None:
    svc, captured = service_capturing_queries

    await svc.graph_traversal(
        silo_id="s1",
        seed_nodes=["n1"],
        relationship_types=["REFERENCES", "SUPPORTS"],
    )

    edge_calls = [c for c in captured if "MATCH (a:Node {id: nid})" in c[0]]
    assert edge_calls, "edge query was not issued"
    query, params = edge_calls[0]

    assert "$rel_types" in query
    assert "'REFERENCES|SUPPORTS'" not in query
    assert params["rel_types"] == ["REFERENCES", "SUPPORTS"]


async def test_graph_traversal_omits_rel_filter_when_none(
    service_capturing_queries: tuple[ContextService, list[tuple[str, dict[str, Any]]]],
) -> None:
    svc, captured = service_capturing_queries

    await svc.graph_traversal(silo_id="s1", seed_nodes=["n1"])

    edge_calls = [c for c in captured if "MATCH (a:Node {id: nid})" in c[0]]
    assert edge_calls
    query, params = edge_calls[0]
    assert "rel_types" not in params
    assert "type(r) IN" not in query
