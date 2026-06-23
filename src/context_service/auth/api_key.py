# src/context_service/auth/api_key.py
"""WorkOS API key authentication."""

from __future__ import annotations

import structlog

from context_service.auth.context import AuthContext

logger = structlog.get_logger(__name__)


async def resolve_api_key(token: str) -> AuthContext | None:
    """Resolve auth context from WorkOS API key (sk_* prefix).

    Returns AuthContext if valid, None if invalid or WorkOS not configured.
    """
    from context_service.config.settings import get_settings

    settings = get_settings()
    api_key = settings.workos_api_key.get_secret_value() if settings.workos_api_key else None
    if api_key is None:
        logger.debug("api_key_auth_skipped", reason="no_workos_api_key_configured")
        return None

    key_prefix = token[:12] if len(token) >= 12 else token[:8]
    try:
        import workos

        client = workos.WorkOSClient(api_key=api_key, client_id=settings.workos_client_id)
        response = client.api_keys.create_validation(value=token)

        if response.api_key is None:
            logger.debug(
                "api_key_auth_failed", reason="validation_returned_none", key_prefix=key_prefix
            )
            return None

        # owner.type is always "organization", owner.id is the org ID
        org_id = response.api_key.owner.id

        logger.info("api_key_auth_ok", key_prefix=key_prefix, org_id=org_id)
        return AuthContext(
            org_id=org_id,
            user_id=f"apikey:{response.api_key.id}",
            email=None,
            is_dev=False,
            agent_id=f"apikey:{response.api_key.id}",
            session_id=None,
            db_user_id=None,
        )
    except Exception as exc:
        logger.warning(
            "api_key_auth_failed", reason="exception", key_prefix=key_prefix, error=str(exc)
        )
        return None
