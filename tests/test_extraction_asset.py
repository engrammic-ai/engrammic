"""Unit tests for pipelines/assets/extraction.py — no live services required."""

from __future__ import annotations

from unittest.mock import patch

import dagster as dg

from context_service.pipelines.assets.extraction import _stable_entity_id
from context_service.pipelines.resources import LLMResource, MemgraphResource, RedisResource

# ---------------------------------------------------------------------------
# _stable_entity_id
# ---------------------------------------------------------------------------


def test_stable_entity_id_deterministic() -> None:
    a = _stable_entity_id("silo-1", "Alice")
    b = _stable_entity_id("silo-1", "Alice")
    assert a == b
    assert len(a) == 32


def test_stable_entity_id_case_insensitive() -> None:
    a = _stable_entity_id("silo-1", "Alice")
    b = _stable_entity_id("silo-1", "alice")
    assert a == b


def test_stable_entity_id_silo_scoped() -> None:
    a = _stable_entity_id("silo-1", "Alice")
    b = _stable_entity_id("silo-2", "Alice")
    assert a != b


# ---------------------------------------------------------------------------
# extraction asset — output shape
# ---------------------------------------------------------------------------


def _make_instance(silo_id: str) -> dg.DagsterInstance:
    instance = dg.DagsterInstance.ephemeral()
    instance.add_dynamic_partitions("silo_id", [silo_id])
    return instance


def test_extraction_asset_output_has_required_metadata_keys() -> None:
    """Assert the asset emits Output with the expected metadata keys."""
    from context_service.pipelines.assets.extraction import extraction

    silo_id = "test-silo"
    instance = _make_instance(silo_id)

    memgraph_res = MemgraphResource(uri="bolt://fake:7687")
    llm_res = LLMResource(provider="gemini", model="gemini-2.0-flash")
    redis_res = RedisResource(url="redis://fake:6379")

    with patch(
        "context_service.pipelines.assets.extraction.asyncio.run",
        return_value=(2, 3, 150, 0.0, 1),
    ):
        result = dg.materialize_to_memory(
            [extraction],
            resources={"memgraph": memgraph_res, "llm": llm_res, "redis": redis_res},
            partition_key=silo_id,
            instance=instance,
        )

    assert result.success
    mats = result.asset_materializations_for_node("extraction")
    assert mats
    metadata = mats[0].metadata
    for key in ("docs_processed", "claims_created", "tokens_used", "cost_usd", "duration_s"):
        assert key in metadata, f"missing metadata key: {key}"


def test_extraction_asset_returns_zero_counts_when_no_docs() -> None:
    """When no pending docs exist, the asset emits zeros without error."""
    from context_service.pipelines.assets.extraction import extraction

    silo_id = "empty-silo"
    instance = _make_instance(silo_id)

    memgraph_res = MemgraphResource(uri="bolt://fake:7687")
    llm_res = LLMResource(provider="gemini", model="gemini-2.0-flash")
    redis_res = RedisResource(url="redis://fake:6379")

    with patch(
        "context_service.pipelines.assets.extraction.asyncio.run",
        return_value=(0, 0, 0, 0.0, 0),
    ):
        result = dg.materialize_to_memory(
            [extraction],
            resources={"memgraph": memgraph_res, "llm": llm_res, "redis": redis_res},
            partition_key=silo_id,
            instance=instance,
        )

    assert result.success
    output = result.output_for_node("extraction")
    assert output["docs_processed"] == 0
    assert output["claims_created"] == 0
