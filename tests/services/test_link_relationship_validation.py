"""Regression test for N-003 — ContextService.link() must reject relationship
labels not in the RelationshipType enum so non-MCP callers cannot inject Cypher.
See codebase-review-2026-04-28.md.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.models.mcp import RelationshipType
from context_service.services.context import ContextService


def _make_service() -> ContextService:
    return ContextService(
        memgraph=MagicMock(execute_write=AsyncMock()),
        qdrant=MagicMock(),
        embedding=None,
        cache=None,
    )


@pytest.mark.parametrize(
    "bad_relationship",
    [
        "DROP TABLE foo",
        "REFERENCES]->(x) DELETE x //",
        "references",  # case-sensitive: enum values are uppercase
        "",
        "NOT_AN_ENUM_VALUE",
    ],
)
async def test_link_rejects_invalid_relationship(bad_relationship: str) -> None:
    svc = _make_service()
    with pytest.raises(ValueError, match="Invalid relationship"):
        await svc.link(
            silo_id="s1",
            from_node="n1",
            to_node="n2",
            relationship=bad_relationship,
        )


async def test_link_accepts_each_valid_relationship() -> None:
    svc = _make_service()
    for rel in RelationshipType:
        edge_id = await svc.link(
            silo_id="s1",
            from_node="n1",
            to_node="n2",
            relationship=rel.value,
        )
        assert edge_id
