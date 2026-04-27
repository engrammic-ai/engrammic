"""Auth context resolved per request."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthContext:
    org_id: str
    user_id: str
    email: str | None
    is_dev: bool
