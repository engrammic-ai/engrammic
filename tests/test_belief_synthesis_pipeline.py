"""Unit tests for belief synthesis Dagster sensor and asset — no live services required."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import dagster as dg
import pytest

# ---------------------------------------------------------------------------
# Module-level bootstrap
#
# We load belief_synthesis.py (asset) directly via file path to avoid
# triggering pipelines/assets/__init__.py, which loads compaction.py.
# compaction.py uses `from __future__ import annotations`, which causes
# Dagster 1.13.2 to fail type-hint resolution for the context parameter —
# this is a pre-existing issue in the codebase unrelated to this feature.
# ---------------------------------------------------------------------------

_SRC = Path(__file__).parent.parent / "src"


def _load_direct(dotted: str) -> Any:
    """Load a module by file path without executing its package __init__."""
    parts = dotted.split(".")
    path = (_SRC / Path(*parts)).with_suffix(".py")
    spec = importlib.util.spec_from_file_location(dotted, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# Load asset module directly (bypasses the broken __init__).
_asset_mod = _load_direct("context_service.pipelines.assets.belief_synthesis")
belief_synthesis_asset: dg.AssetsDefinition = _asset_mod.belief_synthesis_asset

from context_service.pipelines.sensors.belief_synthesis import (  # noqa: E402
    _LIST_DENSE_CLUSTERS_WITHOUT_BELIEF,
    belief_synthesis_sensor,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_belief_synthesis_fn = belief_synthesis_asset.op.compute_fn.decorated_fn
_sensor_raw_fn = belief_synthesis_sensor._raw_fn  # type: ignore[attr-defined]


def _make_asset_context(
    silo_id: str = "silo-1",
    cluster_id: str = "cluster-abc",
) -> dg.AssetExecutionContext:
    ctx = MagicMock(spec=dg.AssetExecutionContext)
    ctx.partition_key = silo_id
    ctx.run_tags = {"cluster_id": cluster_id}
    ctx.log = MagicMock()
    return ctx


def _make_sensor_context(cursor: str | None = None) -> dg.SensorEvaluationContext:
    ctx = MagicMock(spec=dg.SensorEvaluationContext)
    ctx.cursor = cursor
    ctx.log = MagicMock()
    return ctx


# ---------------------------------------------------------------------------
# Asset tests
# ---------------------------------------------------------------------------


def test_belief_synthesis_asset_output_keys() -> None:
    ctx = _make_asset_context()
    memgraph_res = MagicMock()
    llm_res = MagicMock()

    with patch.object(_asset_mod.asyncio, "run", return_value="belief-id-xyz"):
        result = _belief_synthesis_fn(ctx, memgraph=memgraph_res, llm=llm_res)

    assert isinstance(result, dg.Output)
    assert result.value["belief_id"] == "belief-id-xyz"
    assert result.value["cluster_id"] == "cluster-abc"
    assert result.value["silo_id"] == "silo-1"
    assert "duration_s" in result.value


def test_belief_synthesis_asset_metadata_keys() -> None:
    ctx = _make_asset_context()
    memgraph_res = MagicMock()
    llm_res = MagicMock()

    with patch.object(_asset_mod.asyncio, "run", return_value="belief-id-xyz"):
        result = _belief_synthesis_fn(ctx, memgraph=memgraph_res, llm=llm_res)

    meta = result.metadata
    for key in ("silo_id", "cluster_id", "belief_id", "duration_s"):
        assert key in meta, f"metadata key {key!r} missing"


def test_belief_synthesis_asset_raises_without_cluster_id() -> None:
    ctx = MagicMock(spec=dg.AssetExecutionContext)
    ctx.partition_key = "silo-1"
    ctx.run_tags = {}  # no cluster_id
    ctx.log = MagicMock()

    memgraph_res = MagicMock()
    llm_res = MagicMock()

    with pytest.raises(ValueError, match="cluster_id"):
        _belief_synthesis_fn(ctx, memgraph=memgraph_res, llm=llm_res)


def test_belief_synthesis_asset_uses_silo_partition_key() -> None:
    ctx = _make_asset_context(silo_id="silo-custom")
    memgraph_res = MagicMock()
    llm_res = MagicMock()

    with patch.object(_asset_mod.asyncio, "run", return_value="b-1"):
        _belief_synthesis_fn(ctx, memgraph=memgraph_res, llm=llm_res)

    assert ctx.partition_key == "silo-custom"


def test_belief_synthesis_asset_has_concurrency_tag() -> None:
    tags: dict[str, str] = {}
    for t in belief_synthesis_asset.tags_by_key.values():
        tags.update(t)
    assert tags.get("dagster/concurrency_key") == "belief_synthesis"


def test_belief_synthesis_asset_has_retry_policy() -> None:
    retry = belief_synthesis_asset.op.retry_policy
    assert retry is not None
    assert retry.max_retries == 2


# ---------------------------------------------------------------------------
# Sensor tests
# ---------------------------------------------------------------------------


def test_belief_synthesis_sensor_no_triggers_returns_empty() -> None:
    ctx = _make_sensor_context()
    memgraph_res = MagicMock()

    with patch(
        "context_service.pipelines.sensors.belief_synthesis.asyncio.run",
        side_effect=lambda _coro: [],
    ):
        result = _sensor_raw_fn(ctx, memgraph=memgraph_res)

    assert isinstance(result, dg.SensorResult)
    assert result.run_requests == []


def test_belief_synthesis_sensor_emits_run_request_per_cluster() -> None:
    ctx = _make_sensor_context()
    memgraph_res = MagicMock()

    triggers = [
        {"silo_id": "silo-1", "cluster_id": "c-1", "fact_count": 5},
        {"silo_id": "silo-1", "cluster_id": "c-2", "fact_count": 4},
    ]

    with patch(
        "context_service.pipelines.sensors.belief_synthesis.asyncio.run",
        return_value=triggers,
    ):
        result = _sensor_raw_fn(ctx, memgraph=memgraph_res)

    assert len(result.run_requests) == 2
    run_keys = {r.run_key for r in result.run_requests}
    assert "belief_synthesis:silo-1:c-1" in run_keys
    assert "belief_synthesis:silo-1:c-2" in run_keys


def test_belief_synthesis_sensor_tags_cluster_id_on_run_request() -> None:
    ctx = _make_sensor_context()
    memgraph_res = MagicMock()

    triggers = [{"silo_id": "silo-1", "cluster_id": "c-99", "fact_count": 7}]

    with patch(
        "context_service.pipelines.sensors.belief_synthesis.asyncio.run",
        return_value=triggers,
    ):
        result = _sensor_raw_fn(ctx, memgraph=memgraph_res)

    req = result.run_requests[0]
    assert req.tags.get("cluster_id") == "c-99"
    assert req.partition_key == "silo-1"


def test_belief_synthesis_sensor_cursor_records_seen_clusters() -> None:
    ctx = _make_sensor_context()
    memgraph_res = MagicMock()

    triggers = [{"silo_id": "silo-x", "cluster_id": "c-seen", "fact_count": 3}]

    with patch(
        "context_service.pipelines.sensors.belief_synthesis.asyncio.run",
        return_value=triggers,
    ):
        result = _sensor_raw_fn(ctx, memgraph=memgraph_res)

    import json

    cursor_data = json.loads(result.cursor)
    assert "c-seen" in cursor_data.get("silo-x", [])


def test_belief_synthesis_sensor_skips_already_seen_clusters() -> None:
    """Clusters already recorded in the cursor must not generate new run requests."""
    import json

    existing_cursor = json.dumps({"silo-1": ["c-old"]})
    ctx = _make_sensor_context(cursor=existing_cursor)
    memgraph_res = MagicMock()

    with patch(
        "context_service.pipelines.sensors.belief_synthesis.asyncio.run",
        return_value=[],
    ):
        result = _sensor_raw_fn(ctx, memgraph=memgraph_res)

    assert result.run_requests == []


def test_belief_synthesis_sensor_query_threshold() -> None:
    """The density query references $min_facts and excludes covered clusters."""
    from context_service.engine.synthesis import MIN_FACTS_FOR_BELIEF

    assert ">= $min_facts" in _LIST_DENSE_CLUSTERS_WITHOUT_BELIEF
    assert "SYNTHESIZED_FROM" in _LIST_DENSE_CLUSTERS_WITHOUT_BELIEF
    assert MIN_FACTS_FOR_BELIEF == 3


def test_belief_synthesis_sensor_registered_in_all_sensors() -> None:
    from context_service.pipelines.sensors import all_sensors

    names = [s.name for s in all_sensors]
    assert "belief_synthesis_sensor" in names
