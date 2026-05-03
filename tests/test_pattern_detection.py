"""Unit tests for v1.3a pattern detection — co_occurrence, causal_chain, and decay.

No DB required; all tests use FakeGraphStore.
"""

from __future__ import annotations

from typing import Any

import pytest

from context_service.engine.patterns import (
    CAUSAL_CHAIN_MIN_HOPS,
    DEFAULT_DECAY_FACTOR,
    DEFAULT_DETECTION_LIMIT,
    DEFAULT_MIN_CONFIDENCE,
    _description_for_causal_chain,
    _description_for_co_occurrence,
    _make_pattern_id,
    decay_patterns,
    detect_patterns,
    process_causal_chain_candidates,
    process_co_occurrence_candidates,
)
from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _co_occurrence_rows(n: int, cluster_id: str = "cluster-1") -> list[dict[str, Any]]:
    return [
        {
            "fact_id_a": f"fact-a-{i}",
            "fact_id_b": f"fact-b-{i}",
            "content_a": f"Content A {i}",
            "content_b": f"Content B {i}",
            "cluster_id": cluster_id,
        }
        for i in range(n)
    ]


def _causal_chain_rows(n: int, *, length: int = 2) -> list[dict[str, Any]]:
    return [
        {
            "chain_start": f"node-start-{i}",
            "chain_end": f"node-end-{i}",
            "chain_node_ids": [f"node-start-{i}", f"node-mid-{i}", f"node-end-{i}"],
            "chain_length": length,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# detect_patterns — co_occurrence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_co_occurrence_queries_db() -> None:
    store = FakeGraphStore()
    rows = _co_occurrence_rows(3)
    store.seed_query_result(rows)

    result = await detect_patterns(store, "silo-1", "co_occurrence")

    assert result == rows
    assert len(store.query_log) == 1
    cypher, params = store.query_log[0]
    assert "MEMBER_OF" in cypher
    assert params["silo_id"] == "silo-1"
    assert params["limit"] == DEFAULT_DETECTION_LIMIT


@pytest.mark.asyncio
async def test_detect_co_occurrence_custom_limit() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])

    await detect_patterns(store, "silo-1", "co_occurrence", limit=5)

    _, params = store.query_log[0]
    assert params["limit"] == 5


@pytest.mark.asyncio
async def test_detect_co_occurrence_empty_result() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])

    result = await detect_patterns(store, "silo-1", "co_occurrence")

    assert result == []


# ---------------------------------------------------------------------------
# detect_patterns — causal_chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_causal_chain_queries_db() -> None:
    store = FakeGraphStore()
    rows = _causal_chain_rows(2)
    store.seed_query_result(rows)

    result = await detect_patterns(store, "silo-1", "causal_chain")

    assert result == rows
    assert len(store.query_log) == 1
    cypher, params = store.query_log[0]
    assert "CAUSES" in cypher
    assert f"*{CAUSAL_CHAIN_MIN_HOPS}.." in cypher
    assert params["silo_id"] == "silo-1"
    assert params["limit"] == DEFAULT_DETECTION_LIMIT


@pytest.mark.asyncio
async def test_detect_causal_chain_empty_result() -> None:
    store = FakeGraphStore()
    store.seed_query_result([])

    result = await detect_patterns(store, "silo-1", "causal_chain")

    assert result == []


# ---------------------------------------------------------------------------
# _description_for_co_occurrence — symmetry
# ---------------------------------------------------------------------------


def test_co_occurrence_description_symmetric() -> None:
    row_ab = {
        "fact_id_a": "a",
        "fact_id_b": "b",
        "content_a": "alpha",
        "content_b": "beta",
        "cluster_id": "c1",
    }
    row_ba = {
        "fact_id_a": "b",
        "fact_id_b": "a",
        "content_a": "beta",
        "content_b": "alpha",
        "cluster_id": "c1",
    }
    assert _description_for_co_occurrence(row_ab) == _description_for_co_occurrence(row_ba)


def test_co_occurrence_description_includes_cluster() -> None:
    row = {
        "fact_id_a": "a",
        "fact_id_b": "b",
        "content_a": "x",
        "content_b": "y",
        "cluster_id": "my-cluster",
    }
    desc = _description_for_co_occurrence(row)
    assert "my-cluster" in desc


# ---------------------------------------------------------------------------
# _description_for_causal_chain
# ---------------------------------------------------------------------------


def test_causal_chain_description_includes_length() -> None:
    row = {
        "chain_start": "s",
        "chain_end": "e",
        "chain_node_ids": ["s", "m", "e"],
        "chain_length": 3,
    }
    desc = _description_for_causal_chain(row)
    assert "len3" in desc
    assert "s" in desc
    assert "e" in desc


# ---------------------------------------------------------------------------
# process_co_occurrence_candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_co_occurrence_creates_patterns() -> None:
    store = FakeGraphStore()
    candidates = _co_occurrence_rows(2)

    # Each call to create_or_update_pattern: 1 query (GET) + 1 write (CREATE)
    for _ in candidates:
        store.seed_query_result([])  # no existing pattern
        store.seed_write_result([{"pattern_id": "p", "edges_created": 2}])

    count = await process_co_occurrence_candidates(store, "silo-1", candidates)

    assert count == 2
    assert len(store.write_log) == 2


