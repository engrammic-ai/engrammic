# context_service/mcp/auth.py
"""MCP authentication middleware and helpers.

Two middleware classes:
- ``MCPAuthMiddleware``: Legacy API key validation via MCP_API_KEY env var.
- ``MCPOAuthChallengeMiddleware``: Returns 401 with WWW-Authenticate header when
  no token is present, triggering OAuth flow in MCP clients (Cursor, Claude Code).

The OAuth challenge middleware is mounted in ``api/app.py`` when ``auth_enabled=true``.
Actual token validation (OAuth, WorkOS, API keys) happens in the tool layer via
``context_service.mcp.server.get_mcp_auth_context()``.

Note: ``MCPAuthMiddleware`` uses a ContextVar that requires the middleware to be
mounted. For per-request auth in tools, use ``get_mcp_auth_context()`` instead
of ``get_mcp_auth()``.
"""

from __future__ import annotations

import hmac
import os
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

logger = structlog.get_logger(__name__)

ALL_PERMISSIONS = ["read", "write", "admin"]

_mcp_auth_context: ContextVar[MCPAuthContext | None] = ContextVar("mcp_auth_context", default=None)


class MCPAuthError(ValueError):
    """Raised when MCP request authentication fails.

    Subclasses ``ValueError`` so existing middleware ``except ValueError``
    handlers continue to catch it during the v1-β transition.
    """


@dataclass
class MCPAuthContext:
    """Authentication context for MCP requests."""

    org_id: str
    permissions: list[str] = field(default_factory=list)
    is_dev_mode: bool = False

    def has_permission(self, permission: str) -> bool:
        """Check if the context has a specific permission."""
        return permission in self.permissions or "admin" in self.permissions


def get_mcp_auth() -> MCPAuthContext:
    """Get the current MCP authentication context.

    Raises:
        RuntimeError: If called outside of an MCP request context.
    """
    ctx = _mcp_auth_context.get()
    if ctx is None:
        raise RuntimeError("MCP auth context not set. Ensure MCPAuthMiddleware is configured.")
    return ctx


def set_mcp_auth(ctx: MCPAuthContext) -> None:
    """Set the MCP authentication context for the current request."""
    _mcp_auth_context.set(ctx)


def clear_mcp_auth() -> None:
    """Clear the MCP authentication context."""
    _mcp_auth_context.set(None)


async def validate_mcp_request(authorization: str | None) -> MCPAuthContext:
    """Validate an MCP request and return auth context.

    Uses simple API key validation from environment.

    Args:
        authorization: Authorization header value (Bearer token).

    Returns:
        MCPAuthContext with org_id and permissions.

    Raises:
        MCPAuthError: If authentication fails or MCP_API_KEY is not configured.
    """
    expected_key = os.environ.get("MCP_API_KEY")

    if not expected_key:
        raise MCPAuthError("MCP_API_KEY is not configured")

    # Validate Bearer token
    if not authorization:
        raise MCPAuthError("Missing Authorization header")

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise MCPAuthError("Invalid Authorization header format")

    token = parts[1].strip()
    if not token:
        raise MCPAuthError("Empty API key")

    # Timing-safe comparison to avoid leaking key bytes via response timing.
    if not hmac.compare_digest(token.encode("utf-8"), expected_key.strip().encode("utf-8")):
        raise MCPAuthError("Invalid API key")

    # In production, org_id would come from API key lookup
    # For now, use env var or default
    org_id = os.environ.get("MCP_ORG_ID", "default-org")

    return MCPAuthContext(
        org_id=org_id,
        permissions=list(ALL_PERMISSIONS),
        is_dev_mode=False,
    )


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware for MCP authentication (legacy API key auth)."""

    def __init__(self, app: Any) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process request and validate authentication."""
        # Only apply to MCP endpoints
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)

        try:
            authorization = request.headers.get("authorization")
            ctx = await validate_mcp_request(authorization)
            set_mcp_auth(ctx)

            response = await call_next(request)
            return response

        except ValueError as e:
            logger.warning("MCP auth failed", error=str(e))
            # Build resource_metadata URL for OAuth discovery
            scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get("host", request.url.netloc)
            resource_metadata_url = f"{scheme}://{host}/.well-known/oauth-protected-resource"

            return JSONResponse(
                status_code=401,
                content={"error": str(e)},
                headers={
                    "WWW-Authenticate": f'Bearer resource_metadata="{resource_metadata_url}"',
                },
            )

        finally:
            clear_mcp_auth()


class MCPOAuthChallengeMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that returns 401 with OAuth discovery header when no token.

    This middleware triggers the OAuth flow in MCP clients (Cursor, Claude Code, etc.)
    by returning a 401 with WWW-Authenticate header pointing to the OAuth metadata.
    It does NOT validate the token - that happens in the tool layer via
    get_mcp_auth_context() which supports OAuth tokens, WorkOS sessions, and API keys.
    """

    def __init__(self, app: Any) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Return 401 challenge if no Authorization header, else pass through."""
        authorization = request.headers.get("authorization")

        if not authorization:
            logger.debug("mcp.oauth_challenge", path=request.url.path)
            scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get("host", request.url.netloc)
            resource_metadata_url = f"{scheme}://{host}/.well-known/oauth-protected-resource"

            return JSONResponse(
                status_code=401,
                content={"error": "Authorization required"},
                headers={
                    "WWW-Authenticate": f'Bearer resource_metadata="{resource_metadata_url}"',
                },
            )

        return await call_next(request)
