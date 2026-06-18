"""Unit tests for pipelines/assets/custodian_finalize.py — no live services required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import dagster as dg

from context_service.pipelines.assets.custodian_finalize import custodian_finalize, silo_partitions
from context_service.pipelines.resources import MemgraphResource

_finalize_fn = custodian_finalize.op.compute_fn.decorated_fn


def _make_context(silo_id: str = "silo-finalize-test") -> dg.AssetExecutionContext:
    ctx = MagicMock(spec=dg.AssetExecutionContext)
    ctx.partition_key = silo_id
    ctx.log = MagicMock()
    return ctx


def test_custodian_finalize_uses_shared_silo_partitions() -> None:
    assert silo_partitions.name == "silo_id"


def test_custodian_finalize_output_has_required_metadata_keys() -> None:
    ctx = _make_context()
    memgraph_res = MagicMock(spec=MemgraphResource)

    with patch("context_service.pipelines.assets.custodian_finalize.asyncio.run") as mock_run:
        mock_run.return_value = (5, 3)
        result = _finalize_fn(ctx, memgraph=memgraph_res)

    assert isinstance(result, dg.Output)
    meta = result.metadata
    for key in ("silo_id", "clusters_processed", "findings_created", "duration_s"):
        assert key in meta, f"missing metadata key: {key}"


def test_custodian_finalize_output_value_matches_run_result() -> None:
    ctx = _make_context("silo-abc")
    memgraph_res = MagicMock(spec=MemgraphResource)

    with patch("context_service.pipelines.assets.custodian_finalize.asyncio.run") as mock_run:
        mock_run.return_value = (8, 6)
        result = _finalize_fn(ctx, memgraph=memgraph_res)

    val = result.value
    assert val["silo_id"] == "silo-abc"
    assert val["clusters_processed"] == 8
    assert val["findings_created"] == 6
    assert "duration_s" in val


def test_custodian_finalize_returns_zeros_when_no_promotable_commitments() -> None:
    ctx = _make_context("silo-empty")
    memgraph_res = MagicMock(spec=MemgraphResource)

    with patch("context_service.pipelines.assets.custodian_finalize.asyncio.run") as mock_run:
        mock_run.return_value = (0, 0)
        result = _finalize_fn(ctx, memgraph=memgraph_res)

    assert result.value["clusters_processed"] == 0
    assert result.value["findings_created"] == 0


def test_custodian_finalize_depends_on_claim_to_fact_promotion() -> None:
    """custodian_finalize must declare a graph dependency on claim_to_fact_promotion."""
    assert any(
        "claim_to_fact_promotion" in str(v)
        for v in custodian_finalize.keys_by_input_name.values()  # type: ignore[attr-defined]
    ), "custodian_finalize must depend on claim_to_fact_promotion"
