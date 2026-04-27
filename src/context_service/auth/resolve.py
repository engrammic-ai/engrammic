"""Transport-agnostic auth context resolution.

MCP transport-level auth header negotiation with FastMCP is deferred (see plan
v1a-auth-toggle.md). For v1-alpha, when AUTH_ENABLED=true, the MCP surface reads
MCP_DEV_TOKEN from the environment as a stop-gap bearer token.

TODO: Replace MCP_DEV_TOKEN stop-gap with proper FastMCP transport auth once
FastMCP exposes per-request header access in a stable, non-HTTP transport-safe way.
See plan v1a-auth-toggle.md "Out of scope" section.
"""

from __future__ import annotations

import os

from context_service.auth.context import AuthContext
from context_service.config.logging import get_logger
from context_service.config.settings import get_settings

logger = get_logger(__name__)

_dev_bypass_logged = False


class MCPAuthError(RuntimeError):
    """Raised when MCP auth resolution fails under AUTH_ENABLED=true.

    Auth must fail closed: silently degrading to a dev AuthContext would
    defeat the boot-time prod-guard in Settings.
    """


async def resolve_mcp_auth() -> AuthContext:
    """Resolve AuthContext for an MCP request.

    Dev bypass: AUTH_ENABLED=false returns the dev AuthContext.
    Auth enabled: uses MCP_DEV_TOKEN env var as a stop-gap bearer token for
    WorkOS verification. Missing or invalid tokens raise MCPAuthError —
    never silently fall back to dev.
    """
    global _dev_bypass_logged

    settings = get_settings()

    if not settings.auth_enabled:
        if not _dev_bypass_logged:
            logger.info("auth.mcp_dev_bypass_active", reason="AUTH_ENABLED=false")
            _dev_bypass_logged = True
        return AuthContext(
            org_id=settings.dev_org_id,
            user_id=settings.dev_user_id,
            email=None,
            is_dev=True,
        )

    # TODO: Replace with per-request header extraction once FastMCP exposes a
    # stable transport-agnostic header ContextVar outside HTTP-only code paths.
    token = os.environ.get("MCP_DEV_TOKEN", "")
    if not token:
        logger.error(
            "auth.mcp_token_missing",
            hint="Set MCP_DEV_TOKEN for authenticated MCP dev access",
        )
        raise MCPAuthError(
            "MCP auth required (AUTH_ENABLED=true) but MCP_DEV_TOKEN not set"
        )

    from context_service.auth import workos_client

    try:
        return await workos_client.verify_session(token)
    except ValueError as exc:
        logger.error("auth.mcp_token_invalid", hint="MCP_DEV_TOKEN rejected by WorkOS")
        raise MCPAuthError(f"MCP_DEV_TOKEN rejected by WorkOS: {exc}") from exc
