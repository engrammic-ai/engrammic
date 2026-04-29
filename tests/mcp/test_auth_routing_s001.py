"""Regression test for S-001 — MCP tools route to the startup-resolved auth
context, not the ContextVar-backed get_mcp_auth() that the never-mounted
MCPAuthMiddleware would have populated. See codebase-review-2026-04-28.md.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

TOOL_MODULES = [
    "context_service.mcp.tools.context_assert",
    "context_service.mcp.tools.context_commit",
    "context_service.mcp.tools.context_get",
    "context_service.mcp.tools.context_graph",
    "context_service.mcp.tools.context_history",
    "context_service.mcp.tools.context_link",
    "context_service.mcp.tools.context_provenance",
    "context_service.mcp.tools.context_query",
    "context_service.mcp.tools.context_reason",
    "context_service.mcp.tools.context_reflect",
    "context_service.mcp.tools.context_remember",
    "context_service.mcp.tools.silo",
]


@pytest.mark.parametrize("module_name", TOOL_MODULES)
def test_tool_does_not_import_broken_get_mcp_auth(module_name: str) -> None:
    module = importlib.import_module(module_name)
    source = inspect.getsource(module)
    assert "from context_service.mcp.auth import get_mcp_auth" not in source, (
        f"{module_name} re-introduced the broken auth import (S-001)"
    )
    if "get_mcp_auth(" in source:
        assert "get_mcp_auth_context(" in source, (
            f"{module_name} calls bare get_mcp_auth() instead of get_mcp_auth_context() (S-001)"
        )


@pytest.mark.asyncio
async def test_get_mcp_auth_context_returns_dev_fallback_when_no_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from context_service.config import settings as settings_module
    from context_service.mcp import server

    real_get_settings = settings_module.get_settings
    real_settings = real_get_settings()
    monkeypatch.setattr(
        real_settings,
        "auth_enabled",
        False,
        raising=False,
    )

    # Simulate stdio / no-HTTP-request: get_http_headers returns {}.
    monkeypatch.setattr(server, "get_http_headers", lambda **_kw: {})

    auth = await server.get_mcp_auth_context()
    assert auth.org_id
    assert auth.is_dev is True
