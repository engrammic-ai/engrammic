"""Tests for context_query tool."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_deps():
    with (
        patch("context_service.mcp.tools.context_query.get_mcp_auth_context") as auth_mock,
        patch("context_service.mcp.tools.context_query.get_context_service") as svc_mock,
        patch("context_service.mcp.tools.context_query.get_silo_service", return_value=MagicMock()),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        auth = MagicMock()
        auth.org_id = "test-org"
        auth_mock.return_value = auth

        svc = AsyncMock()
        svc.query.return_value = []
        svc_mock.return_value = svc

        yield {"auth": auth, "svc": svc}


def _make_query_result(node_id: uuid.UUID | None = None) -> MagicMock:
    r = MagicMock()
    r.node_id = node_id or uuid.uuid4()
    r.layer = "memory"
    r.content = "Test content"
    r.summary = None
    r.confidence = 0.9
    r.relevance_score = 0.85
    r.tags = ["test"]
    r.created_at = datetime(2026, 4, 27, tzinfo=UTC)
    return r


@pytest.mark.asyncio
async def test_query_basic_returns_results(mock_deps):
    from context_service.mcp.tools.context_query import _context_query

    mock_deps["svc"].query.return_value = [_make_query_result()]

    result = await _context_query(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="What are the OAuth token settings?",
    )

    assert "results" in result
    assert len(result["results"]) == 1
    assert "search_time_ms" in result
    assert "total_candidates" in result
    mock_deps["svc"].query.assert_called_once()


@pytest.mark.asyncio
async def test_query_empty_results(mock_deps):
    from context_service.mcp.tools.context_query import _context_query

    result = await _context_query(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="nonexistent topic",
    )

    assert result["results"] == []
    assert result["total_candidates"] == 0


@pytest.mark.asyncio
async def test_query_invalid_silo_id(mock_deps):
    from context_service.mcp.tools.context_query import _context_query

    with patch(
        "context_service.mcp.tools.context_query.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"},
    ):
        result = await _context_query(silo_id="not-a-uuid", query="test")

    assert result["error"] == "invalid_silo_id"


@pytest.mark.asyncio
async def test_query_wrong_silo_id(mock_deps):
    from context_service.mcp.tools.context_query import _context_query

    with patch(
        "context_service.mcp.tools.context_query.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "silo_not_found", "silo_id": str(uuid.uuid4())},
    ):
        result = await _context_query(
            silo_id=str(uuid.uuid4()),
            query="test",
        )

    assert result["error"] == "silo_not_found"


@pytest.mark.asyncio
async def test_query_with_layer_filter(mock_deps):
    from context_service.mcp.tools.context_query import _context_query

    result = await _context_query(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="test",
        layers=["memory", "knowledge"],
    )

    assert "error" not in result
    call_kwargs = mock_deps["svc"].query.call_args.kwargs
    assert call_kwargs["layers"] is not None
    assert len(call_kwargs["layers"]) == 2


@pytest.mark.asyncio
async def test_query_invalid_layer(mock_deps):
    from context_service.mcp.tools.context_query import _context_query

    result = await _context_query(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="test",
        layers=["invalid_layer"],
    )

    assert result["error"] == "invalid_layer"
    assert "valid" in result


@pytest.mark.asyncio
async def test_query_with_filters(mock_deps):
    from context_service.mcp.tools.context_query import _context_query

    result = await _context_query(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="test",
        filters={"min_confidence": 0.7, "tags": ["important"]},
    )

    assert "error" not in result
    call_kwargs = mock_deps["svc"].query.call_args.kwargs
    assert call_kwargs["filters"] is not None
    assert call_kwargs["filters"].min_confidence == 0.7


@pytest.mark.asyncio
async def test_query_invalid_filters(mock_deps):
    from context_service.mcp.tools.context_query import _context_query

    result = await _context_query(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="test",
        filters={"invalid_field_xyz": 999},
    )

    assert result["error"] == "invalid_filters"


@pytest.mark.asyncio
async def test_query_rejects_as_of(mock_deps):
    from context_service.mcp.tools.context_query import _context_query

    result = await _context_query(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="test",
        as_of="2026-01-01T00:00:00",
    )

    assert result["error"] == "as_of_not_supported"


@pytest.mark.asyncio
async def test_query_result_structure(mock_deps):
    from context_service.mcp.tools.context_query import _context_query

    node_id = uuid.uuid4()
    mock_deps["svc"].query.return_value = [_make_query_result(node_id)]

    result = await _context_query(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="test",
    )

    r = result["results"][0]
    assert r["node_id"] == str(node_id)
    assert r["layer"] == "memory"
    assert r["content"] == "Test content"
    assert r["confidence"] == 0.9
    assert r["relevance_score"] == 0.85
    assert r["tags"] == ["test"]
    assert r["created_at"] is not None
