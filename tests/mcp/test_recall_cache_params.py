"""Tests verifying bypass_cache and max_age_seconds are threaded through recall tools."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from context_service.mcp.tools.context_recall import _context_recall
from context_service.mcp.tools.recall import _recall_impl

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

_QUERY_RESULT = {
    "results": [],
    "total_candidates": 0,
    "search_time_ms": 5,
    "search_mode": "hybrid",
    "reflection_suggested": False,
    "metadata": {},
}


@pytest.mark.asyncio
async def test_context_recall_threads_bypass_cache() -> None:
    """_context_recall forwards bypass_cache=True to _context_query (query + depth=0 branch)."""
    with patch(
        "context_service.mcp.tools.context_recall._context_query",
        new_callable=AsyncMock,
        return_value=_QUERY_RESULT,
    ) as mock_query:
        await _context_recall(
            silo_id=_SILO_ID,
            query="test query",
            bypass_cache=True,
        )

    mock_query.assert_called_once()
    kwargs = mock_query.call_args.kwargs
    assert kwargs.get("bypass_cache") is True


@pytest.mark.asyncio
async def test_context_recall_threads_max_age_seconds() -> None:
    """_context_recall forwards max_age_seconds to _context_query (query + depth=0 branch)."""
    with patch(
        "context_service.mcp.tools.context_recall._context_query",
        new_callable=AsyncMock,
        return_value=_QUERY_RESULT,
    ) as mock_query:
        await _context_recall(
            silo_id=_SILO_ID,
            query="test query",
            max_age_seconds=30,
        )

    mock_query.assert_called_once()
    kwargs = mock_query.call_args.kwargs
    assert kwargs.get("max_age_seconds") == 30


@pytest.mark.asyncio
async def test_recall_threads_bypass_cache() -> None:
    """_recall_impl forwards bypass_cache=True to _context_recall."""
    _RECALL_RESULT: dict = {"results": [], "total_candidates": 0}

    with (
        patch(
            "context_service.mcp.tools.recall._context_recall",
            new_callable=AsyncMock,
            return_value=_RECALL_RESULT,
        ) as mock_recall,
        patch(
            "context_service.mcp.tools.recall.get_mcp_auth_context",
            new_callable=AsyncMock,
            return_value=AsyncMock(
                org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"), session_id=None
            ),
        ),
        patch(
            "context_service.mcp.tools.recall.track_tool_usage",
            new_callable=AsyncMock,
        ),
        patch(
            "context_service.mcp.tools.recall.get_preset_resolver",
            side_effect=RuntimeError("no preset"),
        ),
    ):
        await _recall_impl(query="test query", bypass_cache=True)

    mock_recall.assert_called_once()
    kwargs = mock_recall.call_args.kwargs
    assert kwargs.get("bypass_cache") is True


@pytest.mark.asyncio
async def test_recall_threads_max_age_seconds() -> None:
    """_recall_impl forwards max_age_seconds to _context_recall."""
    _RECALL_RESULT: dict = {"results": [], "total_candidates": 0}

    with (
        patch(
            "context_service.mcp.tools.recall._context_recall",
            new_callable=AsyncMock,
            return_value=_RECALL_RESULT,
        ) as mock_recall,
        patch(
            "context_service.mcp.tools.recall.get_mcp_auth_context",
            new_callable=AsyncMock,
            return_value=AsyncMock(
                org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"), session_id=None
            ),
        ),
        patch(
            "context_service.mcp.tools.recall.track_tool_usage",
            new_callable=AsyncMock,
        ),
        patch(
            "context_service.mcp.tools.recall.get_preset_resolver",
            side_effect=RuntimeError("no preset"),
        ),
    ):
        await _recall_impl(query="test query", max_age_seconds=60)

    mock_recall.assert_called_once()
    kwargs = mock_recall.call_args.kwargs
    assert kwargs.get("max_age_seconds") == 60
