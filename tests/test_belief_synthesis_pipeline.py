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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_belief_synthesis_fn = belief_synthesis_asset.op.compute_fn.decorated_fn


def _make_asset_context(
    silo_id: str = "silo-1",
    cluster_id: str = "cluster-abc",
) -> dg.AssetExecutionContext:
    ctx = MagicMock(spec=dg.AssetExecutionContext)
    ctx.partition_key = silo_id
    ctx.run_tags = {"cluster_id": cluster_id}
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


# Sensor tests removed: belief_synthesis_sensor was deleted as part of the
# SAGE schedule consolidation. Belief synthesis is now triggered by
# sage_synthesizer_schedule rather than a dedicated sensor.
