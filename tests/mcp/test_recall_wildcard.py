"""Tests for recall wildcard bypass behavior."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from context_service.mcp.tools.context_recall import _context_recall

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
async def test_wildcard_sets_bypass_threshold() -> None:
    """query='*' should pass bypass_threshold=True to _context_query."""
    with patch(
        "context_service.mcp.tools.context_recall._context_query",
        new_callable=AsyncMock,
        return_value=_QUERY_RESULT,
    ) as mock_query:
        await _context_recall(
            silo_id=_SILO_ID,
            query="*",
            top_k=100,
        )

    mock_query.assert_called_once()
    assert mock_query.call_args.kwargs.get("bypass_threshold") is True


@pytest.mark.asyncio
async def test_normal_query_does_not_bypass_threshold() -> None:
    """A normal query should not set bypass_threshold."""
    with patch(
        "context_service.mcp.tools.context_recall._context_query",
        new_callable=AsyncMock,
        return_value=_QUERY_RESULT,
    ) as mock_query:
        await _context_recall(
            silo_id=_SILO_ID,
            query="test query",
        )

    mock_query.assert_called_once()
    assert not mock_query.call_args.kwargs.get("bypass_threshold")


@pytest.mark.asyncio
async def test_min_threshold_forwarded() -> None:
    """min_threshold should be forwarded to _context_query."""
    with patch(
        "context_service.mcp.tools.context_recall._context_query",
        new_callable=AsyncMock,
        return_value=_QUERY_RESULT,
    ) as mock_query:
        await _context_recall(
            silo_id=_SILO_ID,
            query="test query",
            min_threshold=0.1,
        )

    mock_query.assert_called_once()
    assert mock_query.call_args.kwargs.get("min_threshold") == 0.1


@pytest.mark.asyncio
async def test_empty_string_returns_missing_input_error() -> None:
    """query='' is treated as missing input, not a wildcard (falsy guard fires first)."""
    result = await _context_recall(
        silo_id=_SILO_ID,
        query="",
    )
    assert result.get("error") == "missing_input"
