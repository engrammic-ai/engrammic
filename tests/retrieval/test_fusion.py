"""Unit tests for the RRF fusion retriever and helpers."""

from __future__ import annotations

import pytest


def test_rrf_fusion_math() -> None:
    """Verify RRF formula: normalized score = sum(1/(k+rank)) / max_theoretical."""
    from context_service.retrieval.fusion import ChannelResult, FusionRetriever

    semantic = ChannelResult(
        channel_name="semantic",
        ranked_ids=["node_a", "node_b", "node_c"],
        latency_ms=50.0,
    )
    graph = ChannelResult(
        channel_name="graph",
        ranked_ids=["node_b", "node_d", "node_a"],
        latency_ms=80.0,
    )

    retriever = FusionRetriever(ctx_svc=None, k=60)  # type: ignore[arg-type]

    fused = retriever._fuse_rrf([semantic, graph], top_k=10)

    # node_b: rank 2 in semantic (1/62) + rank 1 in graph (1/61)
    # node_a: rank 1 in semantic (1/61) + rank 3 in graph (1/63)
    # Raw: node_b = 1/62 + 1/61, node_a = 1/61 + 1/63
    # Normalized by max_theoretical = num_channels / (k+1) = 2/61
    assert fused[0].node_id == "node_b"
    assert fused[1].node_id == "node_a"

    raw_score = 1 / 61 + 1 / 62
    max_theoretical = 2 / 61
    expected_normalized = raw_score / max_theoretical
    assert abs(fused[0].rrf_score - expected_normalized) < 0.0001


@pytest.mark.asyncio
async def test_temporal_filter() -> None:
    """Verify temporal filter excludes nodes outside window."""
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock

    from context_service.retrieval.fusion import FusedResult, _filter_temporal

    now = datetime.now(UTC)

    results = [
        FusedResult(node_id="old_node", rrf_score=0.5, channel_contributions={}),
        FusedResult(node_id="new_node", rrf_score=0.4, channel_contributions={}),
        FusedResult(node_id="no_timestamp", rrf_score=0.3, channel_contributions={}),
    ]

    mock_store = MagicMock()
    mock_store.execute_query = AsyncMock(
        return_value=[
            {
                "node_id": "old_node",
                "created_at": int((now - timedelta(days=30)).timestamp() * 1_000_000),
            },
            {
                "node_id": "new_node",
                "created_at": int((now - timedelta(days=1)).timestamp() * 1_000_000),
            },
            # no_timestamp not returned
        ]
    )

    since = now - timedelta(days=7)
    filtered = await _filter_temporal(results, since, None, mock_store, "test-silo")

    assert len(filtered) == 2
    node_ids = [r.node_id for r in filtered]
    assert "new_node" in node_ids
    assert "no_timestamp" in node_ids
    assert "old_node" not in node_ids


def test_fusion_graceful_degradation() -> None:
    """One channel error should not break fusion."""
    from context_service.retrieval.fusion import ChannelResult, FusionRetriever

    semantic = ChannelResult(
        channel_name="semantic",
        ranked_ids=["node_a", "node_b"],
        latency_ms=50.0,
    )
    graph = ChannelResult(
        channel_name="graph",
        ranked_ids=[],
        latency_ms=0.0,
        error="Connection refused",
    )

    retriever = FusionRetriever(ctx_svc=None, k=60)  # type: ignore[arg-type]
    fused = retriever._fuse_rrf([semantic, graph], top_k=10)

    assert len(fused) == 2
    assert fused[0].node_id == "node_a"
    assert "semantic" in fused[0].channel_contributions
    assert "graph" not in fused[0].channel_contributions


def test_fused_result_properties_default() -> None:
    """FusedResult.properties defaults to empty dict and can be set."""
    from context_service.retrieval.fusion import FusedResult

    result = FusedResult(node_id="node_a", rrf_score=0.5)
    assert result.properties == {}

    result.properties = {"valid_to": None, "corroboration_count": 3, "synthesis_state": "accepted"}
    assert result.properties["corroboration_count"] == 3


def test_parse_relative_time() -> None:
    """Verify relative time parsing."""
    from datetime import UTC, datetime, timedelta

    from context_service.retrieval.fusion import _parse_relative_time

    now = datetime(2024, 6, 8, 12, 0, 0, tzinfo=UTC)

    assert _parse_relative_time("7d", now) == now - timedelta(days=7)
    assert _parse_relative_time("1w", now) == now - timedelta(weeks=1)
    assert _parse_relative_time("30d", now) == now - timedelta(days=30)

    iso = _parse_relative_time("2024-06-01T00:00:00+00:00", now)
    assert iso.year == 2024
    assert iso.month == 6
    assert iso.day == 1

    with pytest.raises(ValueError):
        _parse_relative_time("yesterday", now)
