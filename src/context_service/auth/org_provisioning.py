"""Self-serve organization provisioning.

When a user authenticates with no organization (typical of self-serve
signup via the hosted AuthKit UI), provision a personal
``"{name}'s workspace"`` org so every identity resolves to a real silo.

WorkOS calls use the lazily-imported ``workos`` SDK (the ``auth`` group), so
this module imports cleanly when that group is not installed.
"""

from __future__ import annotations

from typing import Any

import structlog

from context_service.config.settings import get_settings

logger = structlog.get_logger(__name__)

_ORG_METADATA = {"source": "self-serve-signup"}


def _build_workos_client() -> Any:
    """Construct a WorkOS client from settings (matches existing auth helpers)."""
    import workos  # lazy: optional `auth` group

    settings = get_settings()
    api_key = settings.workos_api_key.get_secret_value() if settings.workos_api_key else None
    if api_key is None:
        raise ValueError("WORKOS_API_KEY must be configured for org provisioning")
    if not settings.workos_client_id:
        raise ValueError("WORKOS_CLIENT_ID must be configured for org provisioning")
    return workos.WorkOSClient(api_key=api_key, client_id=settings.workos_client_id)


def _ensure_membership(client: Any, *, workos_user_id: str, organization_id: str) -> None:
    """Create the user's membership, tolerating an already-a-member conflict.

    Idempotent: a duplicate membership returns ConflictError (or
    UnprocessableEntityError on some WorkOS versions); both are treated as a
    no-op so re-running provisioning is safe and partial failures self-repair.
    """
    import workos

    try:
        client.user_management.create_organization_membership(
            user_id=workos_user_id,
            organization_id=organization_id,
        )
    except (workos.ConflictError, workos.UnprocessableEntityError):
        logger.info(
            "org_provisioning.membership_exists",
            org_id=organization_id,
            workos_user_id=workos_user_id,
        )


def ensure_personal_org(workos_user_id: str, workspace_name: str) -> str:
    """Return the id of the user's personal org, creating it if absent.

    Idempotent and concurrency-safe, keyed on ``external_id == workos_user_id``:
      - If an org with that external id already exists, reuse it and re-ensure
        the membership (repairs a prior org-created-but-membership-failed state).
      - Otherwise create the org. If a racing request created it first, WorkOS
        rejects the duplicate external id with ConflictError; re-fetch and reuse.
      - Always (re)ensure the membership.
    """
    import workos

    client = _build_workos_client()

    try:
        existing = client.organizations.get_organization_by_external_id(workos_user_id)
        org_id = str(existing.id)
        _ensure_membership(client, workos_user_id=workos_user_id, organization_id=org_id)
        logger.info("org_provisioning.reuse_existing", org_id=org_id, workos_user_id=workos_user_id)
        return org_id
    except workos.NotFoundError:
        pass

    try:
        org = client.organizations.create_organization(
            name=workspace_name,
            external_id=workos_user_id,
            metadata=_ORG_METADATA,
        )
        org_id = str(org.id)
        logger.info("org_provisioning.created", org_id=org_id, workos_user_id=workos_user_id)
    except workos.ConflictError:
        # Lost a race: another request already created the org for this external id.
        existing = client.organizations.get_organization_by_external_id(workos_user_id)
        org_id = str(existing.id)
        logger.info(
            "org_provisioning.create_race_resolved", org_id=org_id, workos_user_id=workos_user_id
        )

    _ensure_membership(client, workos_user_id=workos_user_id, organization_id=org_id)
    return org_id


def resolve_workspace_name(name: str | None, email: str) -> str:
    """Derive a workspace name from the user's display name or email.

    Prefers the full name; falls back to the local-part of the email when no
    name is available (common for magic-link signups).
    """
    base = (name or "").strip() or email.split("@", 1)[0].strip()
    if not base:
        # No usable name and no email local-part (e.g. "@x.com"); neutral default.
        return "New workspace"
    return f"{base}'s workspace"
