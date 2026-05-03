"""Unit tests for partial revision and cascade flagging.

Tests cover:
- partial_revise_belief: splits belief and flags cascade
- flag_cascade: finds referencing beliefs and sets flag
- get_cascade_pending: returns flagged beliefs
- clear_cascade_pending: removes the flag

No DB or real LLM/embedder required.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.engine.revision import (
    PartialRevisionResult,
    clear_cascade_pending,
    flag_cascade,
    get_cascade_pending,
    partial_revise_belief,
)
from tests.fakes.fake_graph_store import FakeGraphStore

SILO = "silo-test"
BELIEF_ID = "belief-aaa"
CHILD_ID_1 = "child-bbb"
CHILD_ID_2 = "child-ccc"
REF_BELIEF_ID = "belief-ddd"


# ---------------------------------------------------------------------------
# flag_cascade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_cascade_no_referencing_beliefs() -> None:
    store = FakeGraphStore()
    # No rows = no downstream beliefs
    count = await flag_cascade(store=store, revised_belief_id=BELIEF_ID, silo_id=SILO)
    assert count == 0
    assert len(store.write_log) == 0


@pytest.mark.asyncio
async def test_flag_cascade_flags_referencing_beliefs() -> None:
    store = FakeGraphStore()
    store.seed_query_result(
        [
            {"belief_id": REF_BELIEF_ID, "content": "downstream belief", "confidence": 0.8, "wisdom_status": "active"},
        ]
    )

    count = await flag_cascade(store=store, revised_belief_id=BELIEF_ID, silo_id=SILO)

    assert count == 1
    assert len(store.write_log) == 1
    cypher, params = store.write_log[0]
    assert "FLAG_CASCADE_PENDING" in cypher or "revision_cascade_pending" in cypher
    assert params["belief_ids"] == [REF_BELIEF_ID]
    assert params["silo_id"] == SILO


@pytest.mark.asyncio
async def test_flag_cascade_multiple_referencing_beliefs() -> None:
    store = FakeGraphStore()
    store.seed_query_result(
        [
            {"belief_id": "b1", "content": "b1 content", "confidence": 0.7, "wisdom_status": "active"},
            {"belief_id": "b2", "content": "b2 content", "confidence": 0.6, "wisdom_status": "active"},
            {"belief_id": "b3", "content": "b3 content", "confidence": 0.9, "wisdom_status": "active"},
        ]
    )

    count = await flag_cascade(store=store, revised_belief_id=BELIEF_ID, silo_id=SILO)

    assert count == 3
    cypher, params = store.write_log[0]
    assert set(params["belief_ids"]) == {"b1", "b2", "b3"}


# ---------------------------------------------------------------------------
# get_cascade_pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cascade_pending_empty() -> None:
    store = FakeGraphStore()
    result = await get_cascade_pending(store=store, silo_id=SILO)
    assert result == []


@pytest.mark.asyncio
async def test_get_cascade_pending_returns_rows() -> None:
    store = FakeGraphStore()
    pending_row: dict[str, Any] = {
        "belief_id": REF_BELIEF_ID,
        "content": "downstream content",
        "confidence": 0.8,
        "cascade_flagged_at": "2026-05-03T00:00:00+00:00",
        "wisdom_status": "active",
    }
    store.seed_query_result([pending_row])

    result = await get_cascade_pending(store=store, silo_id=SILO)

    assert len(result) == 1
    assert result[0]["belief_id"] == REF_BELIEF_ID
    # Verify the query used the correct silo and default limit
    cypher, params = store.query_log[0]
    assert params["silo_id"] == SILO
    assert params["limit"] == 100


@pytest.mark.asyncio
async def test_get_cascade_pending_custom_limit() -> None:
    store = FakeGraphStore()
    await get_cascade_pending(store=store, silo_id=SILO, limit=10)
    cypher, params = store.query_log[0]
    assert params["limit"] == 10


# ---------------------------------------------------------------------------
# clear_cascade_pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_cascade_pending_writes_correct_params() -> None:
    store = FakeGraphStore()
    await clear_cascade_pending(store=store, belief_id=BELIEF_ID, silo_id=SILO)

    assert len(store.write_log) == 1
    cypher, params = store.write_log[0]
    assert "CLEAR_CASCADE_PENDING" in cypher or "cascade_processed_at" in cypher
    assert params["belief_id"] == BELIEF_ID
    assert params["silo_id"] == SILO
    assert "processed_at" in params


# ---------------------------------------------------------------------------
# partial_revise_belief
# ---------------------------------------------------------------------------


def _make_llm_mock(children: list[str]) -> Any:
    raw = json.dumps({"children": children})
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=(raw, {}))
    return llm


def _make_embedding_mock(n: int = 1) -> Any:
    vec = [0.1, 0.2, 0.3]
    embed = AsyncMock()
    embed.embed = AsyncMock(return_value=[[*vec] for _ in range(n)])
    return embed


def _seed_belief(store: FakeGraphStore, content: str = "original belief", confidence: float = 0.8) -> None:
    """Seed execute_query results for split_belief internals."""
    store.seed_query_result(
        [{"belief_id": BELIEF_ID, "content": content, "confidence": confidence, "wisdom_status": "active"}]
    )


@pytest.mark.asyncio
async def test_partial_revise_belief_two_children_no_cascade() -> None:
    store = FakeGraphStore()
    _seed_belief(store)

    # No downstream beliefs referencing this belief
    # split_belief needs: belief fetch -> (write child1, write centroid1, write REVISED_FROM1) per child
    # then partial_revise_belief calls flag_cascade which calls execute_query (returns empty)

    llm = _make_llm_mock(["Revised part.", "Retained part."])
    embed = _make_embedding_mock(1)

    result = await partial_revise_belief(
        store=store,
        belief_id=BELIEF_ID,
        silo_id=SILO,
        revision_note="Some facts changed.",
        llm_client=llm,
        embedding_client=embed,
    )

    assert isinstance(result, PartialRevisionResult)
    assert result.original_belief_id == BELIEF_ID
    assert result.revised_id != result.retained_id
    assert result.cascade_flagged_count == 0


@pytest.mark.asyncio
async def test_partial_revise_belief_single_child_retains_original() -> None:
    """When LLM returns only one child, the original belief is the retained portion."""
    store = FakeGraphStore()
    _seed_belief(store)

    llm = _make_llm_mock(["Only revised portion."])
    embed = _make_embedding_mock(1)

    result = await partial_revise_belief(
        store=store,
        belief_id=BELIEF_ID,
        silo_id=SILO,
        revision_note="Partial change.",
        llm_client=llm,
        embedding_client=embed,
    )

    assert result.retained_id == BELIEF_ID
    assert result.revised_id != BELIEF_ID


@pytest.mark.asyncio
async def test_partial_revise_belief_with_cascade() -> None:
    """Downstream beliefs are flagged when present."""
    store = FakeGraphStore()
    _seed_belief(store)

    # flag_cascade's execute_query call returns one downstream belief
    store.seed_query_result(
        [{"belief_id": REF_BELIEF_ID, "content": "dependent belief", "confidence": 0.7, "wisdom_status": "active"}]
    )

    llm = _make_llm_mock(["Revised.", "Retained."])
    embed = _make_embedding_mock(1)

    result = await partial_revise_belief(
        store=store,
        belief_id=BELIEF_ID,
        silo_id=SILO,
        revision_note="Evidence changed.",
        llm_client=llm,
        embedding_client=embed,
    )

    assert result.cascade_flagged_count == 1
    # Check that FLAG_CASCADE_PENDING write was issued
    flag_writes = [
        (c, p) for c, p in store.write_log
        if "revision_cascade_pending" in c
    ]
    assert len(flag_writes) == 1
    assert flag_writes[0][1]["belief_ids"] == [REF_BELIEF_ID]


@pytest.mark.asyncio
async def test_partial_revise_belief_raises_when_belief_not_found() -> None:
    store = FakeGraphStore()
    # No seed = empty result from execute_query

    llm = _make_llm_mock(["Child."])
    embed = _make_embedding_mock(1)

    with pytest.raises(ValueError, match="not found"):
        await partial_revise_belief(
            store=store,
            belief_id="nonexistent",
            silo_id=SILO,
            revision_note="note",
            llm_client=llm,
            embedding_client=embed,
        )
