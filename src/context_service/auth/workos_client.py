"""WorkOS session verification wrapper.

Uses the WorkOS SDK v6 sealed-session flow: clients send the sealed session
string (set by WorkOS hosted UI on login) as a bearer token; we unseal +
verify with the configured cookie_password. v6 dropped the v4 raw-JWT
`authenticate_with_session_token` method in favor of this pattern.

The `workos` SDK is imported lazily so this module loads cleanly when the
`auth` optional group is not installed. The dev bypass path never calls
verify_session, so it never triggers the import.
"""

from __future__ import annotations

from typing import Any

from context_service.auth.context import AuthContext
from context_service.config.settings import get_settings


async def verify_session(token: str) -> AuthContext:
    """Verify a sealed WorkOS session and return an AuthContext.

    Raises ValueError on an invalid, expired, or unauthenticated session.
    """
    import workos  # lazy: heavy import only when verify_session is actually called

    settings = get_settings()
    api_key = settings.workos_api_key.get_secret_value() if settings.workos_api_key else None
    cookie_password = (
        settings.workos_cookie_password.get_secret_value()
        if settings.workos_cookie_password
        else None
    )
    if cookie_password is None:
        raise ValueError("WORKOS_COOKIE_PASSWORD must be configured for session verification")

    client: Any = workos.WorkOSClient(api_key=api_key, client_id=settings.workos_client_id)

    try:
        response: Any = client.user_management.authenticate_with_session_cookie(
            session_data=token,
            cookie_password=cookie_password,
        )
    except Exception as exc:
        raise ValueError(f"WorkOS session verification failed: {exc}") from exc

    if not getattr(response, "authenticated", False):
        reason = getattr(response, "reason", "unknown")
        raise ValueError(f"WorkOS session not authenticated: {reason}")

    user: dict[str, Any] | None = response.user
    if user is None:
        raise ValueError("WorkOS session response missing user")

    org_id = response.organization_id
    if org_id is None:
        raise ValueError("WorkOS session response missing organization_id")

    return AuthContext(
        org_id=org_id,
        user_id=user["id"],
        email=user.get("email", ""),
        is_dev=False,
    )
