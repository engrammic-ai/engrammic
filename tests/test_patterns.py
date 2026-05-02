"""Unit tests for engine/patterns.py — no DB required."""

from __future__ import annotations

from typing import Any

import pytest

from context_service.engine.patterns import (
    DEFAULT_DETECTION_LIMIT,
    DEFAULT_TEMPORAL_WINDOW_SECONDS,
    _make_pattern_id,
    create_or_update_pattern,
    detect_patterns,
)
from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_correlation_rows(n: int) -> list[dict[str, Any]]:
    return [
        {
            "fact_id_a": f"fact-a-{i}",
            "fact_id_b": f"fact-b-{i}",
            "content_a": f"Content A {i}",
            "content_b": f"Content B {i}",
            "valid_from_a": "2026-01-01T00:00:00+00:00",
            "valid_from_b": "2026-01-01T00:05:00+00:00",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# _make_pattern_id
# ---------------------------------------------------------------------------


def test_make_pattern_id_deterministic() -> None:
    a = _make_pattern_id("temporal_correlation", "desc", "silo-1")
    b = _make_pattern_id("temporal_correlation", "desc", "silo-1")
    assert a == b


def test_make_pattern_id_differs_by_type() -> None:
    a = _make_pattern_id("temporal_correlation", "desc", "silo-1")
    b = _make_pattern_id("co_occurrence", "desc", "silo-1")
    assert a != b


def test_make_pattern_id_differs_by_description() -> None:
    a = _make_pattern_id("temporal_correlation", "desc-A", "silo-1")
    b = _make_pattern_id("temporal_correlation", "desc-B", "silo-1")
    assert a != b


def test_make_pattern_id_differs_by_silo() -> None:
    a = _make_pattern_id("temporal_correlation", "desc", "silo-1")
    b = _make_pattern_id("temporal_correlation", "desc", "silo-2")
    assert a != b


# ---------------------------------------------------------------------------
# detect_patterns — temporal_correlation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_patterns_temporal_returns_rows() -> None:
    store = FakeGraphStore()
    rows = _make_correlation_rows(3)
    store.seed_query_result(rows)

    result = await detect_patterns(store, "silo-1", "temporal_correlation")

    assert result == rows
    assert len(store.query_log) == 1
    cypher, params = store.query_log[0]
    assert "Fact" in cypher
    assert params["silo_id"] == "silo-1"
    assert params["window_seconds"] == DEFAULT_TEMPORAL_WINDOW_SECONDS
    assert params["limit"] == DEFAULT_DETECTION_LIMIT


@pytest.mark.asyncio
async def test_detect_patterns_temporal_custom_window() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])

    await detect_patterns(store, "silo-1", "temporal_correlation", window_seconds=300, limit=10)

    _, params = store.query_log[0]
    assert params["window_seconds"] == 300
    assert params["limit"] == 10


@pytest.mark.asyncio
async def test_detect_patterns_temporal_empty_result() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])

    result = await detect_patterns(store, "silo-1", "temporal_correlation")

    assert result == []


# ---------------------------------------------------------------------------
# detect_patterns — unimplemented types return empty list without error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_patterns_co_occurrence_noop() -> None:
    store = FakeGraphStore()
    result = await detect_patterns(store, "silo-1", "co_occurrence")
    assert result == []
    assert store.query_log == []


@pytest.mark.asyncio
async def test_detect_patterns_causal_chain_noop() -> None:
    store = FakeGraphStore()
    result = await detect_patterns(store, "silo-1", "causal_chain")
    assert result == []
    assert store.query_log == []


# ---------------------------------------------------------------------------
# create_or_update_pattern — create path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_pattern_new_node() -> None:
    store = FakeGraphStore()
    # No existing pattern found.
    store.seed_query_result([])
    # CREATE_PATTERN write.
    store.seed_write_result([{"pattern_id": "p-1", "edges_created": 2}])

    pattern_id = await create_or_update_pattern(
        store,
        "temporal_correlation",
        "Facts co-occur within 1 hour",
        ["fact-1", "fact-2"],
        "silo-1",
        confidence=0.85,
    )

    expected_id = _make_pattern_id("temporal_correlation", "Facts co-occur within 1 hour", "silo-1")
    assert pattern_id == expected_id

    # One read (GET_PATTERN_BY_TYPE_AND_SUBJECT) + one write (CREATE_PATTERN)
    assert len(store.query_log) == 1
    assert len(store.write_log) == 1

    _, write_params = store.write_log[0]
    assert write_params["silo_id"] == "silo-1"
    assert write_params["pattern_type"] == "temporal_correlation"
    assert write_params["frequency"] == 1
    assert abs(write_params["confidence"] - 0.85) < 1e-9
    assert sorted(write_params["observed_node_ids"]) == ["fact-1", "fact-2"]


@pytest.mark.asyncio
async def test_create_pattern_sets_description() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])
    store.seed_write_result([{"pattern_id": "p-x", "edges_created": 1}])

    await create_or_update_pattern(
        store,
        "temporal_correlation",
        "My description",
        ["fact-a"],
        "silo-1",
    )

    _, write_params = store.write_log[0]
    assert write_params["description"] == "My description"


# ---------------------------------------------------------------------------
# create_or_update_pattern — update path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_pattern_increments_frequency() -> None:
    store = FakeGraphStore()
    # Existing pattern found.
    store.seed_query_result(
        [
            {
                "pattern_id": "p-existing",
                "description": "Facts co-occur within 1 hour",
                "frequency": 3,
                "confidence": 0.9,
                "first_observed": "2026-01-01T00:00:00+00:00",
                "last_observed": "2026-01-02T00:00:00+00:00",
            }
        ]
    )
    # UPDATE_PATTERN_FREQUENCY write.
    store.seed_write_result([{"pattern_id": "p-existing", "frequency": 4}])

    pattern_id = await create_or_update_pattern(
        store,
        "temporal_correlation",
        "Facts co-occur within 1 hour",
        ["fact-3"],
        "silo-1",
    )

    expected_id = _make_pattern_id("temporal_correlation", "Facts co-occur within 1 hour", "silo-1")
    assert pattern_id == expected_id

    # One read + one write (UPDATE, not CREATE)
    assert len(store.query_log) == 1
    assert len(store.write_log) == 1

    cypher, write_params = store.write_log[0]
    # Should call UPDATE_PATTERN_FREQUENCY, not CREATE_PATTERN
    assert "frequency" in cypher.lower() or "frequency" in str(write_params)
    assert write_params["pattern_id"] == expected_id
    assert write_params["silo_id"] == "silo-1"


# ---------------------------------------------------------------------------
# create_or_update_pattern — query params
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_or_update_pattern_query_params() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])
    store.seed_write_result([{"pattern_id": "p-q", "edges_created": 0}])

    await create_or_update_pattern(
        store,
        "co_occurrence",
        "Some subject",
        [],
        "silo-x",
    )

    _, read_params = store.query_log[0]
    assert read_params["silo_id"] == "silo-x"
    assert read_params["pattern_type"] == "co_occurrence"
    assert read_params["subject"] == "Some subject"
