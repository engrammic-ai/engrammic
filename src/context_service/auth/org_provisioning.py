"""Self-serve organization provisioning.

When a user authenticates with no organization (typical of self-serve
signup via the hosted AuthKit UI), provision a personal
``"{name}'s workspace"`` org so every identity resolves to a real silo.

WorkOS calls use the lazily-imported ``workos`` SDK (the ``auth`` group), so
this module imports cleanly when that group is not installed.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


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
