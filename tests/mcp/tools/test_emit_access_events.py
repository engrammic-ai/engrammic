"""Tests for _emit_access_events helper in context_query."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.mcp.tools.context_query import _emit_access_events


class TestEmitAccessEvents:
    @pytest.mark.asyncio
    async def test_access_events_emitted_for_results(self) -> None:
        """Helper calls emit_access_event for each result node_id."""
        redis = MagicMock()
        silo_id = "test-silo"

        results = [
            MagicMock(node_id="node-1"),
            MagicMock(node_id="node-2"),
            MagicMock(node_id="node-3"),
        ]

        with patch(
            "context_service.mcp.tools.context_query.emit_access_event",
            new_callable=AsyncMock,
        ) as mock_emit:
            await _emit_access_events(redis, silo_id, results)

        assert mock_emit.call_count == 3
        called_node_ids = {call.args[2] for call in mock_emit.call_args_list}
        assert called_node_ids == {"node-1", "node-2", "node-3"}

    @pytest.mark.asyncio
    async def test_no_events_when_redis_is_none(self) -> None:
        """Helper is a no-op when redis is None."""
        results = [MagicMock(node_id="node-1")]

        with patch(
            "context_service.mcp.tools.context_query.emit_access_event",
            new_callable=AsyncMock,
        ) as mock_emit:
            await _emit_access_events(None, "test-silo", results)

        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_events_when_results_empty(self) -> None:
        """Helper is a no-op when results list is empty."""
        redis = MagicMock()

        with patch(
            "context_service.mcp.tools.context_query.emit_access_event",
            new_callable=AsyncMock,
        ) as mock_emit:
            await _emit_access_events(redis, "test-silo", [])

        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_dict_results_use_node_id_key(self) -> None:
        """Helper handles dict results (cache-hit path) as well as object results."""
        redis = MagicMock()
        silo_id = "test-silo"

        results = [
            {"node_id": "node-a", "content": "hello"},
            {"node_id": "node-b", "content": "world"},
        ]

        with patch(
            "context_service.mcp.tools.context_query.emit_access_event",
            new_callable=AsyncMock,
        ) as mock_emit:
            await _emit_access_events(redis, silo_id, results)

        assert mock_emit.call_count == 2
        called_node_ids = {call.args[2] for call in mock_emit.call_args_list}
        assert called_node_ids == {"node-a", "node-b"}

    @pytest.mark.asyncio
    async def test_timeout_is_handled_gracefully(self) -> None:
        """Timeout error during emit is caught and logged, not propagated."""
        import asyncio

        redis = MagicMock()
        results = [MagicMock(node_id="node-1")]

        async def slow_emit(*_args: object) -> None:
            await asyncio.sleep(10)

        with (
            patch(
                "context_service.mcp.tools.context_query.emit_access_event",
                side_effect=slow_emit,
            ),
            patch("asyncio.wait_for", side_effect=TimeoutError),
        ):
            # Should not raise
            await _emit_access_events(redis, "test-silo", results)
