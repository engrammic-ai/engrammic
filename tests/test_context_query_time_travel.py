"""Unit tests for context_query time-travel (as_of) parameter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.mcp.tools.context_query import _context_query


def _make_auth(org_id: str = "org-test") -> MagicMock:
    auth = MagicMock()
    auth.org_id = org_id
    return auth


def _make_ctx_svc(temporal_results: list | None = None) -> MagicMock:
    svc = MagicMock()
    svc.query = AsyncMock(return_value=[])
    svc.temporal_query = AsyncMock(return_value=temporal_results or [])
    return svc


def _make_silo_svc() -> MagicMock:
    svc = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_as_of_none_uses_normal_query() -> None:
    """No as_of -> normal query path, no historical_query flag."""
    ctx_svc = _make_ctx_svc()
    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=_make_auth(),
        ),
        patch("context_service.mcp.tools.context_query.get_context_service", return_value=ctx_svc),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=_make_silo_svc(),
        ),
        patch("context_service.mcp.tools.context_query.validate_silo_ownership", return_value=None),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
    ):
        result = await _context_query(silo_id="silo-1", query="test query")

    assert "error" not in result
    assert result.get("historical_query") is None
    ctx_svc.query.assert_called_once()
    ctx_svc.temporal_query.assert_not_called()


@pytest.mark.asyncio
async def test_as_of_valid_iso_uses_temporal_path() -> None:
    """Valid as_of ISO string -> temporal_query called, historical_query=True in response."""
    ctx_svc = _make_ctx_svc()
    as_of_str = "2026-04-01T00:00:00Z"
    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=_make_auth(),
        ),
        patch("context_service.mcp.tools.context_query.get_context_service", return_value=ctx_svc),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=_make_silo_svc(),
        ),
        patch("context_service.mcp.tools.context_query.validate_silo_ownership", return_value=None),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
    ):
        result = await _context_query(silo_id="silo-1", query="test", as_of=as_of_str)

    assert "error" not in result
    assert result.get("historical_query") is True
    assert result.get("as_of") == as_of_str
    ctx_svc.temporal_query.assert_called_once()
    ctx_svc.query.assert_not_called()


@pytest.mark.asyncio
async def test_as_of_invalid_format_returns_error() -> None:
    """Malformed as_of -> error response, no query called."""
    ctx_svc = _make_ctx_svc()
    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=_make_auth(),
        ),
        patch("context_service.mcp.tools.context_query.get_context_service", return_value=ctx_svc),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=_make_silo_svc(),
        ),
        patch("context_service.mcp.tools.context_query.validate_silo_ownership", return_value=None),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
    ):
        result = await _context_query(silo_id="silo-1", query="test", as_of="not-a-date")

    assert result.get("error") == "invalid_as_of_format"
    ctx_svc.query.assert_not_called()
    ctx_svc.temporal_query.assert_not_called()


@pytest.mark.asyncio
async def test_as_of_future_returns_warning() -> None:
    """as_of in the future -> response includes a warning, still returns results."""
    future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    ctx_svc = _make_ctx_svc()
    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=_make_auth(),
        ),
        patch("context_service.mcp.tools.context_query.get_context_service", return_value=ctx_svc),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=_make_silo_svc(),
        ),
        patch("context_service.mcp.tools.context_query.validate_silo_ownership", return_value=None),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
    ):
        result = await _context_query(silo_id="silo-1", query="test", as_of=future)

    assert result.get("historical_query") is True
    assert "warning" in result
