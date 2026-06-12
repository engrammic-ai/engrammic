"""Shared auth helpers for REST API routes.

Respects AUTH_ENABLED while maintaining silo scoping for all endpoints.
"""

from __future__ import annotations

from fastapi import HTTPException

from context_service.config.settings import get_settings
from context_service.services.models import derive_silo_id


async def get_silo_context(
    x_silo_id: str | None,
    x_session_id: str | None = None,
    require_session: bool = False,
) -> tuple[str, str | None]:
    """Get silo_id and session_id, respecting AUTH_ENABLED.

    Dev mode (AUTH_ENABLED=false): falls back to dev_org_id/"dev-session"
    Prod mode: requires headers

    Returns:
        Tuple of (silo_id, session_id) where silo_id is derived UUID string
    """
    settings = get_settings()

    if not settings.auth_enabled:
        # Dev mode: use header or fallback to dev defaults
        silo_id = x_silo_id or settings.dev_org_id
        session_id = x_session_id or "dev-session"
    else:
        # Prod mode: require headers
        if not x_silo_id:
            raise HTTPException(status_code=400, detail="X-Silo-ID header is required")
        if require_session and not x_session_id:
            raise HTTPException(status_code=400, detail="X-Session-ID header is required")
        silo_id = x_silo_id
        session_id = x_session_id

    return str(derive_silo_id(silo_id)), session_id
