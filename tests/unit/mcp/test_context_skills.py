"""Unit tests for context_skills MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.mcp.tools.context_skills import _context_skills_impl


@pytest.mark.asyncio
async def test_list_action() -> None:
    """List action should return skills."""
    mock_service = MagicMock()
    mock_service.list = AsyncMock(return_value=[])

    result = await _context_skills_impl(
        service=mock_service,
        silo_id="silo-123",
        action="list",
    )

    assert "skills" in result
    assert "count" in result
    mock_service.list.assert_called_once()


@pytest.mark.asyncio
async def test_get_action_requires_name() -> None:
    """Get action without name should error."""
    mock_service = MagicMock()

    result = await _context_skills_impl(
        service=mock_service,
        silo_id="silo-123",
        action="get",
        name=None,
    )

    assert "error" in result


@pytest.mark.asyncio
async def test_search_action_requires_query() -> None:
    """Search action without query should error."""
    mock_service = MagicMock()

    result = await _context_skills_impl(
        service=mock_service,
        silo_id="silo-123",
        action="search",
        query=None,
    )

    assert "error" in result


@pytest.mark.asyncio
async def test_get_action_returns_skill() -> None:
    """Get action with valid name returns skill."""
    mock_skill = MagicMock()
    mock_skill.model_dump.return_value = {"name": "engrammic:observe", "description": "Store observation"}
    mock_service = MagicMock()
    mock_service.get = AsyncMock(return_value=mock_skill)

    result = await _context_skills_impl(
        service=mock_service,
        silo_id="silo-123",
        action="get",
        name="engrammic:observe",
    )

    assert "skill" in result
    mock_service.get.assert_called_once_with("silo-123", "engrammic:observe")


@pytest.mark.asyncio
async def test_get_action_not_found() -> None:
    """Get action for missing skill returns error."""
    mock_service = MagicMock()
    mock_service.get = AsyncMock(return_value=None)

    result = await _context_skills_impl(
        service=mock_service,
        silo_id="silo-123",
        action="get",
        name="nonexistent:skill",
    )

    assert "error" in result
    assert "nonexistent:skill" in result["error"]


@pytest.mark.asyncio
async def test_search_action_returns_results() -> None:
    """Search action returns matching skills."""
    mock_skill = MagicMock()
    mock_skill.model_dump.return_value = {"name": "engrammic:observe", "description": "Store observation"}
    mock_service = MagicMock()
    mock_service.search = AsyncMock(return_value=[mock_skill])

    result = await _context_skills_impl(
        service=mock_service,
        silo_id="silo-123",
        action="search",
        query="observe",
    )

    assert "skills" in result
    assert result["count"] == 1
    mock_service.search.assert_called_once_with("silo-123", "observe", namespace=None, limit=50)


@pytest.mark.asyncio
async def test_unknown_action() -> None:
    """Unknown action returns error."""
    mock_service = MagicMock()

    result = await _context_skills_impl(
        service=mock_service,
        silo_id="silo-123",
        action="unknown",  # type: ignore[arg-type]
    )

    assert "error" in result
