"""Unit tests for pipelines/assets/clustering.py — no live services required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import dagster as dg

from context_service.pipelines.assets.clustering import clustering, silo_partitions

# clustering has a dg.Nothing typed `custodian_finalize` dep that Dagster's runtime excludes
# from kwargs. We call the underlying decorated function directly so we can provide it.
_clustering_fn = clustering.op.compute_fn.decorated_fn


def _make_context(silo_id: str = "silo-cluster-test") -> dg.AssetExecutionContext:
    ctx = MagicMock(spec=dg.AssetExecutionContext)
    ctx.partition_key = silo_id
    ctx.log = MagicMock()
    return ctx


def test_clustering_uses_shared_silo_partitions() -> None:
    assert silo_partitions.name == "silo_id"


def test_clustering_output_has_required_metadata_keys() -> None:
    ctx = _make_context()
    memgraph_res = MagicMock()
    qdrant_res = MagicMock()
    redis_res = MagicMock()
    llm_res = MagicMock()
    embedding_res = MagicMock()

    with patch("context_service.pipelines.assets.clustering.asyncio.run") as mock_run:
        mock_run.return_value = (12, 3, 10, 0.05)
        result = _clustering_fn(
            ctx,
            memgraph=memgraph_res,
            qdrant=qdrant_res,
            redis=redis_res,
            llm=llm_res,
            embedding=embedding_res,
            custodian_finalize=None,
        )

    assert isinstance(result, dg.Output)
    meta = result.metadata
    for key in (
        "silo_id",
        "clusters_created",
        "hierarchy_levels",
        "embeddings_upserted",
        "cost_usd",
        "duration_s",
    ):
        assert key in meta, f"missing metadata key: {key}"


def test_clustering_output_value_matches_run_result() -> None:
    ctx = _make_context("silo-abc")
    memgraph_res = MagicMock()
    qdrant_res = MagicMock()
    redis_res = MagicMock()
    llm_res = MagicMock()
    embedding_res = MagicMock()

    with patch("context_service.pipelines.assets.clustering.asyncio.run") as mock_run:
        mock_run.return_value = (7, 2, 5, 0.02)
        result = _clustering_fn(
            ctx,
            memgraph=memgraph_res,
            qdrant=qdrant_res,
            redis=redis_res,
            llm=llm_res,
            embedding=embedding_res,
            custodian_finalize=None,
        )

    val = result.value
    assert val["silo_id"] == "silo-abc"
    assert val["clusters_created"] == 7
    assert val["hierarchy_levels"] == 2
    assert val["embeddings_upserted"] == 5
    assert val["cost_usd"] == 0.02
    assert "duration_s" in val


def test_clustering_returns_zeros_when_no_clusters() -> None:
    ctx = _make_context("silo-empty")
    memgraph_res = MagicMock()
    qdrant_res = MagicMock()
    redis_res = MagicMock()
    llm_res = MagicMock()
    embedding_res = MagicMock()

    with patch("context_service.pipelines.assets.clustering.asyncio.run") as mock_run:
        mock_run.return_value = (0, 0, 0, 0.0)
        result = _clustering_fn(
            ctx,
            memgraph=memgraph_res,
            qdrant=qdrant_res,
            redis=redis_res,
            llm=llm_res,
            embedding=embedding_res,
            custodian_finalize=None,
        )

    assert result.value["clusters_created"] == 0
    assert result.value["hierarchy_levels"] == 0
    assert result.value["embeddings_upserted"] == 0


def test_clustering_depends_on_custodian_finalize() -> None:
    """clustering must declare a graph dependency on custodian_finalize."""
    assert any(
        "custodian_finalize" in str(v)
        for v in clustering.keys_by_input_name.values()  # type: ignore[attr-defined]
    ), "clustering must depend on custodian_finalize"
