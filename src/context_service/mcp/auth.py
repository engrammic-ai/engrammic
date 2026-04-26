# context_service/mcp/auth.py
"""MCP authentication - simplified API key auth."""

from __future__ import annotations

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

DEV_ORG_ID = "dev-org"
ALL_PERMISSIONS = ["read", "write", "admin"]

_mcp_auth_context: ContextVar[MCPAuthContext | None] = ContextVar("mcp_auth_context", default=None)


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
        ValueError: If authentication fails.
    """
    expected_key = os.environ.get("MCP_API_KEY")

    # Dev mode: no API key configured
    if not expected_key:
        logger.debug("MCP running in dev mode (no MCP_API_KEY)")
        return MCPAuthContext(
            org_id=DEV_ORG_ID,
            permissions=list(ALL_PERMISSIONS),
            is_dev_mode=True,
        )

    # Validate Bearer token
    if not authorization:
        raise ValueError("Missing Authorization header")

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ValueError("Invalid Authorization header format")

    token = parts[1].strip()
    if not token:
        raise ValueError("Empty API key")

    if token != expected_key:
        raise ValueError("Invalid API key")

    # In production, org_id would come from API key lookup
    # For now, use env var or default
    org_id = os.environ.get("MCP_ORG_ID", "default-org")

    return MCPAuthContext(
        org_id=org_id,
        permissions=list(ALL_PERMISSIONS),
        is_dev_mode=False,
    )


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware for MCP authentication."""

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
            return JSONResponse(
                status_code=401,
                content={"error": str(e)},
            )

        finally:
            clear_mcp_auth()
