"""Unit tests for pipelines/assets/custodian_visit.py — no live services required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import dagster as dg

from context_service.pipelines.assets.custodian_visit import custodian_visit, silo_partitions
from context_service.pipelines.resources import MemgraphResource, RedisResource

# custodian_visit has dg.Nothing typed `extraction` and `embedding` deps that Dagster's
# runtime excludes from kwargs. We call the underlying decorated function directly.
_visit_fn = custodian_visit.op.compute_fn.decorated_fn


def _make_context(silo_id: str = "silo-visit-test") -> dg.AssetExecutionContext:
    ctx = MagicMock(spec=dg.AssetExecutionContext)
    ctx.partition_key = silo_id
    ctx.log = MagicMock()
    return ctx


def test_custodian_visit_uses_shared_silo_partitions() -> None:
    assert silo_partitions.name == "silo_id"


def test_custodian_visit_output_has_required_metadata_keys() -> None:
    ctx = _make_context()
    memgraph_res = MagicMock(spec=MemgraphResource)
    redis_res = MagicMock(spec=RedisResource)

    with patch("context_service.pipelines.assets.custodian_visit.asyncio.run") as mock_run:
        mock_run.return_value = (3, 5, 12, 0.02)
        result = _visit_fn(ctx, memgraph=memgraph_res, redis=redis_res, extraction=None, embedding=None)

    assert isinstance(result, dg.Output)
    meta = result.metadata
    for key in ("silo_id", "visits", "commitments_created", "llm_calls", "cost_usd", "duration_s"):
        assert key in meta, f"missing metadata key: {key}"


def test_custodian_visit_output_value_matches_run_result() -> None:
    ctx = _make_context("silo-xyz")
    memgraph_res = MagicMock(spec=MemgraphResource)
    redis_res = MagicMock(spec=RedisResource)

    with patch("context_service.pipelines.assets.custodian_visit.asyncio.run") as mock_run:
        mock_run.return_value = (4, 7, 20, 0.05)
        result = _visit_fn(ctx, memgraph=memgraph_res, redis=redis_res, extraction=None, embedding=None)

    val = result.value
    assert val["silo_id"] == "silo-xyz"
    assert val["visits"] == 4
    assert val["commitments_created"] == 7
    assert val["llm_calls"] == 20
    assert val["cost_usd"] == 0.05


def test_custodian_visit_returns_zeros_when_no_clusters() -> None:
    ctx = _make_context("silo-empty")
    memgraph_res = MagicMock(spec=MemgraphResource)
    redis_res = MagicMock(spec=RedisResource)

    with patch("context_service.pipelines.assets.custodian_visit.asyncio.run") as mock_run:
        mock_run.return_value = (0, 0, 0, 0.0)
        result = _visit_fn(ctx, memgraph=memgraph_res, redis=redis_res, extraction=None, embedding=None)

    assert result.value["visits"] == 0
    assert result.value["commitments_created"] == 0


def test_custodian_visit_depends_on_extraction_and_embedding() -> None:
    """custodian_visit must declare graph dependencies on extraction and embedding assets."""
    dep_keys = [str(v) for v in custodian_visit.keys_by_input_name.values()]  # type: ignore[attr-defined]
    assert any("extraction" in k for k in dep_keys), "custodian_visit must depend on extraction"
    assert any("embedding" in k for k in dep_keys), "custodian_visit must depend on embedding"
