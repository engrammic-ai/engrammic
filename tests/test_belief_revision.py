"""Unit tests for engine/revision.py — no DB or real LLM/embedder required."""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.engine.revision import (
    REVISION_THRESHOLD,
    _centroid,
    _cosine_distance,
    _make_revised_belief_id,
    check_belief_revision,
    revise_belief,
)
from context_service.engine.synthesis import InsufficientEvidenceError
from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


def test_cosine_distance_identical_vectors() -> None:
    v = [1.0, 0.0, 0.0]
    assert _cosine_distance(v, v) == pytest.approx(0.0)


def test_cosine_distance_orthogonal_vectors() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert _cosine_distance(a, b) == pytest.approx(1.0)


def test_cosine_distance_opposite_vectors() -> None:
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert _cosine_distance(a, b) == pytest.approx(2.0)


def test_cosine_distance_zero_vector_returns_one() -> None:
    assert _cosine_distance([0.0, 0.0], [1.0, 0.5]) == 1.0


def test_centroid_single_vector() -> None:
    v = [1.0, 2.0, 3.0]
    assert _centroid([v]) == v


def test_centroid_two_vectors() -> None:
    result = _centroid([[1.0, 0.0], [0.0, 1.0]])
    assert result == pytest.approx([0.5, 0.5])


def test_centroid_empty_returns_empty() -> None:
    assert _centroid([]) == []


def test_make_revised_belief_id_deterministic() -> None:
    a = _make_revised_belief_id("b-1", 2)
    b = _make_revised_belief_id("b-1", 2)
    assert a == b


def test_make_revised_belief_id_differs_by_count() -> None:
    a = _make_revised_belief_id("b-1", 1)
    b = _make_revised_belief_id("b-1", 2)
    assert a != b


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fact_rows(n: int, confidence: float = 0.9) -> list[dict[str, Any]]:
    return [
        {
            "fact_id": f"fact-{i}",
            "content": f"Fact content {i}",
            "confidence": confidence,
            "valid_from": "2026-01-01T00:00:00+00:00",
        }
        for i in range(n)
    ]


def _unit_vec(dim: int, idx: int) -> list[float]:
    """Return a unit vector of length dim with a 1 at position idx."""
    v = [0.0] * dim
    v[idx] = 1.0
    return v


def _make_embedding_client(vecs: list[list[float]]) -> AsyncMock:
    client = AsyncMock()
    client.embed = AsyncMock(return_value=vecs)
    return client


def _make_llm(response: str = "Revised belief statement.") -> AsyncMock:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=(response, None))
    return llm


def _belief_row(
    belief_id: str = "b-1",
    *,
    centroid: list[float] | None = None,
    revision_count: int = 0,
    wisdom_status: str = "active",
) -> dict[str, Any]:
    return {
        "belief_id": belief_id,
        "content": "Old belief content.",
        "confidence": 0.85,
        "centroid_embedding": centroid,
        "revision_count": revision_count,
        "wisdom_status": wisdom_status,
    }


# ---------------------------------------------------------------------------
# check_belief_revision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_revision_belief_not_found() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])  # belief lookup returns nothing

    client = _make_embedding_client([])
    result = await check_belief_revision(store, "missing", "silo-1", client)

    assert not result.needs_revision
    assert result.reason == "belief_not_found"


@pytest.mark.asyncio
async def test_check_revision_already_stale() -> None:
    store = FakeGraphStore()
    store.seed_query_result([_belief_row(wisdom_status="stale")])

    client = _make_embedding_client([])
    result = await check_belief_revision(store, "b-1", "silo-1", client)

    assert not result.needs_revision
    assert result.reason == "already_stale"


@pytest.mark.asyncio
async def test_check_revision_no_centroid_stored() -> None:
    store = FakeGraphStore()
    store.seed_query_result([_belief_row(centroid=None)])

    client = _make_embedding_client([])
    result = await check_belief_revision(store, "b-1", "silo-1", client)

    assert not result.needs_revision
    assert result.reason == "no_centroid_stored"


@pytest.mark.asyncio
async def test_check_revision_cluster_not_found() -> None:
    store = FakeGraphStore()
    store.seed_query_result([_belief_row(centroid=[1.0, 0.0])])
    store.seed_query_result([])  # cluster lookup returns nothing

    client = _make_embedding_client([])
    result = await check_belief_revision(store, "b-1", "silo-1", client)

    assert not result.needs_revision
    assert result.reason == "cluster_not_found"


@pytest.mark.asyncio
async def test_check_revision_insufficient_facts() -> None:
    store = FakeGraphStore()
    store.seed_query_result([_belief_row(centroid=[1.0, 0.0])])
    store.seed_query_result([{"cluster_id": "c-1"}])
    store.seed_query_result(_make_fact_rows(1))  # fewer than MIN_FACTS_FOR_BELIEF

    client = _make_embedding_client([])
    result = await check_belief_revision(store, "b-1", "silo-1", client)

    assert not result.needs_revision
    assert result.reason == "insufficient_facts"


@pytest.mark.asyncio
async def test_check_revision_within_threshold() -> None:
    # Old centroid and new centroid are identical -> distance = 0
    centroid = [1.0, 0.0, 0.0]
    store = FakeGraphStore()
    store.seed_query_result([_belief_row(centroid=centroid)])
    store.seed_query_result([{"cluster_id": "c-1"}])
    store.seed_query_result(_make_fact_rows(4))

    # Embeddings that reproduce the same centroid
    client = _make_embedding_client([centroid, centroid, centroid, centroid])
    result = await check_belief_revision(store, "b-1", "silo-1", client)

    assert not result.needs_revision
    assert result.reason == "within_threshold"
    assert result.cosine_distance == pytest.approx(0.0, abs=1e-9)


