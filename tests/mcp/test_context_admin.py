"""Tests for context_admin tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
_NODE_ID = str(uuid.uuid4())
_CHAIN_ID = str(uuid.uuid4())

_SILO_LIST_RESULT = {
    "silos": [
        {
            "silo_id": _SILO_ID,
            "name": "default",
            "org_id": "test-org",
            "description": None,
            "dissolvability": "hard",
        }
    ]
}

_HISTORY_RESULT = {"timeline": [], "current": None, "entries_count": 0}

_PROVENANCE_RESULT = {
    "node_id": _NODE_ID,
    "chain": [],
    "root_sources": [],
    "chain_length": 0,
}

_CLOSE_RESULT = {
    "chain_id": _CHAIN_ID,
    "session_state": "closed",
    "summarization_triggered": False,
    "step_count": 0,
    "closed_at": "2026-01-01T00:00:00+00:00",
    "silo_id": _SILO_ID,
}


@pytest.fixture
def mock_silo_list():
    with patch(
        "context_service.mcp.tools.context_admin._silo_list_impl",
        new_callable=AsyncMock,
        return_value=_SILO_LIST_RESULT,
    ) as m:
        yield m


@pytest.fixture
def mock_history():
    with patch(
        "context_service.mcp.tools.context_admin._context_history",
        new_callable=AsyncMock,
        return_value=_HISTORY_RESULT,
    ) as m:
        yield m


@pytest.fixture
def mock_graph_provenance():
    with patch(
        "context_service.mcp.tools.context_admin._context_graph",
        new_callable=AsyncMock,
        return_value=_PROVENANCE_RESULT,
    ) as m:
        yield m


@pytest.fixture
def mock_close_reasoning():
    with patch(
        "context_service.mcp.tools.context_admin._context_close_reasoning",
        new_callable=AsyncMock,
        return_value=_CLOSE_RESULT,
    ) as m:
        yield m


@pytest.mark.asyncio
async def test_admin_silo_list(mock_silo_list):
    from context_service.mcp.tools.context_admin import _context_admin

    result = await _context_admin(action="silo_list", silo_id=_SILO_ID)

    assert "silos" in result
    mock_silo_list.assert_called_once()


@pytest.mark.asyncio
async def test_admin_history(mock_history):
    from context_service.mcp.tools.context_admin import _context_admin

    result = await _context_admin(action="history", silo_id=_SILO_ID, ref=_NODE_ID)

    assert "timeline" in result
    mock_history.assert_called_once()


@pytest.mark.asyncio
async def test_admin_history_missing_ref():
    from context_service.mcp.tools.context_admin import _context_admin

    result = await _context_admin(action="history", silo_id=_SILO_ID)

    assert result["error"] == "missing_ref"


@pytest.mark.asyncio
async def test_admin_provenance(mock_graph_provenance):
    from context_service.mcp.tools.context_admin import _context_admin

    result = await _context_admin(action="provenance", silo_id=_SILO_ID, ref=_NODE_ID)

    assert "node_id" in result
    mock_graph_provenance.assert_called_once()
    call_kwargs = mock_graph_provenance.call_args.kwargs
    assert call_kwargs.get("mode") == "provenance"
    assert call_kwargs.get("seed_nodes") == [_NODE_ID]


@pytest.mark.asyncio
async def test_admin_provenance_missing_ref():
    from context_service.mcp.tools.context_admin import _context_admin

    result = await _context_admin(action="provenance", silo_id=_SILO_ID)

    assert result["error"] == "missing_ref"


@pytest.mark.asyncio
async def test_admin_close_session(mock_close_reasoning):
    from context_service.mcp.tools.context_admin import _context_admin

    result = await _context_admin(action="close_session", silo_id=_SILO_ID, ref=_CHAIN_ID)

    assert result["chain_id"] == _CHAIN_ID
    mock_close_reasoning.assert_called_once()


@pytest.mark.asyncio
async def test_admin_close_session_missing_ref():
    from context_service.mcp.tools.context_admin import _context_admin

    result = await _context_admin(action="close_session", silo_id=_SILO_ID)

    assert result["error"] == "missing_ref"


@pytest.mark.asyncio
async def test_admin_unknown_action():
    from context_service.mcp.tools.context_admin import _context_admin

    result = await _context_admin(action="delete_everything", silo_id=_SILO_ID)

    assert result["error"] == "unknown_action"
    assert "valid" in result
