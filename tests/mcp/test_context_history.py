"""Tests for context_history tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.services.context_meta import HistoryEntry, HistoryResult

SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))


@pytest.fixture
def mock_auth():
    with patch("context_service.mcp.server.get_mcp_auth_context") as m:
        auth = MagicMock()
        auth.org_id = "test-org"
        m.return_value = auth
        yield auth


@pytest.fixture
def mock_context_service():
    with patch("context_service.mcp.server.get_context_service") as m:
        svc = AsyncMock()
        svc.history.return_value = HistoryResult(
            timeline=[
                HistoryEntry(
                    node_id="node-old",
                    content="OAuth tokens expire in 7 days",
                    valid_from=1000,
                    valid_to=2000,
                    confidence=0.9,
                    supersession_reason="Policy updated",
                ),
                HistoryEntry(
                    node_id="node-new",
                    content="OAuth tokens expire in 30 days",
                    valid_from=2000,
                    valid_to=None,
                    confidence=0.95,
                    supersession_reason=None,
                ),
            ],
            current={
                "node_id": "node-new",
                "content": "OAuth tokens expire in 30 days",
                "confidence": 0.95,
                "superseded_by": None,
            },
        )
        m.return_value = svc
        yield svc


@pytest.mark.asyncio
async def test_history_by_subject(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_history import _context_history

    result = await _context_history(
        silo_id=SILO_ID,
        subject="OAuth tokens",
    )

    assert "timeline" in result
    assert "current" in result
    assert result["entries_count"] == 2
    mock_context_service.history.assert_called_once()


@pytest.mark.asyncio
async def test_history_by_node_id(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_history import _context_history

    node_id = "node-new"
    result = await _context_history(
        silo_id=SILO_ID,
        node_id=node_id,
    )

    assert result["entries_count"] == 2
    call_kwargs = mock_context_service.history.call_args
    assert call_kwargs.kwargs["node_id"] == node_id


@pytest.mark.asyncio
async def test_history_invalid_silo(mock_auth):
    from context_service.mcp.tools.context_history import _context_history

    result = await _context_history(
        silo_id="not-a-uuid",
        subject="anything",
    )

    assert result["error"] == "invalid_silo_id"


@pytest.mark.asyncio
async def test_history_missing_input(mock_auth):
    from context_service.mcp.tools.context_history import _context_history

    result = await _context_history(
        silo_id=SILO_ID,
    )

    assert result["error"] == "missing_input"


@pytest.mark.asyncio
async def test_history_timeline_shape(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_history import _context_history

    result = await _context_history(
        silo_id=SILO_ID,
        subject="OAuth",
    )

    first = result["timeline"][0]
    assert "node_id" in first
    assert "content" in first
    assert "confidence" in first
    assert "supersession_reason" in first
