"""API key management service."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from context_service.models.postgres.api_key import APIKey


class APIKeyService:
    """Service for creating and verifying API keys."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_key(
        self,
        user_id: UUID,
        name: str,
        scopes: str = "read write",
        expires_at: datetime | None = None,
    ) -> tuple[str, APIKey]:
        """Create a new API key.

        Returns (plaintext_key, api_key_record). The plaintext is only
        available at creation time - store it securely.
        """
        # Generate key: eng_ prefix + 32 random hex chars
        raw = secrets.token_hex(16)
        plaintext = f"eng_{raw}"
        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()

        api_key = APIKey(
            user_id=user_id,
            key_hash=key_hash,
            name=name,
            scopes=scopes,
            expires_at=expires_at,
        )
        self._session.add(api_key)
        await self._session.flush()
        return plaintext, api_key

    async def verify_key(self, plaintext: str) -> APIKey | None:
        """Verify an API key and return the record if valid.

        Returns None if key is invalid, revoked, or expired.
        """
        if not plaintext.startswith("eng_"):
            return None

        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        now = datetime.now(UTC)

        stmt = select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.revoked_at.is_(None),
        )
        result = await self._session.execute(stmt)
        api_key = result.scalar_one_or_none()

        if api_key is None:
            return None

        # Check expiry
        if api_key.expires_at and api_key.expires_at < now:
            return None

        # Update last_used_at
        await self._session.execute(
            update(APIKey).where(APIKey.id == api_key.id).values(last_used_at=now)
        )

        return api_key

    async def revoke_key(self, key_id: UUID) -> bool:
        """Revoke an API key. Returns True if key existed."""
        result = await self._session.execute(
            update(APIKey)
            .where(APIKey.id == key_id, APIKey.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        rowcount: int = result.rowcount  # type: ignore[attr-defined]
        return rowcount > 0

    async def list_keys(self, user_id: UUID) -> list[APIKey]:
        """List all non-revoked keys for a user."""
        stmt = select(APIKey).where(
            APIKey.user_id == user_id,
            APIKey.revoked_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
