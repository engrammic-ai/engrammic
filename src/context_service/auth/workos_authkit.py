"""WorkOS AuthKit OAuth authorization code flow helpers.

Handles the OAuth redirect flow used by MCP clients: generating the
authorization URL and exchanging the returned code for user information.

The `workos` SDK is imported lazily so this module loads cleanly when the
`auth` optional group is not installed.
"""

from __future__ import annotations

from typing import Any

import structlog

from context_service.config.settings import get_settings

logger = structlog.get_logger(__name__)


async def get_authorization_url(redirect_uri: str, state: str) -> str:
    """Generate a WorkOS AuthKit authorization URL.

    The returned URL redirects the user to WorkOS login (magic link or SSO
    depending on WorkOS configuration). The `state` parameter is passed
    through for CSRF protection.

    Raises ValueError if required settings are missing.
    """
    import workos  # type: ignore[import-not-found]  # lazy: optional dep

    settings = get_settings()
    api_key = settings.workos_api_key.get_secret_value() if settings.workos_api_key else None
    if api_key is None:
        raise ValueError("WORKOS_API_KEY must be configured for AuthKit")
    if not settings.workos_client_id:
        raise ValueError("WORKOS_CLIENT_ID must be configured for AuthKit")

    client: Any = workos.WorkOSClient(api_key=api_key, client_id=settings.workos_client_id)

    try:
        url: str = client.user_management.get_authorization_url(
            redirect_uri=redirect_uri,
            state=state,
            provider=None,  # Let WorkOS choose (magic link or SSO)
        )
    except Exception as exc:
        raise ValueError(f"WorkOS get_authorization_url failed: {exc}") from exc

    return url


async def exchange_code_for_user(code: str) -> dict[str, Any]:
    """Exchange a WorkOS authorization code for user information.

    Returns a dict with keys: id, email, organization_id.

    Raises ValueError on missing configuration or if the exchange fails.
    """
    import workos  # lazy: optional dep

    settings = get_settings()
    api_key = settings.workos_api_key.get_secret_value() if settings.workos_api_key else None
    if api_key is None:
        raise ValueError("WORKOS_API_KEY must be configured for AuthKit")
    if not settings.workos_client_id:
        raise ValueError("WORKOS_CLIENT_ID must be configured for AuthKit")

    client: Any = workos.WorkOSClient(api_key=api_key, client_id=settings.workos_client_id)

    try:
        response: Any = client.user_management.authenticate_with_code(
            code=code,
            code_verifier=None,  # WorkOS handles PKCE internally for AuthKit
        )
    except Exception as exc:
        raise ValueError(f"WorkOS code exchange failed: {exc}") from exc

    user: Any = response.user
    if user is None:
        raise ValueError("WorkOS code exchange response missing user")

    org_id: str | None = response.organization_id

    logger.info(
        "workos_authkit_exchange_success",
        user_id=user.id,
        organization_id=org_id,
    )

    return {
        "id": user.id,
        "email": user.email,
        "organization_id": org_id,
    }
