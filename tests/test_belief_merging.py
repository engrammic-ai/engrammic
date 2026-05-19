"""Unit tests for belief merging (v1.4 Phase 4a).

Tests cover:
- detect_overlapping_beliefs: returns empty list when < 2 candidates
- detect_overlapping_beliefs: passes correct params to FIND_SIMILAR_BELIEFS
- merge_beliefs: raises ValueError with < 2 sources
- merge_beliefs: unions fact ids from all source beliefs
- merge_beliefs: weighted confidence reconciliation
- merge_beliefs: creates merged belief + MERGED_FROM edges + stales sources
- merge_beliefs: deterministic merged id from source ids
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.engine.synthesis import (
    _make_merged_belief_id,
    detect_overlapping_beliefs,
    merge_beliefs,
)
from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_belief_row(
    belief_id: str,
    content: str = "Some belief content.",
    confidence: float = 0.9,
    fact_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "belief_id": belief_id,
        "content": content,
        "confidence": confidence,
        "fact_ids": fact_ids or [f"{belief_id}-fact-0", f"{belief_id}-fact-1"],
    }


def _make_llm(response: str = "Merged belief statement.") -> AsyncMock:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=(response, None))
    return llm


# ---------------------------------------------------------------------------
# detect_overlapping_beliefs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_overlapping_returns_empty_when_no_candidates() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])

    result = await detect_overlapping_beliefs(store, "silo-1", "climate")

    assert result == []


@pytest.mark.asyncio
async def test_detect_overlapping_returns_empty_when_single_candidate() -> None:
    store = FakeGraphStore()
    store.seed_query_result([_make_belief_row("b-1")])

    result = await detect_overlapping_beliefs(store, "silo-1", "climate")

    assert result == []


@pytest.mark.asyncio
async def test_detect_overlapping_returns_candidates_when_two_or_more() -> None:
    store = FakeGraphStore()
    rows = [_make_belief_row("b-1"), _make_belief_row("b-2")]
    store.seed_query_result(rows)

    result = await detect_overlapping_beliefs(store, "silo-1", "climate")

    assert len(result) == 2
    assert result[0]["belief_id"] == "b-1"


@pytest.mark.asyncio
async def test_detect_overlapping_passes_correct_params() -> None:
    store = FakeGraphStore()
    store.seed_query_result([_make_belief_row("b-1"), _make_belief_row("b-2")])

    await detect_overlapping_beliefs(store, "silo-99", "ocean warming", limit=5)

    cypher, params = store.query_log[0]
    assert "FIND_SIMILAR" in cypher or "Belief" in cypher
    assert params["silo_id"] == "silo-99"
    assert params["subject"] == "ocean warming"
    assert params["limit"] == 5


# ---------------------------------------------------------------------------
# _make_merged_belief_id
# ---------------------------------------------------------------------------


def test_merged_id_deterministic() -> None:
    a = _make_merged_belief_id(["b-1", "b-2"], "silo-1")
    b = _make_merged_belief_id(["b-2", "b-1"], "silo-1")  # order-independent
    assert a == b


def test_merged_id_differs_by_sources() -> None:
    a = _make_merged_belief_id(["b-1", "b-2"], "silo-1")
    b = _make_merged_belief_id(["b-1", "b-3"], "silo-1")
    assert a != b


def test_merged_id_differs_by_silo() -> None:
    a = _make_merged_belief_id(["b-1", "b-2"], "silo-1")
    b = _make_merged_belief_id(["b-1", "b-2"], "silo-2")
    assert a != b


# ---------------------------------------------------------------------------
# merge_beliefs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_beliefs_raises_on_single_source() -> None:
    store = FakeGraphStore()
    llm = _make_llm()

    with pytest.raises(ValueError, match="at least 2"):
        await merge_beliefs(store, "silo-1", [_make_belief_row("b-1")], llm)


@pytest.mark.asyncio
async def test_merge_beliefs_raises_on_empty_sources() -> None:
    store = FakeGraphStore()
    llm = _make_llm()

    with pytest.raises(ValueError, match="at least 2"):
        await merge_beliefs(store, "silo-1", [], llm)


@pytest.mark.asyncio
async def test_merge_beliefs_unions_fact_ids() -> None:
    store = FakeGraphStore()
    store.seed_write_result([{"belief_id": "merged", "edges_created": 4}])
    store.seed_write_result([{"edges_created": 2}])  # MERGED_FROM edges
    store.seed_write_result([{"belief_id": "b-1"}])  # stale b-1
    store.seed_write_result([{"belief_id": "b-2"}])  # stale b-2

    sources = [
        _make_belief_row("b-1", fact_ids=["f-1", "f-2"]),
        _make_belief_row("b-2", fact_ids=["f-2", "f-3"]),  # f-2 shared
    ]
    llm = _make_llm("United belief.")

    await merge_beliefs(store, "silo-1", sources, llm)

    # First write is CREATE_MERGED_BELIEF
    _, params = store.write_log[0]
    assert params["evidence_count"] == 3
    # Second write is CREATE_MERGED_BELIEF_FACT_EDGES - check unioned fact_ids
    _, edge_params = store.write_log[1]
    assert sorted(edge_params["fact_ids"]) == ["f-1", "f-2", "f-3"]


@pytest.mark.asyncio
async def test_merge_beliefs_weighted_confidence() -> None:
    store = FakeGraphStore()
    store.seed_write_result([{"belief_id": "merged", "edges_created": 4}])
    store.seed_write_result([{"edges_created": 2}])
    store.seed_write_result([{"belief_id": "b-1"}])
    store.seed_write_result([{"belief_id": "b-2"}])

    # b-1: confidence 1.0, 1 fact; b-2: confidence 0.5, 3 facts
    # weighted mean = (1.0*1 + 0.5*3) / 4 = 2.5/4 = 0.625
    sources = [
        _make_belief_row("b-1", confidence=1.0, fact_ids=["f-1"]),
        _make_belief_row("b-2", confidence=0.5, fact_ids=["f-2", "f-3", "f-4"]),
    ]
    llm = _make_llm()

    await merge_beliefs(store, "silo-1", sources, llm)

    _, params = store.write_log[0]
    assert abs(params["confidence"] - 0.625) < 1e-9


@pytest.mark.asyncio
async def test_merge_beliefs_creates_merged_from_edges() -> None:
    store = FakeGraphStore()
    store.seed_write_result([{"belief_id": "merged", "edges_created": 2}])
    store.seed_write_result([{"edges_created": 2}])  # fact edges
    store.seed_write_result([{"edges_created": 2}])  # merged_from edges
    store.seed_write_result([{"belief_id": "b-1"}])
    store.seed_write_result([{"belief_id": "b-2"}])

    sources = [_make_belief_row("b-1"), _make_belief_row("b-2")]
    llm = _make_llm()

    merged_id = await merge_beliefs(store, "silo-1", sources, llm)

    # Third write is CREATE_MERGED_FROM_EDGES (after belief + fact edges)
    _, params = store.write_log[2]
    assert params["merged_belief_id"] == merged_id
    assert sorted(params["source_belief_ids"]) == ["b-1", "b-2"]
    assert params["silo_id"] == "silo-1"


@pytest.mark.asyncio
async def test_merge_beliefs_stales_source_beliefs() -> None:
    store = FakeGraphStore()
    store.seed_write_result([{"belief_id": "merged", "edges_created": 2}])
    store.seed_write_result([{"edges_created": 2}])  # fact edges
    store.seed_write_result([{"edges_created": 2}])  # merged_from edges
    store.seed_write_result([{"belief_id": "b-1"}])
    store.seed_write_result([{"belief_id": "b-2"}])

    sources = [_make_belief_row("b-1"), _make_belief_row("b-2")]
    llm = _make_llm()

    await merge_beliefs(store, "silo-1", sources, llm)

    # Writes 4 and 5 are MARK_BELIEF_STALE for each source (after belief, fact edges, merged_from)
    stale_ids = {store.write_log[3][1]["belief_id"], store.write_log[4][1]["belief_id"]}
    assert stale_ids == {"b-1", "b-2"}


@pytest.mark.asyncio
async def test_merge_beliefs_calls_llm_with_facts() -> None:
    store = FakeGraphStore()
    store.seed_write_result([{"belief_id": "merged", "edges_created": 2}])
    store.seed_write_result([{"edges_created": 2}])
    store.seed_write_result([{"belief_id": "b-1"}])
    store.seed_write_result([{"belief_id": "b-2"}])

    sources = [_make_belief_row("b-1"), _make_belief_row("b-2")]
    llm = _make_llm("Merged result.")

    await merge_beliefs(store, "silo-1", sources, llm)

    assert llm.complete.called
    call_args = llm.complete.call_args
    messages = call_args.kwargs.get("messages") or call_args[0][0]
    assert messages[0]["role"] == "system"
    # User prompt should contain the fact contents
    user_msg = messages[1]["content"]
    assert "Facts:" in user_msg


@pytest.mark.asyncio
async def test_merge_beliefs_returns_deterministic_id() -> None:
    store = FakeGraphStore()
    for _ in range(4):
        store.seed_write_result([{"belief_id": "x", "edges_created": 1}])

    sources = [_make_belief_row("b-1"), _make_belief_row("b-2")]
    llm = _make_llm()

    merged_id = await merge_beliefs(store, "silo-1", sources, llm)

    expected = _make_merged_belief_id(["b-1", "b-2"], "silo-1")
    assert merged_id == expected


@pytest.mark.asyncio
async def test_merge_beliefs_content_from_llm() -> None:
    store = FakeGraphStore()
    store.seed_write_result([{"belief_id": "m", "edges_created": 2}])
    store.seed_write_result([{"edges_created": 2}])
    store.seed_write_result([{"belief_id": "b-1"}])
    store.seed_write_result([{"belief_id": "b-2"}])

    sources = [_make_belief_row("b-1"), _make_belief_row("b-2")]
    llm = _make_llm("  LLM merged output.  ")

    await merge_beliefs(store, "silo-1", sources, llm)

    _, params = store.write_log[0]
    assert params["content"] == "LLM merged output."
