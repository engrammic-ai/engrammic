"""Tests for the dismiss MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_context_service():
    """Mock context service with graph store."""
    ctx = MagicMock()
    ctx.graph_store = AsyncMock()
    # Default: no ProposedBelief found, so regular marker path is followed
    ctx.graph_store.execute_query = AsyncMock(return_value=[])
    return ctx


@pytest.fixture
def mock_redis_client():
    """Mock RedisClient wrapper."""
    redis_client = MagicMock()
    # The underlying raw Redis instance
    raw_redis = MagicMock()
    pipe = AsyncMock()
    pipe.zrem = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    raw_redis.pipeline = MagicMock(return_value=pipe)
    redis_client._redis = raw_redis
    return redis_client


class TestDismissMarkerInternal:
    """Tests for the internal _dismiss_marker function."""

    @pytest.mark.asyncio
    async def test_dismiss_contradiction_marker(self, mock_context_service, mock_redis_client):
        """Successfully dismiss a Contradiction marker."""
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
                "context_service.engine.markers.get_marker_details",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": "marker-1",
                            "marker_type": "Contradiction",
                            "status": "pending",
                            "about_ids": ["node-a", "node-b"],
                        }
                    ]
                ),
            ),
            patch(
                "context_service.engine.markers.dismiss_marker",
                new=AsyncMock(
                    return_value={
                        "marker_id": "marker-1",
                        "marker_type": "Contradiction",
                        "status": "dismissed",
                    }
                ),
            ),
        ):
            from context_service.mcp.tools.dismiss import _dismiss_marker

            result = await _dismiss_marker(
                marker_id="marker-1",
                reason="false positive",
                silo_id="silo-1",
            )

        assert result["marker_id"] == "marker-1"
        assert result["status"] == "dismissed"

    @pytest.mark.asyncio
    async def test_dismiss_stale_commitment_marker(self, mock_context_service, mock_redis_client):
        """Successfully dismiss a StaleCommitment marker."""
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
                "context_service.engine.markers.get_marker_details",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": "marker-2",
                            "marker_type": "StaleCommitment",
                            "status": "pending",
                            "about_ids": ["commit-1"],
                        }
                    ]
                ),
            ),
            patch(
                "context_service.engine.markers.dismiss_marker",
                new=AsyncMock(
                    return_value={
                        "marker_id": "marker-2",
                        "marker_type": "StaleCommitment",
                        "status": "dismissed",
                    }
                ),
            ),
        ):
            from context_service.mcp.tools.dismiss import _dismiss_marker

            result = await _dismiss_marker(
                marker_id="marker-2",
                reason="handled externally",
                silo_id="silo-1",
            )

        assert result["marker_id"] == "marker-2"
        assert result["status"] == "dismissed"

    @pytest.mark.asyncio
    async def test_error_on_nonexistent_marker(self, mock_context_service, mock_redis_client):
        """Return error when marker does not exist."""
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
                "context_service.engine.markers.get_marker_details",
                new=AsyncMock(return_value=[]),
            ),
        ):
            from context_service.mcp.tools.dismiss import _dismiss_marker

            result = await _dismiss_marker(
                marker_id="nonexistent",
                reason="test",
                silo_id="silo-1",
            )

        assert result["error"] == "not_found"
        assert "nonexistent" in result["message"]

    @pytest.mark.asyncio
    async def test_error_on_already_dismissed_marker(self, mock_context_service, mock_redis_client):
        """Return error when marker is already dismissed."""
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
                "context_service.engine.markers.get_marker_details",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": "marker-3",
                            "marker_type": "Contradiction",
                            "status": "dismissed",
                            "about_ids": ["node-a"],
                        }
                    ]
                ),
            ),
        ):
            from context_service.mcp.tools.dismiss import _dismiss_marker

            result = await _dismiss_marker(
                marker_id="marker-3",
                reason="trying again",
                silo_id="silo-1",
            )

        assert result["error"] == "invalid_status"
        assert "dismissed" in result["message"]

    @pytest.mark.asyncio
    async def test_dismiss_rejects_proposed_belief(self, mock_context_service, mock_redis_client):
        """dismiss rejects a pending ProposedBelief and returns proposal_id + status."""
        mock_context_service.graph_store.execute_query = AsyncMock(
            return_value=[{"status": "pending"}]
        )
        mock_context_service.graph_store.execute_write = AsyncMock(
            return_value=[{"proposed_belief_id": "pb-1", "status": "rejected"}]
        )

        with (
            patch(
                "context_service.mcp.server.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.mcp.server.get_redis",
                return_value=mock_redis_client,
            ),
        ):
            from context_service.mcp.tools.dismiss import _dismiss_marker

            result = await _dismiss_marker(
                marker_id="pb-1",
                reason="Factually incorrect",
                silo_id="silo-1",
            )

        assert result.get("status") == "rejected"
        assert result.get("proposal_id") == "pb-1"
        assert result.get("reason") == "Factually incorrect"
        assert "rejected_at" in result

    @pytest.mark.asyncio
    async def test_dismiss_rejects_only_pending_proposals(
        self, mock_context_service, mock_redis_client
    ):
        """dismiss fails for an already-rejected ProposedBelief."""
        mock_context_service.graph_store.execute_query = AsyncMock(
            return_value=[{"status": "rejected"}]
        )

        with (
            patch(
                "context_service.mcp.server.get_context_service",
                return_value=mock_context_service,
            ),
            patch(
                "context_service.mcp.server.get_redis",
                return_value=mock_redis_client,
            ),
        ):
            from context_service.mcp.tools.dismiss import _dismiss_marker

            result = await _dismiss_marker(
                marker_id="pb-already-rejected",
                reason="Try again",
                silo_id="silo-1",
            )

        assert result.get("error") == "invalid_status"

    @pytest.mark.asyncio
    async def test_error_on_resolved_marker(self, mock_context_service, mock_redis_client):
        """Return error when marker is already resolved."""
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
                "context_service.engine.markers.get_marker_details",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": "marker-4",
                            "marker_type": "StaleCommitment",
                            "status": "resolved",
                            "about_ids": ["node-a"],
                        }
                    ]
                ),
            ),
        ):
            from context_service.mcp.tools.dismiss import _dismiss_marker

            result = await _dismiss_marker(
                marker_id="marker-4",
                reason="test",
                silo_id="silo-1",
            )

        assert result["error"] == "invalid_status"
        assert "resolved" in result["message"]

    @pytest.mark.asyncio
    async def test_error_when_redis_unavailable(self, mock_context_service):
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
            from context_service.mcp.tools.dismiss import _dismiss_marker

            result = await _dismiss_marker(
                marker_id="marker-1",
                reason="test",
                silo_id="silo-1",
            )

        assert result["error"] == "service_unavailable"
        assert "Redis" in result["message"]

    @pytest.mark.asyncio
    async def test_dismiss_clears_touch_counter_on_success(
        self, mock_context_service, mock_redis_client
    ):
        """clear_touches is called with correct silo_id and marker_id after dismiss."""
        mock_clear = AsyncMock()

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
                "context_service.engine.markers.get_marker_details",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": "marker-5",
                            "marker_type": "Contradiction",
                            "status": "pending",
                            "about_ids": ["node-a"],
                        }
                    ]
                ),
            ),
            patch(
                "context_service.engine.markers.dismiss_marker",
                new=AsyncMock(
                    return_value={
                        "marker_id": "marker-5",
                        "marker_type": "Contradiction",
                        "status": "dismissed",
                        "resolution": "false positive",
                        "resolved_at": "2026-01-01T00:00:00Z",
                    }
                ),
            ),
            patch("context_service.engine.touch_counter.clear_touches", mock_clear),
        ):
            from context_service.mcp.tools.dismiss import _dismiss_marker

            result = await _dismiss_marker(
                marker_id="marker-5",
                reason="false positive",
                silo_id="silo-1",
            )

        assert result["status"] == "dismissed"
        mock_clear.assert_awaited_once_with(mock_redis_client._redis, "silo-1", "marker-5")


class TestDismissToolRegistration:
    """Tests for tool registration."""

    def test_register_adds_tool(self):
        """The register function should add the dismiss tool to MCP."""
        from context_service.mcp.tools.dismiss import register

        mcp = MagicMock()
        mcp.tool = MagicMock(return_value=lambda f: f)

        register(mcp)

        mcp.tool.assert_called_once()
        call_kwargs = mcp.tool.call_args[1]
        assert call_kwargs["name"] == "dismiss"
