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
from uuid import UUID

import structlog

from context_service.auth.context import AuthContext
from context_service.auth.org_provisioning import resolve_or_create_org
from context_service.config.settings import get_settings

logger = structlog.get_logger(__name__)


async def verify_session(token: str) -> AuthContext:
    """Verify a sealed WorkOS session and return an AuthContext.

    Raises ValueError on an invalid, expired, or unauthenticated session.
    """
    import workos

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

    session_org_id = response.organization_id

    first_name: str | None = user.get("first_name")
    last_name: str | None = user.get("last_name")
    full_name: str | None = " ".join(filter(None, [first_name, last_name])) or None
    email = user.get("email", "")

    db_user_id: UUID | None = None
    effective_org_id: str | None = session_org_id
    try:
        from context_service.db.postgres import get_session
        from context_service.services.models import derive_silo_id
        from context_service.services.user import UserService

        async with get_session() as session:
            effective_org_id = await resolve_or_create_org(
                session,
                workos_user_id=user["id"],
                session_org_id=session_org_id,
                name=full_name,
                email=email,
            )
            user_service = UserService(session)
            db_user = await user_service.upsert_user(
                workos_user_id=user["id"],
                org_id=effective_org_id,
                silo_id=str(derive_silo_id(effective_org_id)),
                email=email,
                name=full_name,
            )
            db_user_id = db_user.id
            await session.commit()
    except Exception as exc:
        logger.warning(
            "user_upsert_failed",
            error=str(exc),
            workos_user_id=user["id"],
        )

    # Fail open only when the user already had an org (existing contract): a
    # transient DB error still yields a valid AuthContext with db_user_id=None.
    # A genuinely-new no-org user that could not be provisioned has no valid
    # silo, so fail closed rather than emit a None org id.
    if effective_org_id is None:
        raise ValueError("Could not resolve or provision an organization for the user")

    return AuthContext(
        org_id=effective_org_id,
        user_id=user["id"],
        email=email,
        is_dev=False,
        db_user_id=db_user_id,
    )
