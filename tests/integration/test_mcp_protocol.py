# tests/integration/test_mcp_protocol.py
"""MCP protocol-level tests: tool registration and invocation via FastMCP."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from context_service.auth.context import AuthContext
from context_service.mcp.server import create_mcp_server
from context_service.mcp.tools import register_all

EXPECTED_TOOLS = {
    "remember",
    "learn",
    "decide",
    "accept",
    "recall",
    "trace",
    "history",
    "link",
    "patterns",
    "reason",
    "reflect",
    "hypothesize",
    "revise",
    "commit",
    "forget",
    "dismiss",
    "tick",
}

_DEV_AUTH = AuthContext(
    org_id="test-org",
    user_id="test-user",
    email=None,
    is_dev=True,
)


@pytest.mark.integration
class TestMCPProtocol:
    @pytest.mark.asyncio
    async def test_all_tools_registered(self) -> None:
        mcp = FastMCP("test-registration")
        register_all(mcp)
        tools = await mcp.list_tools()
        registered = {t.name for t in tools}
        assert registered == EXPECTED_TOOLS

    def test_create_mcp_server_returns_fastmcp(self) -> None:
        server = create_mcp_server()
        assert isinstance(server, FastMCP)
        assert server.name == "engrammic"

    @pytest.mark.asyncio
    async def test_create_mcp_server_tool_count(self) -> None:
        server = create_mcp_server()
        tools = await server.list_tools()
        registered = {t.name for t in tools}
        # create_mcp_server uses the default profile (reasoning)
        assert registered == EXPECTED_TOOLS

    @pytest.mark.asyncio
    async def test_tool_invocation_structure(self) -> None:
        """context_query with an invalid (unowned) silo returns an error dict."""
        from context_service.mcp.tools.context_query import _context_query

        with (
            patch(
                "context_service.mcp.tools.context_query.get_mcp_auth_context",
                new=AsyncMock(return_value=_DEV_AUTH),
            ),
            patch(
                "context_service.mcp.tools.context_query.get_context_service",
                return_value=MagicMock(),
            ),
            patch(
                "context_service.mcp.tools.context_query.get_silo_service",
                return_value=MagicMock(),
            ),
            patch(
                "context_service.mcp.tools.context_query.validate_silo_ownership",
                new=AsyncMock(return_value={"error": "silo_not_found"}),
            ),
        ):
            result: dict[str, Any] = await _context_query(
                silo_id="00000000-0000-0000-0000-000000000000",
                query="test query",
            )

        assert isinstance(result, dict)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_error_on_invalid_silo(self) -> None:
        """Invalid (unowned) silo_id returns an error response."""
        from context_service.mcp.tools.context_store import _context_remember

        with (
            patch(
                "context_service.mcp.tools.context_store.get_mcp_auth_context",
                new=AsyncMock(return_value=_DEV_AUTH),
            ),
            patch(
                "context_service.mcp.tools.context_store.get_silo_service",
                return_value=MagicMock(),
            ),
            patch(
                "context_service.mcp.tools.context_store.validate_silo_ownership",
                new=AsyncMock(return_value={"error": "silo_not_found"}),
            ),
        ):
            result: dict[str, Any] = await _context_remember(
                silo_id="not-a-real-silo",
                content="hello",
            )

        assert isinstance(result, dict)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_error_on_missing_required_param(self) -> None:
        """Calling a tool with missing required params raises TypeError before hitting services."""
        from context_service.mcp.tools.context_query import _context_query

        with pytest.raises(TypeError):
            await _context_query()  # type: ignore[call-arg]

    @pytest.mark.asyncio
    async def test_invalid_layer_returns_error(self) -> None:
        """context_query with an unknown layer name returns an error dict."""
        from context_service.mcp.tools.context_query import _context_query

        with (
            patch(
                "context_service.mcp.tools.context_query.get_mcp_auth_context",
                new=AsyncMock(return_value=_DEV_AUTH),
            ),
            patch(
                "context_service.mcp.tools.context_query.get_context_service",
                return_value=MagicMock(),
            ),
            patch(
                "context_service.mcp.tools.context_query.get_silo_service",
                return_value=MagicMock(),
            ),
            patch(
                "context_service.mcp.tools.context_query.validate_silo_ownership",
                new=AsyncMock(return_value=None),
            ),
        ):
            result: dict[str, Any] = await _context_query(
                silo_id="00000000-0000-0000-0000-000000000000",
                query="test",
                layers=["not_a_real_layer"],
            )

        assert isinstance(result, dict)
        assert result.get("error") == "invalid_layer"
