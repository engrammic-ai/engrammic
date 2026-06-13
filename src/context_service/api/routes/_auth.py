"""Shared auth helpers for REST API routes.

Uses get_auth_context for token verification when AUTH_ENABLED=true.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from context_service.api.auth_dep import get_auth_context
from context_service.auth.context import AuthContext
from context_service.config.settings import get_settings
from context_service.services.models import derive_silo_id


async def require_auth(request: Request) -> AuthContext:
    """Dependency that requires valid authentication.

    In dev mode (AUTH_ENABLED=false): returns dev context
    In prod mode: verifies Bearer token via WorkOS
    """
    return await get_auth_context(request)


async def get_authenticated_silo(
    auth: AuthContext = Depends(require_auth),  # noqa: B008
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
) -> tuple[str, str | None]:
    """Get silo_id from authenticated context.

    The silo_id is derived from the verified org_id in the auth context,
    NOT from a caller-supplied header. This ensures tenant isolation.

    Returns:
        Tuple of (silo_id, session_id)
    """
    silo_id = str(derive_silo_id(auth.org_id))
    session_id = x_session_id or (auth.user_id if auth.is_dev else None)
    return silo_id, session_id


# Backwards compatibility - deprecated, use get_authenticated_silo instead
async def get_silo_context(
    x_silo_id: str | None,
    x_session_id: str | None = None,
    require_session: bool = False,
) -> tuple[str, str | None]:
    """DEPRECATED: Use get_authenticated_silo dependency instead.

    This function trusts caller-supplied headers without verification.
    Only use for endpoints that have their own auth mechanism.
    """
    settings = get_settings()

    silo_id: str
    session_id: str | None
    if not settings.auth_enabled:
        silo_id = x_silo_id or settings.dev_org_id
        session_id = x_session_id or "dev-session"
    else:
        if not x_silo_id:
            raise HTTPException(status_code=400, detail="X-Silo-ID header is required")
        if require_session and not x_session_id:
            raise HTTPException(status_code=400, detail="X-Session-ID header is required")
        silo_id = x_silo_id
        session_id = x_session_id

    return str(derive_silo_id(silo_id)), session_id
