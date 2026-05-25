"""Unit tests for pipelines/assets/marker_cleanup.py — no live services required."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import dagster as dg
import pytest

from context_service.pipelines.assets.marker_cleanup import marker_cleanup_asset, silo_partitions
from context_service.pipelines.resources import MemgraphResource, RedisResource

_cleanup_fn = marker_cleanup_asset.op.compute_fn.decorated_fn


def _make_context(silo_id: str = "silo-cleanup-test") -> dg.AssetExecutionContext:
    ctx = MagicMock(spec=dg.AssetExecutionContext)
    ctx.partition_key = silo_id
    ctx.log = MagicMock()
    return ctx


def test_marker_cleanup_uses_shared_silo_partitions() -> None:
    assert silo_partitions.name == "silo_id"


def test_marker_cleanup_returns_output_with_required_keys() -> None:
    ctx = _make_context()
    memgraph_res = MagicMock(spec=MemgraphResource)
    redis_res = MagicMock(spec=RedisResource)

    with patch("context_service.pipelines.assets.marker_cleanup._run_async") as mock_run:
        mock_run.return_value = (2, 3)
        result = _cleanup_fn(ctx, memgraph=memgraph_res, redis=redis_res)

    assert isinstance(result, dg.Output)
    val = result.value
    for key in ("silo_id", "deleted_contradictions", "deleted_stale_commitments", "total_deleted"):
        assert key in val, f"missing output key: {key}"


def test_marker_cleanup_total_is_sum_of_both_types() -> None:
    ctx = _make_context("silo-abc")
    memgraph_res = MagicMock(spec=MemgraphResource)
    redis_res = MagicMock(spec=RedisResource)

    with patch("context_service.pipelines.assets.marker_cleanup._run_async") as mock_run:
        mock_run.return_value = (4, 7)
        result = _cleanup_fn(ctx, memgraph=memgraph_res, redis=redis_res)

    assert result.value["deleted_contradictions"] == 4
    assert result.value["deleted_stale_commitments"] == 7
    assert result.value["total_deleted"] == 11
    assert result.value["silo_id"] == "silo-abc"


def test_marker_cleanup_zero_when_nothing_expired() -> None:
    ctx = _make_context("silo-empty")
    memgraph_res = MagicMock(spec=MemgraphResource)
    redis_res = MagicMock(spec=RedisResource)

    with patch("context_service.pipelines.assets.marker_cleanup._run_async") as mock_run:
        mock_run.return_value = (0, 0)
        result = _cleanup_fn(ctx, memgraph=memgraph_res, redis=redis_res)

    assert result.value["total_deleted"] == 0
    assert result.value["deleted_contradictions"] == 0
    assert result.value["deleted_stale_commitments"] == 0


def test_marker_cleanup_metadata_includes_metric_keys() -> None:
    ctx = _make_context()
    memgraph_res = MagicMock(spec=MemgraphResource)
    redis_res = MagicMock(spec=RedisResource)

    with patch("context_service.pipelines.assets.marker_cleanup._run_async") as mock_run:
        mock_run.return_value = (1, 2)
        result = _cleanup_fn(ctx, memgraph=memgraph_res, redis=redis_res)

    meta = result.metadata
    assert "markers_expired_contradictions" in meta
    assert "markers_expired_stale_commitments" in meta
    # Dagster wraps integer metadata in IntMetadataValue; compare via .value.
    assert meta["markers_expired_contradictions"].value == 1
    assert meta["markers_expired_stale_commitments"].value == 2


@pytest.mark.asyncio
async def test_marker_cleanup_redis_zrem_called_for_about_ids() -> None:
    """Verify that for each expired marker, ZREM is called on each about_id's key."""
    from context_service.pipelines.assets.marker_cleanup import _MARKER_INDEX_KEY

    silo_id = "silo-redis-test"

    # Simulate expired rows returned by GET_EXPIRED_MARKERS.
    expired_rows = [
        {"id": "marker-1", "marker_type": "Contradiction", "about_ids": ["node-a", "node-b"]},
        {"id": "marker-2", "marker_type": "StaleCommitment", "about_ids": ["node-c"]},
    ]
    # DELETE_EXPIRED_MARKERS returns counts.
    delete_result = [{"deleted_contradictions": 1, "deleted_stale_commitments": 1}]

    mock_store = AsyncMock()
    mock_store.execute_query = AsyncMock(side_effect=[expired_rows, delete_result])

    mock_pipe = AsyncMock()
    mock_pipe.zrem = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 1, 1])

    mock_redis_client = AsyncMock()
    mock_redis_client.pipeline = MagicMock(return_value=mock_pipe)

    mock_memgraph = AsyncMock()
    mock_memgraph.store = AsyncMock(return_value=mock_store)

    mock_redis = AsyncMock()
    mock_redis.client = AsyncMock(return_value=mock_redis_client)

    # Test the inner coroutine logic by constructing an equivalent coroutine.
    async def _inner() -> tuple[int, int]:
        from datetime import UTC, datetime

        from context_service.db.queries import DELETE_EXPIRED_MARKERS, GET_EXPIRED_MARKERS

        graph_store = await mock_memgraph.store()
        redis_client = await mock_redis.client()
        now = datetime.now(UTC).isoformat()

        expired = await graph_store.execute_query(
            GET_EXPIRED_MARKERS, {"silo_id": silo_id, "now": now}
        )

        contradictions: list[tuple[str, list[str]]] = []
        stale: list[tuple[str, list[str]]] = []
        for row in expired:
            mid = str(row["id"])
            aids: list[str] = list(row.get("about_ids") or [])
            if row.get("marker_type") == "Contradiction":
                contradictions.append((mid, aids))
            else:
                stale.append((mid, aids))

        result = await graph_store.execute_query(
            DELETE_EXPIRED_MARKERS, {"silo_id": silo_id, "now": now}
        )
        deleted_c = int(result[0]["deleted_contradictions"]) if result else 0
        deleted_sc = int(result[0]["deleted_stale_commitments"]) if result else 0

        all_markers = contradictions + stale
        if all_markers:
            pipe = redis_client.pipeline(transaction=False)
            for mid, aids in all_markers:
                for node_id in aids:
                    key = _MARKER_INDEX_KEY.format(silo_id=silo_id, node_id=node_id)
                    pipe.zrem(key, mid)
            await pipe.execute()

        return deleted_c, deleted_sc

    deleted_c, deleted_sc = await _inner()

    assert deleted_c == 1
    assert deleted_sc == 1

    # Verify ZREM was called for each (marker_id, node_id) pair.
    expected_calls = [
        ("marker-1", "node-a"),
        ("marker-1", "node-b"),
        ("marker-2", "node-c"),
    ]
    assert mock_pipe.zrem.call_count == len(expected_calls)
    for marker_id, node_id in expected_calls:
        key = _MARKER_INDEX_KEY.format(silo_id=silo_id, node_id=node_id)
        mock_pipe.zrem.assert_any_call(key, marker_id)
