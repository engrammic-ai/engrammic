"""User management service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from context_service.models.postgres.user import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class UserService:
    """Service for managing WorkOS-authenticated users."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_user(
        self,
        workos_user_id: str,
        org_id: str,
        silo_id: str,
        email: str,
        name: str | None = None,
    ) -> User:
        """Create user if not exists, always update last_active_at.

        On existing user: updates last_active_at and name/email if changed.
        On new user: creates with all fields.

        Note: passing name=None will set the DB column to NULL. This is
        intentional; callers should omit name only when no name is available.
        """
        now = datetime.now(UTC)

        stmt = (
            insert(User)
            .values(
                workos_user_id=workos_user_id,
                org_id=org_id,
                silo_id=silo_id,
                email=email,
                name=name,
                last_active_at=now,
            )
            .on_conflict_do_update(
                index_elements=["workos_user_id"],
                set_={
                    "last_active_at": now,
                    "email": email,
                    "name": name,
                    "org_id": org_id,
                    "silo_id": silo_id,
                },
            )
            .returning(User)
        )

        result = await self._session.execute(stmt)
        user: User = result.scalars().one()

        logger.info(
            "user.upserted",
            workos_user_id=workos_user_id,
            org_id=org_id,
            silo_id=silo_id,
        )
        return user

    async def get_user_by_workos_id(self, workos_user_id: str) -> User | None:
        """Look up a user by their WorkOS user ID."""
        stmt = select(User).where(User.workos_user_id == workos_user_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()
