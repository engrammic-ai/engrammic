"""Tests for the tick MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_context_service():
    """Mock context service with graph store."""
    ctx = MagicMock()
    ctx.graph_store = AsyncMock()
    return ctx


@pytest.fixture
def mock_redis_client():
    """Mock RedisClient wrapper."""
    redis_client = MagicMock()
    raw_redis = MagicMock()
    pipe = AsyncMock()
    pipe.zrange = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    raw_redis.pipeline = MagicMock(return_value=pipe)
    redis_client._redis = raw_redis
    return redis_client


class TestTickInternal:
    """Tests for the internal _tick function."""

    @pytest.mark.asyncio
    async def test_tick_no_markers_returns_null_engagement(
        self, mock_context_service, mock_redis_client
    ):
        """When no pending markers exist, engagement should be null."""
        with (
            patch(
                "context_service.mcp.server.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.mcp.server.get_redis",
                return_value=mock_redis_client,
            ),
            patch(
                "context_service.engine.markers.get_all_pending_markers",
                new=AsyncMock(return_value=[]),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(about_hint=None, silo_id="silo-1")

        assert result["engagement"] is None

    @pytest.mark.asyncio
    async def test_tick_with_markers_returns_engagement_data(
        self, mock_context_service, mock_redis_client
    ):
        """When pending markers exist, engagement payload should be returned."""
        marker_details = [
            {
                "id": "marker-1",
                "marker_type": "Contradiction",
                "status": "pending",
                "detected_at": "2026-05-25T10:00:00Z",
                "about_ids": ["node-a", "node-b"],
                "node_a_id": "node-a",
                "node_b_id": "node-b",
            }
        ]

        with (
            patch(
                "context_service.mcp.server.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.mcp.server.get_redis",
                return_value=mock_redis_client,
            ),
            patch(
                "context_service.engine.markers.get_all_pending_markers",
                new=AsyncMock(return_value=["marker-1"]),
            ),
            patch(
                "context_service.engine.markers.get_marker_details",
                new=AsyncMock(return_value=marker_details),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(about_hint=None, silo_id="silo-1")

        assert result["engagement"] is not None
        engagement = result["engagement"]
        assert engagement["mode"] == "soft"
        assert len(engagement["markers"]) == 1
        m = engagement["markers"][0]
        assert m["marker_id"] == "marker-1"
        assert m["marker_type"] == "Contradiction"
        assert m["decision_required"] == "dismiss"

    @pytest.mark.asyncio
    async def test_tick_with_about_hint_filters_correctly(
        self, mock_context_service, mock_redis_client
    ):
        """When about_hint is provided, get_engagement_for_about_set is called."""
        expected_engagement = {
            "mode": "soft",
            "markers": [
                {
                    "marker_id": "marker-2",
                    "marker_type": "StaleCommitment",
                    "summary": "Commitment commit-1 may be stale",
                    "node_ids": ["commit-1"],
                    "detected_at": "2026-05-25T11:00:00Z",
                    "decision_required": "dismiss",
                }
            ],
        }

        with (
            patch(
                "context_service.mcp.server.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.mcp.server.get_redis",
                return_value=mock_redis_client,
            ),
            patch(
                "context_service.engine.engagement.get_engagement_for_about_set",
                new=AsyncMock(return_value=expected_engagement),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(about_hint=["commit-1"], silo_id="silo-1")

        assert result["engagement"] is not None
        assert result["engagement"]["markers"][0]["marker_id"] == "marker-2"

    @pytest.mark.asyncio
    async def test_tick_with_about_hint_no_markers(
        self, mock_context_service, mock_redis_client
    ):
        """When about_hint provided but no markers found, engagement is null."""
        with (
            patch(
                "context_service.mcp.server.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.mcp.server.get_redis",
                return_value=mock_redis_client,
            ),
            patch(
                "context_service.engine.engagement.get_engagement_for_about_set",
                new=AsyncMock(return_value=None),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(about_hint=["node-x"], silo_id="silo-1")

        assert result["engagement"] is None

    @pytest.mark.asyncio
    async def test_tick_error_when_redis_unavailable(self, mock_context_service):
        """Return error when Redis is not configured."""
        with (
            patch(
                "context_service.mcp.server.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.mcp.server.get_redis",
                return_value=None,
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(about_hint=None, silo_id="silo-1")

        assert result["error"] == "service_unavailable"
        assert "Redis" in result["message"]

    @pytest.mark.asyncio
    async def test_tick_filters_non_pending_markers(
        self, mock_context_service, mock_redis_client
    ):
        """Markers that are not 'pending' are excluded from results."""
        marker_details = [
            {
                "id": "marker-resolved",
                "marker_type": "Contradiction",
                "status": "resolved",
                "detected_at": "2026-05-25T10:00:00Z",
                "about_ids": ["node-a"],
                "node_a_id": "node-a",
                "node_b_id": "node-b",
            }
        ]

        with (
            patch(
                "context_service.mcp.server.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.mcp.server.get_redis",
                return_value=mock_redis_client,
            ),
            patch(
                "context_service.engine.markers.get_all_pending_markers",
                new=AsyncMock(return_value=["marker-resolved"]),
            ),
            patch(
                "context_service.engine.markers.get_marker_details",
                new=AsyncMock(return_value=marker_details),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(about_hint=None, silo_id="silo-1")

        # resolved marker should be filtered out -> no engagement
        assert result["engagement"] is None


class TestTickToolRegistration:
    """Tests for tool registration."""

    def test_register_adds_tool(self):
        """The register function should add the tick tool to MCP."""
        from context_service.mcp.tools.tick import register

        mcp = MagicMock()
        mcp.tool = MagicMock(return_value=lambda f: f)

        register(mcp)

        mcp.tool.assert_called_once()
        call_kwargs = mcp.tool.call_args[1]
        assert call_kwargs["name"] == "tick"