@pytest.mark.asyncio
async def test_process_co_occurrence_empty_candidates() -> None:
    store = FakeGraphStore()
    count = await process_co_occurrence_candidates(store, "silo-1", [])
    assert count == 0
    assert store.write_log == []


# ---------------------------------------------------------------------------
# process_causal_chain_candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_causal_chain_creates_patterns() -> None:
    store = FakeGraphStore()
    candidates = _causal_chain_rows(2, length=2)

    for _ in candidates:
        store.seed_query_result([])
        store.seed_write_result([{"pattern_id": "p", "edges_created": 3}])

    count = await process_causal_chain_candidates(store, "silo-1", candidates)

    assert count == 2
    assert len(store.write_log) == 2


@pytest.mark.asyncio
async def test_process_causal_chain_skips_short_chains() -> None:
    """Chains with chain_length < 2 (fewer than 3 nodes) are filtered out."""
    store = FakeGraphStore()
    # chain_length=1 means only 2 nodes — not a proper chain.
    candidates = _causal_chain_rows(3, length=1)

    count = await process_causal_chain_candidates(store, "silo-1", candidates)

    assert count == 0
    assert store.write_log == []


@pytest.mark.asyncio
async def test_process_causal_chain_uses_node_id_list() -> None:
    """The OBSERVED_IN edges should use chain_node_ids, not just start/end."""
    store = FakeGraphStore()
    candidates = [
        {
            "chain_start": "s",
            "chain_end": "e",
            "chain_node_ids": ["s", "m1", "m2", "e"],
            "chain_length": 3,
        }
    ]
    store.seed_query_result([])
    store.seed_write_result([{"pattern_id": "p", "edges_created": 4}])

    await process_causal_chain_candidates(store, "silo-1", candidates)

    _, write_params = store.write_log[0]
    assert write_params["observed_node_ids"] == ["s", "m1", "m2", "e"]


# ---------------------------------------------------------------------------
# decay_patterns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decay_patterns_calls_both_queries() -> None:
    store = FakeGraphStore()
    store.seed_write_result([{"patterns_decayed": 3}])
    store.seed_write_result([{"patterns_tombstoned": 1}])

    decayed, tombstoned = await decay_patterns(
        store,
        "silo-1",
        stale_before_iso="2026-04-01T00:00:00+00:00",
    )

    assert decayed == 3
    assert tombstoned == 1
    assert len(store.write_log) == 2

    decay_cypher, decay_params = store.write_log[0]
    assert "confidence" in decay_cypher.lower()
    assert decay_params["silo_id"] == "silo-1"
    assert decay_params["decay_factor"] == DEFAULT_DECAY_FACTOR
    assert decay_params["stale_before"] == "2026-04-01T00:00:00+00:00"

    tomb_cypher, tomb_params = store.write_log[1]
    assert "tombstoned" in tomb_cypher.lower()
    assert tomb_params["min_confidence"] == DEFAULT_MIN_CONFIDENCE


@pytest.mark.asyncio
async def test_decay_patterns_custom_factor() -> None:
    store = FakeGraphStore()
    store.seed_write_result([{"patterns_decayed": 0}])
    store.seed_write_result([{"patterns_tombstoned": 0}])

    await decay_patterns(
        store,
        "silo-x",
        decay_factor=0.5,
        stale_before_iso="2026-01-01T00:00:00+00:00",
        min_confidence=0.2,
    )

    _, decay_params = store.write_log[0]
    assert decay_params["decay_factor"] == 0.5

    _, tomb_params = store.write_log[1]
    assert tomb_params["min_confidence"] == 0.2


@pytest.mark.asyncio
async def test_decay_patterns_zero_results() -> None:
    store = FakeGraphStore()
    # Empty results (no patterns to decay)
    store.seed_write_result([])
    store.seed_write_result([])

    decayed, tombstoned = await decay_patterns(
        store,
        "silo-1",
        stale_before_iso="2026-01-01T00:00:00+00:00",
    )

    assert decayed == 0
    assert tombstoned == 0


# ---------------------------------------------------------------------------
# Feature flag: ensure detect_patterns still works when flag is off
# (the flag is enforced at the asset layer, not engine layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_patterns_co_occurrence_no_flag_needed() -> None:
    """engine/patterns.py does not check the feature flag; the asset does."""
    store = FakeGraphStore()
    rows = _co_occurrence_rows(1)
    store.seed_query_result(rows)

    result = await detect_patterns(store, "silo-1", "co_occurrence")

    assert result == rows


# ---------------------------------------------------------------------------
# pattern_id stability across calls
# ---------------------------------------------------------------------------


def test_pattern_id_stable_co_occurrence() -> None:
    desc = _description_for_co_occurrence(
        {
            "fact_id_a": "a",
            "fact_id_b": "b",
            "content_a": "x",
            "content_b": "y",
            "cluster_id": "c",
        }
    )
    pid_1 = _make_pattern_id("co_occurrence", desc, "silo-1")
    pid_2 = _make_pattern_id("co_occurrence", desc, "silo-1")
    assert pid_1 == pid_2


def test_pattern_id_stable_causal_chain() -> None:
    desc = _description_for_causal_chain(
        {"chain_start": "s", "chain_end": "e", "chain_node_ids": ["s", "e"], "chain_length": 2}
    )
    pid_1 = _make_pattern_id("causal_chain", desc, "silo-1")
    pid_2 = _make_pattern_id("causal_chain", desc, "silo-1")
    assert pid_1 == pid_2
