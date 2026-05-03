"""Pre-import MCP tool modules so mock.patch targets are resolvable."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import context_service.mcp.tools.context_get  # noqa: F401
import context_service.mcp.tools.context_graph  # noqa: F401
import context_service.mcp.tools.context_link  # noqa: F401
import context_service.mcp.tools.context_query  # noqa: F401


@pytest.fixture(autouse=True)
def mock_silo_validation():
    """Auto-mock silo ownership validation for all MCP tool tests."""
    with (
        patch(
            "context_service.services.silo.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "context_service.mcp.server.get_silo_service",
            return_value=AsyncMock(),
        ),
    ):
        yield
