# context_service/mcp/__init__.py
"""MCP server and tools."""

from context_service.mcp.auth import (
    MCPAuthContext,
    MCPAuthMiddleware,
    clear_mcp_auth,
    get_mcp_auth,
    set_mcp_auth,
    validate_mcp_request,
)
from context_service.mcp.server import (
    configure_services,
    create_mcp_server,
    get_context_service,
    get_silo_service,
)

__all__ = [
    # Server
    "configure_services",
    "create_mcp_server",
    "get_context_service",
    "get_silo_service",
    # Auth
    "MCPAuthContext",
    "MCPAuthMiddleware",
    "clear_mcp_auth",
    "get_mcp_auth",
    "set_mcp_auth",
    "validate_mcp_request",
]
