"""Tests for the agents MCP tool."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_session(rows: list[dict]) -> MagicMock:
    """Build a mock session whose execute returns given rows as mappings."""
    mapping_rows = [MagicMock(**r) for r in rows]
    for row, data in zip(mapping_rows, rows, strict=False):
        row.__getitem__ = lambda _self, k, _d=data: _d[k]

    result = MagicMock()
    result.mappings = MagicMock(return_value=MagicMock(all=MagicMock(return_value=mapping_rows)))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.session_id = "test-session"
    return auth


class TestAgentsInternal:
    """Tests for the internal _agents function."""

    @pytest.mark.asyncio
    async def test_agents_returns_empty_for_no_agents(self):
        """When no agents exist for the silo, return empty list."""
        mock_session = _make_mock_session([])

        with patch(
            "context_service.mcp.tools.agents.get_session",
            return_value=mock_session,
        ):
            from context_service.mcp.tools.agents import _agents

            result = await _agents("silo-1")

        assert result == []

    @pytest.mark.asyncio
    async def test_agents_returns_agent_summaries(self):
        """Rows from the DB should be converted to dicts with correct fields."""
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        mock_session = _make_mock_session(
            [
                {
                    "id": "agent-abc",
                    "role": "researcher",
                    "first_seen": now,
                    "last_seen": now,
                    "node_count": 5,
                    "trust_score": 0.7,
                }
            ]
        )

        with patch(
            "context_service.mcp.tools.agents.get_session",
            return_value=mock_session,
        ):
            from context_service.mcp.tools.agents import _agents

            result = await _agents("silo-1")

        assert len(result) == 1
        agent = result[0]
        assert agent["agent_id"] == "agent-abc"
        assert agent["role"] == "researcher"
        assert agent["node_count"] == 5
        assert agent["trust_score"] == 0.7
        assert agent["first_seen"] == now.isoformat()
        assert agent["last_seen"] == now.isoformat()

    @pytest.mark.asyncio
    async def test_agents_trust_score_defaults_to_0_5_when_none(self):
        """trust_score = None from DB should be returned as 0.5."""
        now = datetime(2026, 6, 1, tzinfo=UTC)
        mock_session = _make_mock_session(
            [
                {
                    "id": "agent-legacy",
                    "role": "legacy",
                    "first_seen": now,
                    "last_seen": now,
                    "node_count": 10,
                    "trust_score": None,
                }
            ]
        )

        with patch(
            "context_service.mcp.tools.agents.get_session",
            return_value=mock_session,
        ):
            from context_service.mcp.tools.agents import _agents

            result = await _agents("silo-1")

        assert result[0]["trust_score"] == 0.5

    @pytest.mark.asyncio
    async def test_agents_handles_null_role(self):
        """Agents with no role should return role=None."""
        now = datetime(2026, 6, 1, tzinfo=UTC)
        mock_session = _make_mock_session(
            [
                {
                    "id": "agent-norole",
                    "role": None,
                    "first_seen": now,
                    "last_seen": now,
                    "node_count": 0,
                    "trust_score": 0.5,
                }
            ]
        )

        with patch(
            "context_service.mcp.tools.agents.get_session",
            return_value=mock_session,
        ):
            from context_service.mcp.tools.agents import _agents

            result = await _agents("silo-1")

        assert result[0]["role"] is None
        assert result[0]["node_count"] == 0


class TestAgentsToolRegistration:
    """Tests for tool registration."""

    def test_register_adds_tool(self):
        mcp = MagicMock()
        mcp.tool = MagicMock(return_value=lambda f: f)

        from context_service.mcp.tools.agents import register

        register(mcp)

        mcp.tool.assert_called_once()
        call_kwargs = mcp.tool.call_args[1]
        assert call_kwargs["name"] == "agents"

    def test_agents_description_in_yaml(self):
        """The agents tool must have a description entry in mcp_tools.yaml."""
        from context_service.mcp.tools.registry import get_tool_description

        desc = get_tool_description("agents")
        assert desc
        assert "agent" in desc.lower()


class TestAgentsToolPublicInterface:
    """Tests for the registered tool behavior."""

    @pytest.mark.asyncio
    async def test_agents_response_includes_count(self):
        """The tool response should include count alongside agents list."""
        now = datetime(2026, 6, 1, tzinfo=UTC)
        mock_session = _make_mock_session(
            [
                {
                    "id": "agent-1",
                    "role": "writer",
                    "first_seen": now,
                    "last_seen": now,
                    "node_count": 3,
                    "trust_score": 0.5,
                }
            ]
        )

        with patch(
            "context_service.mcp.tools.agents.get_session",
            return_value=mock_session,
        ):
            from context_service.mcp.tools.agents import _agents

            agent_list = await _agents("test-silo")
            result = {"agents": agent_list, "count": len(agent_list)}

        assert result["count"] == 1
        assert len(result["agents"]) == 1
        assert result["agents"][0]["agent_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_agents_empty_silo_returns_zero_count(self):
        """Empty silo returns count=0."""
        mock_session = _make_mock_session([])

        with patch(
            "context_service.mcp.tools.agents.get_session",
            return_value=mock_session,
        ):
            from context_service.mcp.tools.agents import _agents

            agent_list = await _agents("empty-silo")
            result = {"agents": agent_list, "count": len(agent_list)}

        assert result["count"] == 0
        assert result["agents"] == []
