"""Unit tests for belief synthesis Dagster asset — no live services required."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import dagster as dg

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_belief_synthesis_fn = belief_synthesis_asset.op.compute_fn.decorated_fn


def _make_asset_context(
    silo_id: str = "silo-1",
) -> dg.AssetExecutionContext:
    ctx = MagicMock(spec=dg.AssetExecutionContext)
    ctx.partition_key = silo_id
    ctx.log = MagicMock()
    return ctx


def _make_run_result(succeeded: int = 1, failed: int = 0) -> dict[str, Any]:
    return {
        "succeeded": succeeded,
        "failed": failed,
        "total": succeeded + failed,
        "belief_ids": [f"b-{i}" for i in range(succeeded)],
    }


# ---------------------------------------------------------------------------
# Asset tests
# ---------------------------------------------------------------------------


def test_belief_synthesis_asset_output_keys() -> None:
    ctx = _make_asset_context()
    memgraph_res = MagicMock()
    llm_res = MagicMock()

    with patch.object(_asset_mod, "_run_async", return_value=_make_run_result(succeeded=2)):
        result = _belief_synthesis_fn(ctx, memgraph=memgraph_res, llm=llm_res)

    assert isinstance(result, dg.Output)
    assert result.value["silo_id"] == "silo-1"
    assert result.value["succeeded"] == 2
    assert result.value["failed"] == 0
    assert "duration_s" in result.value


def test_belief_synthesis_asset_metadata_keys() -> None:
    ctx = _make_asset_context()
    memgraph_res = MagicMock()
    llm_res = MagicMock()

    with patch.object(_asset_mod, "_run_async", return_value=_make_run_result()):
        result = _belief_synthesis_fn(ctx, memgraph=memgraph_res, llm=llm_res)

    meta = result.metadata
    for key in ("silo_id", "succeeded", "failed", "total", "duration_s"):
        assert key in meta, f"metadata key {key!r} missing"


def test_belief_synthesis_asset_no_clusters_returns_zero_counts() -> None:
    ctx = _make_asset_context()
    memgraph_res = MagicMock()
    llm_res = MagicMock()

    empty_result = {"succeeded": 0, "failed": 0, "total": 0, "belief_ids": []}

    with patch.object(_asset_mod, "_run_async", return_value=empty_result):
        result = _belief_synthesis_fn(ctx, memgraph=memgraph_res, llm=llm_res)

    assert result.value["succeeded"] == 0
    assert result.value["failed"] == 0
    assert result.value["total"] == 0


def test_belief_synthesis_asset_uses_silo_partition_key() -> None:
    ctx = _make_asset_context(silo_id="silo-custom")
    memgraph_res = MagicMock()
    llm_res = MagicMock()

    with patch.object(_asset_mod, "_run_async", return_value=_make_run_result()):
        result = _belief_synthesis_fn(ctx, memgraph=memgraph_res, llm=llm_res)

    assert result.value["silo_id"] == "silo-custom"


def test_belief_synthesis_asset_has_concurrency_tag() -> None:
    tags: dict[str, str] = {}
    for t in belief_synthesis_asset.tags_by_key.values():
        tags.update(t)
    assert tags.get("dagster/concurrency_key") == "belief_synthesis"


def test_belief_synthesis_asset_has_retry_policy() -> None:
    retry = belief_synthesis_asset.op.retry_policy
    assert retry is not None
    assert retry.max_retries == 1


# Sensor tests removed: belief_synthesis_sensor was deleted as part of the
# SAGE schedule consolidation. Belief synthesis is now triggered by
# sage_synthesizer_schedule rather than a dedicated sensor.
