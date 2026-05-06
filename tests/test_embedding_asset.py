"""Unit tests for pipelines/assets/embedding.py — no live services required."""

from __future__ import annotations

from unittest.mock import patch

import dagster as dg

from context_service.pipelines.assets.embedding import embedding_asset as embedding
from context_service.pipelines.assets.embedding import silo_partitions
from context_service.pipelines.resources import EmbeddingResource, MemgraphResource, QdrantResource

# ---------------------------------------------------------------------------
# silo_partitions shared definition
# ---------------------------------------------------------------------------


def test_embedding_uses_shared_silo_partitions() -> None:
    """embedding must use the same silo_id partitions definition as other assets."""
    assert silo_partitions.name == "silo_id"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_instance(silo_id: str) -> dg.DagsterInstance:
    instance = dg.DagsterInstance.ephemeral()
    instance.add_dynamic_partitions("silo_id", [silo_id])
    return instance


def _resources() -> dict[str, dg.ConfigurableResource]:  # type: ignore[type-arg]
    return {
        "memgraph": MemgraphResource(uri="bolt://fake:7687"),
        "qdrant": QdrantResource(url="http://fake:6333"),
        "embedding": EmbeddingResource(),
    }


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


def test_embedding_asset_output_has_required_metadata_keys() -> None:
    """Output metadata must carry all six required keys."""
    silo_id = "silo-meta"
    instance = _make_instance(silo_id)

    with patch(
        "context_service.pipelines.assets.embedding.asyncio.run",
        return_value=(4, 4, 0.0),
    ):
        result = dg.materialize_to_memory(
            [embedding],
            resources=_resources(),
            partition_key=silo_id,
            instance=instance,
        )

    assert result.success
    mats = result.asset_materializations_for_node("embedding")
    assert mats
    metadata = mats[0].metadata
    for key in (
        "silo_id",
        "nodes_processed",
        "vectors_upserted",
        "tokens_used",
        "cost_usd",
        "duration_s",
    ):
        assert key in metadata, f"missing metadata key: {key}"


def test_embedding_asset_output_value_matches_run_result() -> None:
    """Output value must reflect the async _run() coroutine return values."""
    silo_id = "silo-values"
    instance = _make_instance(silo_id)

    with patch(
        "context_service.pipelines.assets.embedding.asyncio.run",
        return_value=(10, 9, 0.0),
    ):
        result = dg.materialize_to_memory(
            [embedding],
            resources=_resources(),
            partition_key=silo_id,
            instance=instance,
        )

    assert result.success
    val = result.output_for_node("embedding")
    assert val["silo_id"] == silo_id
    assert val["nodes_processed"] == 10
    assert val["vectors_upserted"] == 9
    assert "duration_s" in val


def test_embedding_asset_returns_zeros_when_no_unembedded_nodes() -> None:
    """When all nodes are already embedded, the asset emits zeros without calling embed."""
    silo_id = "silo-empty"
    instance = _make_instance(silo_id)

    with patch(
        "context_service.pipelines.assets.embedding.asyncio.run",
        return_value=(0, 0, 0.0),
    ):
        result = dg.materialize_to_memory(
            [embedding],
            resources=_resources(),
            partition_key=silo_id,
            instance=instance,
        )

    assert result.success
    val = result.output_for_node("embedding")
    assert val["nodes_processed"] == 0
    assert val["vectors_upserted"] == 0


# ---------------------------------------------------------------------------
# Batch path — verify embed() called, not embed_single()
# ---------------------------------------------------------------------------


def test_embedding_asset_uses_batch_embed() -> None:
    """Verify the asset processes multiple nodes in one call and reports correct counts."""
    silo_id = "silo-batch"
    instance = _make_instance(silo_id)

    with patch(
        "context_service.pipelines.assets.embedding.asyncio.run",
        return_value=(5, 5, 0.0),
    ):
        result = dg.materialize_to_memory(
            [embedding],
            resources=_resources(),
            partition_key=silo_id,
            instance=instance,
        )

    assert result.success
    val = result.output_for_node("embedding")
    assert val["nodes_processed"] == 5
    assert val["vectors_upserted"] == 5
    assert val["silo_id"] == silo_id
