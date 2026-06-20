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
    # Support session state calls
    raw_redis.get = AsyncMock(return_value=None)
    raw_redis.setex = AsyncMock(return_value=True)
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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=None),
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
        expected_engagement = {
            "mode": "soft",
            "markers": [
                {
                    "marker_id": "marker-1",
                    "marker_type": "Contradiction",
                    "summary": "Contradiction between node-a and node-b",
                    "node_ids": ["node-a", "node-b"],
                    "detected_at": "2026-05-25T10:00:00Z",
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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=expected_engagement),
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
    async def test_tick_no_hint_includes_proposed_belief(
        self, mock_context_service, mock_redis_client
    ):
        """No-hint path must surface ProposedBelief markers via get_engagement_for_silo."""
        expected_engagement = {
            "mode": "soft",
            "markers": [
                {
                    "marker_id": "pb-1",
                    "marker_type": "ProposedBelief",
                    "summary": "System synthesized belief: Users prefer dark mode",
                    "node_ids": ["fact-1"],
                    "detected_at": "2026-05-25T12:00:00Z",
                    "decision_required": "accept",
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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=expected_engagement),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(about_hint=None, silo_id="silo-1")

        assert result["engagement"] is not None
        engagement = result["engagement"]
        assert len(engagement["markers"]) == 1
        m = engagement["markers"][0]
        assert m["marker_type"] == "ProposedBelief"
        assert m["decision_required"] == "accept"
        assert m["marker_id"] == "pb-1"

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
    async def test_tick_with_about_hint_no_markers(self, mock_context_service, mock_redis_client):
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
    async def test_tick_filters_non_pending_markers(self, mock_context_service, mock_redis_client):
        """Resolved markers are excluded by get_engagement_for_silo; null returned."""
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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=None),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(about_hint=None, silo_id="silo-1")

        # resolved marker should be filtered out -> no engagement
        assert result["engagement"] is None


class TestTickEnhanced:
    """Tests for enhanced tick() with session_id, recent_context, and nudges."""

    @pytest.mark.asyncio
    async def test_tick_returns_session_id(self, mock_context_service, mock_redis_client):
        """tick() should return session_id in response."""
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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=None),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(
                about_hint=None,
                silo_id="silo-1",
                session_id=None,
                recent_context=None,
            )

        assert "session_id" in result
        assert result["session_id"].startswith("sess_")

    @pytest.mark.asyncio
    async def test_tick_returns_nudges_field(self, mock_context_service, mock_redis_client):
        """tick() should include nudges, status, and meta in response."""
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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=None),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(
                about_hint=None,
                silo_id="silo-1",
                session_id=None,
                recent_context="working on authentication",
            )

        assert "nudges" in result
        assert "status" in result
        assert "meta" in result
        assert "checks_completed" in result["meta"]
        assert isinstance(result["nudges"], list)

    @pytest.mark.asyncio
    async def test_tick_preserves_session_id_across_calls(
        self, mock_context_service, mock_redis_client
    ):
        """When session_id provided, same session is returned."""
        import json

        session_data = {
            "session_id": "sess_existing123",
            "turn_count": 3,
            "last_store_turn": 1,
            "shown_nudges": {},
            "ignored_nudges": {},
            "created_at": "2026-05-27T00:00:00+00:00",
        }
        mock_redis_client._redis.get = AsyncMock(return_value=json.dumps(session_data).encode())

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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=None),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(
                about_hint=None,
                silo_id="silo-1",
                session_id="sess_existing123",
                recent_context=None,
            )

        assert result["session_id"] == "sess_existing123"

    @pytest.mark.asyncio
    async def test_tick_storage_gap_nudge(self, mock_context_service, mock_redis_client):
        """tick() should emit a storage_gap nudge when last_store_turn is far back."""
        import json

        session_data = {
            "session_id": "sess_gaptest",
            "turn_count": 15,
            "last_store_turn": 0,
            "shown_nudges": {},
            "ignored_nudges": {},
            "created_at": "2026-05-27T00:00:00+00:00",
        }
        mock_redis_client._redis.get = AsyncMock(return_value=json.dumps(session_data).encode())

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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=None),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(
                about_hint=None,
                silo_id="silo-1",
                session_id="sess_gaptest",
                recent_context=None,
            )

        nudge_types = [n["type"] for n in result["nudges"]]
        assert "storage_gap" in nudge_types

    @pytest.mark.asyncio
    async def test_tick_pending_markers_nudge(self, mock_context_service, mock_redis_client):
        """tick() should emit a pending_markers nudge when markers are present."""
        engagement_with_markers = {
            "mode": "soft",
            "markers": [
                {
                    "marker_id": "m1",
                    "marker_type": "Contradiction",
                    "summary": "Contradiction detected",
                    "node_ids": ["n1", "n2"],
                    "detected_at": "2026-05-27T00:00:00Z",
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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=engagement_with_markers),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(
                about_hint=None,
                silo_id="silo-1",
                session_id=None,
                recent_context=None,
            )

        nudge_types = [n["type"] for n in result["nudges"]]
        assert "pending_markers" in nudge_types

    @pytest.mark.asyncio
    async def test_tick_status_is_ok_with_nudges(self, mock_context_service, mock_redis_client):
        """tick() should return status='ok' when nudges or markers are present."""
        engagement_with_markers = {
            "mode": "soft",
            "markers": [
                {
                    "marker_id": "m1",
                    "marker_type": "Contradiction",
                    "summary": "Contradiction",
                    "node_ids": ["n1"],
                    "detected_at": "2026-05-27T00:00:00Z",
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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=engagement_with_markers),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(
                about_hint=None,
                silo_id="silo-1",
                session_id=None,
                recent_context=None,
            )

        assert result["status"] in ("ok", "partial")

    @pytest.mark.asyncio
    async def test_tick_status_current_when_nothing_pending(
        self, mock_context_service, mock_redis_client
    ):
        """tick() should return status='current' when nothing needs attention."""
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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=None),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(
                about_hint=None,
                silo_id="silo-1",
                session_id=None,
                recent_context=None,
            )

        assert result["status"] in ("current", "partial")

    @pytest.mark.asyncio
    async def test_tick_meta_has_latency(self, mock_context_service, mock_redis_client):
        """tick() meta should include latency_ms."""
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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=None),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(
                about_hint=None,
                silo_id="silo-1",
                session_id=None,
                recent_context=None,
            )

        assert "latency_ms" in result["meta"]
        assert isinstance(result["meta"]["latency_ms"], (int, float))


class TestTickDecayPrevention:
    """Tests for tick decay-prevention (last_accessed_at update)."""

    @pytest.mark.asyncio
    async def test_tick_with_about_hint_updates_node_access(
        self, mock_context_service, mock_redis_client
    ):
        """When about_hint is provided, last_accessed_at should be updated."""
        mock_context_service.graph_store.execute_write = AsyncMock(
            return_value=[{"updated": 2}]
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
            patch(
                "context_service.engine.engagement.get_engagement_for_about_set",
                new=AsyncMock(return_value=None),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(
                about_hint=["node-1", "node-2"],
                silo_id="silo-1",
                engagement_type="used",
            )

        # Verify execute_write was called for node access update
        mock_context_service.graph_store.execute_write.assert_called_once()
        call_args = mock_context_service.graph_store.execute_write.call_args
        params = call_args[0][1]
        assert params["node_ids"] == ["node-1", "node-2"]
        assert params["heat_delta"] == 1.0  # "used" heat

        # Verify response includes metadata
        assert result["meta"]["nodes_updated"] == 2
        assert result["meta"]["engagement_type"] == "used"

    @pytest.mark.asyncio
    async def test_tick_engagement_type_heat_values(
        self, mock_context_service, mock_redis_client
    ):
        """Different engagement types should have different heat deltas."""
        mock_context_service.graph_store.execute_write = AsyncMock(
            return_value=[{"updated": 1}]
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
            patch(
                "context_service.engine.engagement.get_engagement_for_about_set",
                new=AsyncMock(return_value=None),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            # Test "confirmed" engagement type
            await _tick(
                about_hint=["node-1"],
                silo_id="silo-1",
                engagement_type="confirmed",
            )

        call_args = mock_context_service.graph_store.execute_write.call_args
        params = call_args[0][1]
        assert params["heat_delta"] == 2.0  # "confirmed" heat

    @pytest.mark.asyncio
    async def test_tick_no_about_hint_skips_access_update(
        self, mock_context_service, mock_redis_client
    ):
        """When about_hint is None, no access update should happen."""
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
                "context_service.engine.engagement.get_engagement_for_silo",
                new=AsyncMock(return_value=None),
            ),
        ):
            from context_service.mcp.tools.tick import _tick

            result = await _tick(about_hint=None, silo_id="silo-1")

        # No execute_write call for access update
        mock_context_service.graph_store.execute_write.assert_not_called()
        assert result["meta"]["nodes_updated"] == 0


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
