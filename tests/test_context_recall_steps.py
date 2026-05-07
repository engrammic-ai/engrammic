"""Tests for context_recall include_steps parameter."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def mock_proposed_beliefs():
    """Suppress _fetch_proposed_beliefs in unit tests (requires live service)."""
    with patch(
        "context_service.mcp.tools.context_recall._fetch_proposed_beliefs",
        new_callable=AsyncMock,
        return_value=[],
    ):
        yield


@pytest.mark.asyncio
async def test_context_recall_includes_steps_when_requested() -> None:
    """include_steps=True fetches steps from Postgres."""
    from context_service.mcp.tools.context_recall import _context_recall

    chain_id = str(uuid4())
    silo_id = str(uuid4())

    mock_steps = [{"step_index": 0, "operation": "test", "conclusion": "done"}]

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {
            "nodes": [
                {
                    "node_id": chain_id,
                    "layer": "intelligence",
                    "step_count": 1,
                }
            ]
        }

        with patch("context_service.mcp.tools.context_recall._fetch_chain_steps") as mock_fetch:
            mock_fetch.return_value = {chain_id: mock_steps}

            result = await _context_recall(
                silo_id=silo_id,
                node_ids=[chain_id],
                include_steps=True,
            )

            assert result["nodes"][0]["steps"] == mock_steps
            mock_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_context_recall_skips_steps_when_not_requested() -> None:
    """include_steps=False (default) does not fetch steps."""
    from context_service.mcp.tools.context_recall import _context_recall

    chain_id = str(uuid4())
    silo_id = str(uuid4())

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {
            "nodes": [
                {
                    "node_id": chain_id,
                    "layer": "intelligence",
                    "step_count": 1,
                }
            ]
        }

        with patch("context_service.mcp.tools.context_recall._fetch_chain_steps") as mock_fetch:
            result = await _context_recall(
                silo_id=silo_id,
                node_ids=[chain_id],
                include_steps=False,
            )

            mock_fetch.assert_not_called()
            assert "steps" not in result["nodes"][0]


@pytest.mark.asyncio
async def test_context_recall_only_fetches_intelligence_steps() -> None:
    """include_steps only enriches intelligence-layer nodes."""
    from context_service.mcp.tools.context_recall import _context_recall

    chain_id = str(uuid4())
    memory_id = str(uuid4())
    silo_id = str(uuid4())

    mock_steps = [{"step_index": 0, "operation": "test", "conclusion": "done"}]

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {
            "nodes": [
                {
                    "node_id": chain_id,
                    "layer": "intelligence",
                    "step_count": 1,
                },
                {
                    "node_id": memory_id,
                    "layer": "memory",
                },
            ]
        }

        with patch("context_service.mcp.tools.context_recall._fetch_chain_steps") as mock_fetch:
            mock_fetch.return_value = {chain_id: mock_steps}

            result = await _context_recall(
                silo_id=silo_id,
                node_ids=[chain_id, memory_id],
                include_steps=True,
            )

            intelligence_node = next(n for n in result["nodes"] if n["node_id"] == chain_id)
            memory_node = next(n for n in result["nodes"] if n["node_id"] == memory_id)

            assert intelligence_node["steps"] == mock_steps
            assert "steps" not in memory_node

            # _fetch_chain_steps should only be called with intelligence node IDs
            called_ids = mock_fetch.call_args[0][0]
            assert chain_id in called_ids
            assert memory_id not in called_ids


@pytest.mark.asyncio
async def test_context_recall_steps_ignored_in_search_mode() -> None:
    """include_steps is silently ignored in query/search mode."""
    from context_service.mcp.tools.context_recall import _context_recall

    silo_id = str(uuid4())

    with patch("context_service.mcp.tools.context_recall._context_query") as mock_query:
        mock_query.return_value = {"results": [], "total_candidates": 0}

        with patch("context_service.mcp.tools.context_recall._fetch_chain_steps") as mock_fetch:
            result = await _context_recall(
                silo_id=silo_id,
                query="some query",
                include_steps=True,
            )

            mock_fetch.assert_not_called()
            assert "results" in result
