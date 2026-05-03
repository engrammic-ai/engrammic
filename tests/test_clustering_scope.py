"""Tests for clustering layer scoping — layer_labels helper and run_clustering signature."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest
from primitives.protocols import Layer

from context_service.clustering.queries import layer_labels
from context_service.clustering.service import ClusteringService

# --- layer_labels helper ---


def test_layer_labels_knowledge() -> None:
    result = layer_labels([Layer.KNOWLEDGE])
    assert result == "Fact OR Claim"


def test_layer_labels_memory() -> None:
    result = layer_labels([Layer.MEMORY])
    assert result == "Document OR Passage"


def test_layer_labels_multi_layer() -> None:
    result = layer_labels([Layer.MEMORY, Layer.KNOWLEDGE])
    # Should contain all four labels
    assert "Document" in result
    assert "Passage" in result
    assert "Fact" in result
    assert "Claim" in result


def test_layer_labels_wisdom_raises() -> None:
    with pytest.raises(ValueError, match="Wisdom"):
        layer_labels([Layer.WISDOM])


def test_layer_labels_intelligence_raises() -> None:
    with pytest.raises(ValueError, match="Intelligence"):
        layer_labels([Layer.INTELLIGENCE])


def test_layer_labels_empty_raises() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        layer_labels([])


# --- run_clustering signature ---


def test_run_clustering_accepts_target_layers_param() -> None:
    sig = inspect.signature(ClusteringService.run_clustering)
    assert "target_layers" in sig.parameters, "run_clustering must accept target_layers param"


def test_run_clustering_target_layers_defaults_to_none() -> None:
    sig = inspect.signature(ClusteringService.run_clustering)
    param = sig.parameters["target_layers"]
    assert param.default is None


@pytest.mark.asyncio
async def test_run_clustering_defaults_to_knowledge_layer() -> None:
    """When target_layers is None, clustering should only query Knowledge layer nodes."""
    memgraph = MagicMock()
    memgraph.execute_query = AsyncMock(return_value=[])
    memgraph.execute_write = AsyncMock(return_value=[{"deleted": 0}])
    memgraph.transaction = MagicMock()

    llm = MagicMock()
    job_store = MagicMock()
    job_store.save = AsyncMock()

    from context_service.clustering.models import ClusteringJob, ClusteringStatus

    job = ClusteringJob(id="test-job", silo_id="s1", status=ClusteringStatus.PENDING)

    service = ClusteringService(memgraph=memgraph, llm=llm, job_store=job_store)
    await service.run_clustering("s1", job)

    # At minimum, execute_query must have been called (Leiden detection)
    assert memgraph.execute_query.called
    # Verify node_labels param was passed with the correct Knowledge layer labels
    all_calls = memgraph.execute_query.call_args_list
    node_labels_arg: list[str] | None = None
    for call in all_calls:
        args, kwargs = call
        params = args[1] if len(args) > 1 else kwargs.get("params", {})
        if isinstance(params, dict) and "node_labels" in params:
            node_labels_arg = params["node_labels"]
            break
    assert node_labels_arg == ["Fact", "Claim"]
