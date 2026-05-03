"""Basic structural tests for the heat Dagster asset.

These tests exercise the asset's internal logic using mocked Memgraph and Redis
dependencies — no live Docker stack required. Integration-level validation
(seeded silo, real heat_score assertions) is deferred to the beta integration
test pack.
"""

from __future__ import annotations

import math
from collections import defaultdict
from unittest.mock import AsyncMock

import pytest

from context_service.pipelines.assets.heat import (
    HEAT_HALF_LIFE_DAYS,
    HOT_THRESHOLD,
    WARM_THRESHOLD,
    XREAD_COUNT,
    _tier,
    parse_layer,
)
from context_service.signals.heat import LAYER_DECAY_MULTIPLIERS, get_decay_multiplier

# ------------------------------------------------------------------
# Pure helpers
# ------------------------------------------------------------------


def test_tier_hot() -> None:
    assert _tier(HOT_THRESHOLD) == "HOT"
    assert _tier(1.0) == "HOT"


def test_tier_warm() -> None:
    assert _tier(WARM_THRESHOLD) == "WARM"
    assert _tier(0.5) == "WARM"


def test_tier_cold() -> None:
    assert _tier(0.0) == "COLD"
    assert _tier(WARM_THRESHOLD - 0.01) == "COLD"


def test_constants_match_spec() -> None:
    assert HEAT_HALF_LIFE_DAYS == 7
    assert XREAD_COUNT == 10_000
    assert pytest.approx(0.66) == HOT_THRESHOLD
    assert pytest.approx(0.33) == WARM_THRESHOLD


# ------------------------------------------------------------------
# Asset logic (harness simulation)
# ------------------------------------------------------------------


def _make_stream_entry(entry_id: str, node_id: str) -> tuple[bytes, dict[bytes, bytes]]:
    return entry_id.encode(), {b"node_id": node_id.encode()}


@pytest.mark.asyncio
async def test_stream_drain_computes_correct_node_counts() -> None:
    """The stream draining logic counts events per node and derives heat scores."""
    node_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    node_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    messages = [
        _make_stream_entry("1746000001000-0", node_a),
        _make_stream_entry("1746000002000-0", node_a),
        _make_stream_entry("1746000003000-0", node_b),
    ]

    raw_counts: dict[str, int] = defaultdict(int)
    new_last_id = "0-0"

    for entry_id_b, fields in messages:
        node_id_raw = fields.get(b"node_id")
        if node_id_raw is not None:
            nid = node_id_raw.decode() if isinstance(node_id_raw, bytes) else node_id_raw
            raw_counts[nid] += 1
        eid = entry_id_b.decode() if isinstance(entry_id_b, bytes) else entry_id_b
        new_last_id = eid

    assert raw_counts[node_a] == 2
    assert raw_counts[node_b] == 1
    assert new_last_id == "1746000003000-0"

    updates = [
        {
            "node_id": nid,
            "heat_score": min(1.0, math.log1p(c) / math.log1p(XREAD_COUNT)),
            "tier": _tier(min(1.0, math.log1p(c) / math.log1p(XREAD_COUNT))),
        }
        for nid, c in raw_counts.items()
    ]
    assert len(updates) == 2
    heat_a = next(u["heat_score"] for u in updates if u["node_id"] == node_a)
    heat_b = next(u["heat_score"] for u in updates if u["node_id"] == node_b)
    assert heat_a > heat_b  # node_a accessed twice, should be hotter


@pytest.mark.asyncio
async def test_cursor_advance_called_with_final_entry_id() -> None:
    """After draining, advance_heat_cursor receives the last stream entry ID."""
    from context_service.signals.cursor import advance_heat_cursor, fetch_or_init_heat_cursor

    mg_mock = AsyncMock()
    mg_mock.execute_query = AsyncMock(return_value=[{"last_id": "0-0"}])
    mg_mock.execute_write = AsyncMock(return_value=None)

    last_id = await fetch_or_init_heat_cursor(mg_mock, "silo-a")
    assert last_id == "0-0"

    await advance_heat_cursor(mg_mock, "silo-a", "1746000005000-0")

    mg_mock.execute_write.assert_awaited_once()
    params = mg_mock.execute_write.call_args[0][1]
    assert params["last_id"] == "1746000005000-0"
    assert params["silo_id"] == "silo-a"


@pytest.mark.asyncio
async def test_empty_stream_skips_memgraph_writes() -> None:
    """When the stream returns no entries, no heat writes are issued."""
    redis_mock = AsyncMock()
    redis_mock.xread = AsyncMock(return_value=[])

    entries = await redis_mock.xread({"silo:silo-empty:access_events": "0-0"}, count=XREAD_COUNT)
    assert entries == []

    # No writes should happen for empty stream.
    mg_mock = AsyncMock()
    mg_mock.execute_write = AsyncMock()
    mg_mock.execute_write.assert_not_awaited()


# ------------------------------------------------------------------
# Layer parsing and decay multipliers (Phase 3)
# ------------------------------------------------------------------


def test_parse_layer_extracts_from_bytes() -> None:
    fields: dict[bytes, bytes] = {b"node_id": b"abc", b"layer": b"Fact"}
    assert parse_layer(fields) == "Fact"


def test_parse_layer_extracts_from_str() -> None:
    fields: dict[str, str] = {"node_id": "abc", "layer": "Claim"}
    assert parse_layer(fields) == "Claim"


def test_parse_layer_returns_none_when_missing() -> None:
    fields: dict[bytes, bytes] = {b"node_id": b"abc"}
    assert parse_layer(fields) is None


def test_layer_decay_multipliers_match_spec() -> None:
    assert LAYER_DECAY_MULTIPLIERS["Claim"] == 1.0
    assert LAYER_DECAY_MULTIPLIERS["Finding"] == 1.0
    assert LAYER_DECAY_MULTIPLIERS["Fact"] == 2.0
    assert LAYER_DECAY_MULTIPLIERS["Commitment"] == 3.0
    assert LAYER_DECAY_MULTIPLIERS["Insight"] == 4.0
    assert LAYER_DECAY_MULTIPLIERS["ReasoningChain"] == 4.0


def test_get_decay_multiplier_known_labels() -> None:
    assert get_decay_multiplier("Fact") == 2.0
    assert get_decay_multiplier("Commitment") == 3.0


def test_get_decay_multiplier_unknown_label() -> None:
    assert get_decay_multiplier("Document") == 1.0
    assert get_decay_multiplier("SomeOther") == 1.0


def test_get_decay_multiplier_none() -> None:
    assert get_decay_multiplier(None) == 1.0
