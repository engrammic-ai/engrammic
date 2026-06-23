"""FastAPI auth dependency with dev bypass and API key support."""

from __future__ import annotations

from fastapi import HTTPException, Request

from context_service.auth.context import AuthContext
from context_service.config.logging import get_logger
from context_service.config.settings import get_settings

logger = get_logger(__name__)

_dev_bypass_logged = False


async def get_auth_context(request: Request) -> AuthContext:
    """Resolve the auth context for a request.

    Auth cascade:
    1. Dev bypass when AUTH_ENABLED=false
    2. WorkOS API key if token starts with sk_
    3. WorkOS sealed session (OAuth) otherwise
    """
    global _dev_bypass_logged

    settings = get_settings()

    if not settings.auth_enabled:
        if not _dev_bypass_logged:
            logger.info("auth.dev_bypass_active", reason="AUTH_ENABLED=false")
            _dev_bypass_logged = True
        return AuthContext(
            org_id=settings.dev_org_id,
            user_id=settings.dev_user_id,
            email=None,
            is_dev=True,
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing or malformed Authorization header")

    token = auth_header.removeprefix("Bearer ").strip()

    # Try API key first (WorkOS keys prefixed with sk_)
    if token.startswith("sk_"):
        from context_service.auth.api_key import resolve_api_key

        api_key_context = await resolve_api_key(token)
        if api_key_context is not None:
            return api_key_context
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Fall back to WorkOS sealed session (OAuth)
    from context_service.auth import workos_client

    try:
        return await workos_client.verify_session(token)
    except ValueError as exc:
        logger.warning("auth.session_verification_failed", error=str(exc))
        raise HTTPException(status_code=401, detail="Session verification failed") from exc
