"""Per-request MCP auth context resolution.

The resolver takes an inbound `Authorization` header value (typically read
from the live FastMCP request via `fastmcp.server.dependencies.get_http_headers`)
and returns an `AuthContext` after WorkOS sealed-session verification.

The dev fallback (no header, `AUTH_ENABLED=false`) is wired in
`context_service.mcp.server.get_mcp_auth_context`, not here — this module is
strictly the per-header resolver and fails closed on any malformed/missing
input.

`MCPAuthError` is owned by `context_service.mcp.auth` (the canonical
location, also used by the request-layer guard `validate_mcp_request`); we
re-export it here as a convenience for resolver callers.
"""

from __future__ import annotations

from context_service.auth.context import AuthContext
from context_service.config.logging import get_logger
from context_service.mcp.auth import MCPAuthError

__all__ = ["MCPAuthError", "resolve_mcp_auth_from_header"]

logger = get_logger(__name__)


async def resolve_mcp_auth_from_header(authorization: str) -> AuthContext:
    """Resolve an `AuthContext` from an inbound Authorization header value.

    Expects a `Bearer <sealed-session>` token. The sealed session is
    forwarded to WorkOS for verification.

    Raises:
        MCPAuthError: missing, empty, or malformed header; rejected by WorkOS.
    """
    if not authorization:
        raise MCPAuthError("Missing Authorization header on authenticated MCP transport")

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise MCPAuthError("Invalid Authorization header format; expected 'Bearer <token>'")

    token = parts[1].strip()
    if not token:
        raise MCPAuthError("Empty bearer token on authenticated MCP transport")

    from context_service.auth import workos_client

    try:
        return await workos_client.verify_session(token)
    except ValueError as exc:
        logger.error("auth.mcp_token_invalid", hint="bearer token rejected by WorkOS")
        raise MCPAuthError(f"Bearer token rejected by WorkOS: {exc}") from exc
