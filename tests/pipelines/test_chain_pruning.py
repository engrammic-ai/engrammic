"""Tests for chain_pruning Dagster asset.

Mocks all database and store calls so tests run without a live stack.

Note: imports use importlib.util to load the module directly, bypassing the
package __init__ which has a pre-existing Dagster 1.13 incompatibility in
dead_letter_reconciliation.py (from __future__ import annotations + AssetExecutionContext
type hint).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

_MODULE_PATH = (
    pathlib.Path(__file__).parents[2] / "src/context_service/pipelines/assets/chain_pruning.py"
)


def _load_module():
    """Load chain_pruning module directly without going through package __init__."""
    spec = importlib.util.spec_from_file_location(
        "context_service.pipelines.assets.chain_pruning",
        _MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules so relative imports inside the module resolve.
    sys.modules.setdefault("context_service.pipelines.assets.chain_pruning", mod)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _load_module()
chain_pruning = _mod.chain_pruning
_prune_chains = _mod._prune_chains


# ---------------------------------------------------------------------------
# Asset metadata tests
# ---------------------------------------------------------------------------


def test_chain_pruning_group():
    import dagster as dg

    assert isinstance(chain_pruning, dg.AssetsDefinition)
    spec = chain_pruning.specs_by_key[list(chain_pruning.keys)[0]]
    assert spec.group_name == "retention"


# ---------------------------------------------------------------------------
# _prune_chains unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prune_chains_stubs_nodes():
    """Nodes returned by find_stale_chain_interior are stubbed and removed from Qdrant."""
    node_ids = [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]

    mock_store = AsyncMock()
    mock_store.find_stale_chain_interior = AsyncMock(return_value=node_ids)
    mock_store.convert_to_stub = AsyncMock(return_value=True)

    mock_qdrant_store = AsyncMock()
    mock_qdrant_store.delete = AsyncMock()

    mock_memgraph = MagicMock()
    mock_memgraph.store = AsyncMock(return_value=mock_store)

    mock_qdrant = MagicMock()
    mock_qdrant.qdrant_store = MagicMock(return_value=mock_qdrant_store)

    result = await _prune_chains(mock_memgraph, mock_qdrant, "test-silo", max_length=10)

    assert result["stubbed"] == 2
    assert result["failed"] == 0
    assert mock_store.convert_to_stub.await_count == 2
    assert mock_qdrant_store.delete.await_count == 2


@pytest.mark.asyncio
async def test_prune_chains_counts_failures():
    """convert_to_stub returning False increments failed counter."""
    node_ids = ["00000000-0000-0000-0000-000000000001"]

    mock_store = AsyncMock()
    mock_store.find_stale_chain_interior = AsyncMock(return_value=node_ids)
    mock_store.convert_to_stub = AsyncMock(return_value=False)

    mock_qdrant_store = AsyncMock()
    mock_qdrant_store.delete = AsyncMock()

    mock_memgraph = MagicMock()
    mock_memgraph.store = AsyncMock(return_value=mock_store)

    mock_qdrant = MagicMock()
    mock_qdrant.qdrant_store = MagicMock(return_value=mock_qdrant_store)

    result = await _prune_chains(mock_memgraph, mock_qdrant, "test-silo", max_length=10)

    assert result["stubbed"] == 0
    assert result["failed"] == 1
    mock_qdrant_store.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_prune_chains_empty_returns_zeros():
    """No interior nodes returns stubbed=0, failed=0."""
    mock_store = AsyncMock()
    mock_store.find_stale_chain_interior = AsyncMock(return_value=[])

    mock_qdrant_store = AsyncMock()

    mock_memgraph = MagicMock()
    mock_memgraph.store = AsyncMock(return_value=mock_store)

    mock_qdrant = MagicMock()
    mock_qdrant.qdrant_store = MagicMock(return_value=mock_qdrant_store)

    result = await _prune_chains(mock_memgraph, mock_qdrant, "test-silo", max_length=10)

    assert result == {"stubbed": 0, "failed": 0}


@pytest.mark.asyncio
async def test_prune_chains_qdrant_failure_still_counts_stub():
    """A Qdrant delete failure logs a warning but does not increment failed."""
    node_ids = ["00000000-0000-0000-0000-000000000001"]

    mock_store = AsyncMock()
    mock_store.find_stale_chain_interior = AsyncMock(return_value=node_ids)
    mock_store.convert_to_stub = AsyncMock(return_value=True)

    mock_qdrant_store = AsyncMock()
    mock_qdrant_store.delete = AsyncMock(side_effect=RuntimeError("connection refused"))

    mock_memgraph = MagicMock()
    mock_memgraph.store = AsyncMock(return_value=mock_store)

    mock_qdrant = MagicMock()
    mock_qdrant.qdrant_store = MagicMock(return_value=mock_qdrant_store)

    result = await _prune_chains(mock_memgraph, mock_qdrant, "test-silo", max_length=10)

    # Qdrant failure is non-fatal for stub accounting
    assert result["stubbed"] == 1
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_prune_chains_store_exception_increments_failed():
    """An exception from convert_to_stub increments failed."""
    node_ids = ["00000000-0000-0000-0000-000000000001"]

    mock_store = AsyncMock()
    mock_store.find_stale_chain_interior = AsyncMock(return_value=node_ids)
    mock_store.convert_to_stub = AsyncMock(side_effect=RuntimeError("timeout"))

    mock_qdrant_store = AsyncMock()

    mock_memgraph = MagicMock()
    mock_memgraph.store = AsyncMock(return_value=mock_store)

    mock_qdrant = MagicMock()
    mock_qdrant.qdrant_store = MagicMock(return_value=mock_qdrant_store)

    result = await _prune_chains(mock_memgraph, mock_qdrant, "test-silo", max_length=10)

    assert result["stubbed"] == 0
    assert result["failed"] == 1


# ---------------------------------------------------------------------------
# Settings integration
# ---------------------------------------------------------------------------


def test_retention_chain_max_length_setting():
    from context_service.config.settings import get_settings

    settings = get_settings()
    assert settings.retention_supersession_chain_max_length >= 3
