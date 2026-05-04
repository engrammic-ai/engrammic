"""Unit tests for pipelines/assets/chain_stitch.py — no live services required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import dagster as dg

from context_service.pipelines.assets.chain_stitch import chain_stitch, silo_partitions
from context_service.pipelines.resources import MemgraphResource

_stitch_fn = chain_stitch.op.compute_fn.decorated_fn


def _make_context(silo_id: str = "silo-stitch-test") -> dg.AssetExecutionContext:
    ctx = MagicMock(spec=dg.AssetExecutionContext)
    ctx.partition_key = silo_id
    ctx.log = MagicMock()
    return ctx


def test_chain_stitch_uses_shared_silo_partitions() -> None:
    assert silo_partitions.name == "silo_id"


def test_chain_stitch_depends_on_custodian_finalize() -> None:
    input_names = set(chain_stitch.op.input_dict.keys())
    assert "custodian_finalize" in input_names


def test_chain_stitch_output_has_required_metadata_keys() -> None:
    ctx = _make_context()
    memgraph_res = MagicMock(spec=MemgraphResource)

    from context_service.custodian.chain_stitcher import ChainStitchResult

    mock_result = ChainStitchResult(
        silo_id="silo-stitch-test",
        chains_found=2,
        terminals_found=2,
        edges_verified=4,
        errors=[],
    )

    async def _fake_store() -> MagicMock:
        return MagicMock()

    memgraph_res.store = _fake_store

    with patch(
        "context_service.pipelines.assets.chain_stitch.asyncio.run"
    ) as mock_run:
        mock_run.return_value = (
            mock_result.chains_found,
            mock_result.terminals_found,
            mock_result.edges_verified,
            mock_result.errors,
        )
        result = _stitch_fn(ctx, memgraph=memgraph_res, custodian_finalize=None)

    assert isinstance(result, dg.Output)
    for key in ("silo_id", "chains_found", "terminals_found", "edges_verified", "errors", "duration_s"):
        assert key in result.metadata, f"missing metadata key: {key}"


def test_chain_stitch_logs_errors_as_warnings() -> None:
    ctx = _make_context()
    memgraph_res = MagicMock(spec=MemgraphResource)

    with patch(
        "context_service.pipelines.assets.chain_stitch.asyncio.run"
    ) as mock_run:
        mock_run.return_value = (0, 0, 0, ["something went wrong"])
        _stitch_fn(ctx, memgraph=memgraph_res, custodian_finalize=None)

    ctx.log.warning.assert_called_once()
    assert "something went wrong" in ctx.log.warning.call_args[0][0]