@pytest.mark.asyncio
async def test_check_revision_drift_detected() -> None:
    # Old centroid points in x-direction; new facts embed in y-direction
    old_centroid = _unit_vec(3, 0)  # [1, 0, 0]
    new_vecs = [_unit_vec(3, 1)] * 4  # [0, 1, 0] — orthogonal

    store = FakeGraphStore()
    store.seed_query_result([_belief_row(centroid=old_centroid)])
    store.seed_query_result([{"cluster_id": "c-1"}])
    store.seed_query_result(_make_fact_rows(4))

    client = _make_embedding_client(new_vecs)
    result = await check_belief_revision(store, "b-1", "silo-1", client)

    assert result.needs_revision
    assert result.reason == "drift_detected"
    assert result.cosine_distance == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_check_revision_exactly_at_threshold_not_triggered() -> None:
    # Distance exactly == threshold should NOT trigger revision (strictly greater)
    # Build two vectors whose cosine distance equals REVISION_THRESHOLD exactly.
    angle = math.acos(1.0 - REVISION_THRESHOLD)
    old_centroid = [1.0, 0.0]
    new_centroid = [math.cos(angle), math.sin(angle)]

    store = FakeGraphStore()
    store.seed_query_result([_belief_row(centroid=old_centroid)])
    store.seed_query_result([{"cluster_id": "c-1"}])
    store.seed_query_result(_make_fact_rows(4))

    client = _make_embedding_client([new_centroid] * 4)
    result = await check_belief_revision(store, "b-1", "silo-1", client)

    assert not result.needs_revision


# ---------------------------------------------------------------------------
# revise_belief
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revise_belief_raises_if_belief_missing() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])  # belief not found

    with pytest.raises(ValueError, match="not found"):
        await revise_belief(store, "missing", "silo-1", _make_llm(), _make_embedding_client([]))


@pytest.mark.asyncio
async def test_revise_belief_raises_if_cluster_missing() -> None:
    store = FakeGraphStore()
    store.seed_query_result([_belief_row()])
    store.seed_query_result([])  # no cluster

    with pytest.raises(ValueError, match="No cluster found"):
        await revise_belief(store, "b-1", "silo-1", _make_llm(), _make_embedding_client([]))


@pytest.mark.asyncio
async def test_revise_belief_raises_on_insufficient_facts() -> None:
    store = FakeGraphStore()
    store.seed_query_result([_belief_row()])
    store.seed_query_result([{"cluster_id": "c-1"}])
    store.seed_query_result(_make_fact_rows(1))  # too few

    vecs = [[1.0, 0.0]]
    with pytest.raises(InsufficientEvidenceError):
        await revise_belief(store, "b-1", "silo-1", _make_llm(), _make_embedding_client(vecs))


@pytest.mark.asyncio
async def test_revise_belief_happy_path_write_sequence() -> None:
    """Verify the correct queries are issued in order and with sensible params."""
    facts = _make_fact_rows(4)
    store = FakeGraphStore()
    store.seed_query_result([_belief_row("old-b", revision_count=0)])
    store.seed_query_result([{"cluster_id": "c-x"}])
    store.seed_query_result(facts)
    # Four writes: CREATE_BELIEF_FROM_FACTS, UPDATE_BELIEF_CENTROID,
    #              CREATE_BELIEF_SUPERSEDES, MARK_BELIEF_STALE
    for _ in range(4):
        store.seed_write_result([{"belief_id": "new-b", "edges_created": 4}])

    dim_vecs = [[1.0, 0.0]] * 4
    llm = _make_llm("Revised statement.")
    client = _make_embedding_client(dim_vecs)

    new_id = await revise_belief(store, "old-b", "silo-1", llm, client)

    assert new_id == _make_revised_belief_id("old-b", 1)
    assert len(store.write_log) == 4

    # Write 0: CREATE_BELIEF_FROM_FACTS
    _, p0 = store.write_log[0]
    assert p0["belief_id"] == new_id
    assert p0["silo_id"] == "silo-1"
    assert p0["content"] == "Revised statement."
    assert p0["evidence_count"] == 4

    # Write 1: UPDATE_BELIEF_CENTROID
    _, p1 = store.write_log[1]
    assert p1["belief_id"] == new_id
    assert p1["revision_count"] == 1
    assert len(p1["centroid_embedding"]) == 2

    # Write 2: CREATE_BELIEF_SUPERSEDES
    _, p2 = store.write_log[2]
    assert p2["new_belief_id"] == new_id
    assert p2["old_belief_id"] == "old-b"
    assert p2["reason"] == "evidence_shift"

    # Write 3: MARK_BELIEF_STALE
    _, p3 = store.write_log[3]
    assert p3["belief_id"] == "old-b"
    assert p3["silo_id"] == "silo-1"
    assert "valid_to" in p3


@pytest.mark.asyncio
async def test_revise_belief_increments_revision_count() -> None:
    facts = _make_fact_rows(3)
    store = FakeGraphStore()
    store.seed_query_result([_belief_row("b-orig", revision_count=2)])
    store.seed_query_result([{"cluster_id": "c-1"}])
    store.seed_query_result(facts)
    for _ in range(4):
        store.seed_write_result([])

    vecs = [[0.5, 0.5]] * 3
    new_id = await revise_belief(
        store, "b-orig", "silo-1", _make_llm(), _make_embedding_client(vecs)
    )

    # revision_count should be old (2) + 1 = 3
    assert new_id == _make_revised_belief_id("b-orig", 3)
    _, p1 = store.write_log[1]
    assert p1["revision_count"] == 3
