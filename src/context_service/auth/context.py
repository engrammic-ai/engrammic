"""Auth context resolved per request."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuthContext:
    org_id: str
    user_id: str
    email: str | None
    is_dev: bool
    agent_id: str | None = None
    session_id: str | None = None
    db_user_id: UUID | None = None
