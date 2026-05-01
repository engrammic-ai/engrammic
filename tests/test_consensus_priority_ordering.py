"""Sensor returns priority-ranked candidates, not (distinct_agents, chain_count)-ranked."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import context_service.custodian.sensors.consensus as _consensus_mod
from context_service.custodian.sensors.consensus import find_consensus_candidates


@pytest.mark.asyncio
async def test_candidates_ranked_by_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """High-confidence candidates rank below low-confidence ones at equal heat / agents."""
    cypher_rows = [
        # high confidence -> low priority despite many agents
        {
            "commitment_id": "cm-high",
            "chain_count": 5,
            "distinct_agents": 5,
            "avg_chain_confidence": 0.95,
        },
        # low confidence -> high priority even with fewer agents
        {
            "commitment_id": "cm-low",
            "chain_count": 2,
            "distinct_agents": 2,
            "avg_chain_confidence": 0.10,
        },
    ]
    memgraph = AsyncMock()
    memgraph.execute_query = AsyncMock(return_value=cypher_rows)

    # Stub heat to a constant so ordering depends solely on confidence + agents.
    async def fake_heat(_mg, _node_id, _silo):
        return 0.5

    monkeypatch.setattr(_consensus_mod, "get_heat", fake_heat)

    rows = await find_consensus_candidates(
        memgraph=memgraph,
        silo_id="silo-a",
        min_chain_count=2,
        min_distinct_agents=2,
        limit=10,
    )

    assert [r["commitment_id"] for r in rows] == ["cm-low", "cm-high"]
    assert all("priority" in r for r in rows)
    assert rows[0]["priority"] > rows[1]["priority"]


@pytest.mark.asyncio
async def test_limit_applied_after_priority_sort(monkeypatch: pytest.MonkeyPatch) -> None:
    cypher_rows = [
        {
            "commitment_id": f"cm-{i}",
            "chain_count": 2,
            "distinct_agents": 2,
            "avg_chain_confidence": c,
        }
        for i, c in enumerate([0.9, 0.1, 0.5, 0.2])
    ]
    memgraph = AsyncMock()
    memgraph.execute_query = AsyncMock(return_value=cypher_rows)

    async def fake_heat(_mg, _node_id, _silo):
        return 0.5

    monkeypatch.setattr(_consensus_mod, "get_heat", fake_heat)

    rows = await find_consensus_candidates(
        memgraph=memgraph,
        silo_id="silo-a",
        min_chain_count=2,
        min_distinct_agents=2,
        limit=2,
    )

    # Top two by priority are the lowest-confidence rows: 0.1 then 0.2.
    assert [r["commitment_id"] for r in rows] == ["cm-1", "cm-3"]
