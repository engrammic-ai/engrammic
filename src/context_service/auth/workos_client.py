"""WorkOS session verification wrapper.

The `workos` SDK is imported lazily so this module loads cleanly when the
`auth` optional extra is not installed. The dev bypass path never calls
verify_session, so it never triggers the import.

TODO: Validate the exact WorkOS SDK call against a real tenant once credentials
are available. The `user_management.authenticate_with_session_token` surface
may differ from the placeholder below — confirm against workos SDK >= 4.0.
"""

from __future__ import annotations

from typing import Any

from context_service.auth.context import AuthContext
from context_service.config.settings import get_settings


async def verify_session(token: str) -> AuthContext:
    """Verify a WorkOS session token and return an AuthContext.

    Raises ValueError on an invalid or expired token.
    """
    import workos  # type: ignore[import-not-found]  # lazy: only when auth extra installed

    settings = get_settings()
    client: Any = workos.WorkOS(api_key=settings.workos_api_key)

    # TODO: Confirm exact method name against workos SDK >= 4.0 with a real tenant.
    # Expected shape:
    #   profile = client.user_management.authenticate_with_session_token(token=token)
    #   org_id  = profile.organization_id
    #   user_id = profile.user.id
    #   email   = profile.user.email
    try:
        profile: Any = client.user_management.authenticate_with_session_token(token=token)
        return AuthContext(
            org_id=profile.organization_id,
            user_id=profile.user.id,
            email=profile.user.email,
            is_dev=False,
        )
    except Exception as exc:
        raise ValueError(f"WorkOS session verification failed: {exc}") from exc
