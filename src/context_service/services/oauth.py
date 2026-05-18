"""OAuth service layer for MCP OAuth flow."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from sqlalchemy import select

from context_service.config.settings import get_settings
from context_service.models.postgres.oauth import (
    OAuthAuthorizationCode,
    OAuthAuthorizationRequest,
    OAuthToken,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class OAuthService:
    """Service for managing MCP OAuth PKCE flow and token lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._settings = get_settings().oauth

    # ------------------------------------------------------------------ #
    # Public methods                                                       #
    # ------------------------------------------------------------------ #

    async def create_authorization_request(
        self,
        state: str,
        code_challenge: str,
        redirect_uri: str,
        client_id: str | None = None,
        scope: str | None = None,
    ) -> OAuthAuthorizationRequest:
        """Store a PKCE authorization request keyed by state."""
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._settings.authorization_code_ttl_seconds)

        auth_request = OAuthAuthorizationRequest(
            state=state,
            code_challenge=code_challenge,
            code_challenge_method="S256",
            redirect_uri=redirect_uri,
            client_id=client_id,
            scope=scope,
            expires_at=expires_at,
        )
        self._session.add(auth_request)
        await self._session.flush()

        logger.info(
            "oauth.authorization_request.created",
            state=state,
            client_id=client_id,
        )
        return auth_request

    async def get_authorization_request(self, state: str) -> OAuthAuthorizationRequest | None:
        """Retrieve an authorization request by state, checking expiration."""
        stmt = select(OAuthAuthorizationRequest).where(OAuthAuthorizationRequest.state == state)
        result = await self._session.execute(stmt)
        auth_request = result.scalar_one_or_none()

        if auth_request is None:
            return None

        now = datetime.now(UTC)
        if auth_request.expires_at <= now:
            logger.info("oauth.authorization_request.expired", state=state)
            return None

        return auth_request

    async def create_authorization_code(
        self,
        user_id: UUID,
        request_id: UUID,
    ) -> tuple[OAuthAuthorizationCode, str]:
        """Create a single-use authorization code tied to a PKCE request.

        Returns a (OAuthAuthorizationCode, raw_code) tuple.  The raw_code must
        be returned to the caller and included in the redirect; the database
        record stores only its SHA256 hash so a leaked DB row cannot be
        replayed.
        """
        raw_code = self._generate_token()
        code_hash = self._hash_token(raw_code)
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._settings.authorization_code_ttl_seconds)

        auth_code = OAuthAuthorizationCode(
            code=code_hash,
            user_id=user_id,
            authorization_request_id=request_id,
            expires_at=expires_at,
        )
        self._session.add(auth_code)
        await self._session.flush()

        logger.info(
            "oauth.authorization_code.created",
            user_id=str(user_id),
            request_id=str(request_id),
        )
        return auth_code, raw_code

    async def exchange_code_for_tokens(
        self,
        code: str,
        code_verifier: str,
    ) -> dict[str, Any] | None:
        """Validate PKCE and exchange an authorization code for tokens.

        Returns a token response dict or None if validation fails.
        """
        code_hash = self._hash_token(code)
        stmt = select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == code_hash)
        result = await self._session.execute(stmt)
        auth_code = result.scalar_one_or_none()

        if auth_code is None:
            logger.info("oauth.code_exchange.code_not_found")
            return None

        now = datetime.now(UTC)

        if auth_code.used_at is not None:
            logger.warning("oauth.code_exchange.code_already_used", code_id=str(auth_code.id))
            return None

        if auth_code.expires_at <= now:
            logger.info("oauth.code_exchange.code_expired", code_id=str(auth_code.id))
            return None

        if auth_code.authorization_request_id is None:
            logger.warning(
                "oauth.code_exchange.missing_authorization_request",
                code_id=str(auth_code.id),
            )
            return None

        auth_request = await self._session.get(
            OAuthAuthorizationRequest, auth_code.authorization_request_id
        )
        if auth_request is None:
            logger.warning(
                "oauth.code_exchange.authorization_request_not_found",
                request_id=str(auth_code.authorization_request_id),
            )
            return None

        if not self._verify_pkce(code_verifier, auth_request.code_challenge):
            logger.warning(
                "oauth.code_exchange.pkce_verification_failed",
                code_id=str(auth_code.id),
            )
            return None

        # Mark code as used atomically before issuing tokens
        auth_code.used_at = now

        access_token = self._generate_token()
        refresh_token = self._generate_token()

        access_token_expires_at = now + timedelta(seconds=self._settings.access_token_ttl_seconds)
        refresh_token_expires_at = now + timedelta(days=self._settings.refresh_token_ttl_days)

        oauth_token = OAuthToken(
            user_id=auth_code.user_id,
            access_token_hash=self._hash_token(access_token),
            refresh_token_hash=self._hash_token(refresh_token),
            scope=auth_request.scope,
            client_id=auth_request.client_id,
            access_token_expires_at=access_token_expires_at,
            refresh_token_expires_at=refresh_token_expires_at,
        )
        self._session.add(oauth_token)
        await self._session.flush()

        logger.info(
            "oauth.code_exchange.success",
            user_id=str(auth_code.user_id),
            token_id=str(oauth_token.id),
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self._settings.access_token_ttl_seconds,
            "token_type": "Bearer",
        }

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any] | None:
        """Issue a new access token from a valid refresh token.

        Returns a token response dict or None if the refresh token is invalid.
        """
        refresh_token_hash = self._hash_token(refresh_token)
        stmt = select(OAuthToken).where(OAuthToken.refresh_token_hash == refresh_token_hash)
        result = await self._session.execute(stmt)
        token = result.scalar_one_or_none()

        if token is None:
            logger.info("oauth.refresh.token_not_found")
            return None

        now = datetime.now(UTC)

        if token.revoked_at is not None:
            logger.warning("oauth.refresh.token_revoked", token_id=str(token.id))
            return None

        if token.refresh_token_expires_at is not None and token.refresh_token_expires_at <= now:
            logger.info("oauth.refresh.token_expired", token_id=str(token.id))
            return None

        new_access_token = self._generate_token()
        access_token_expires_at = now + timedelta(seconds=self._settings.access_token_ttl_seconds)

        token.access_token_hash = self._hash_token(new_access_token)
        token.access_token_expires_at = access_token_expires_at
        await self._session.flush()

        logger.info(
            "oauth.refresh.success",
            user_id=str(token.user_id),
            token_id=str(token.id),
        )

        return {
            "access_token": new_access_token,
            "expires_in": self._settings.access_token_ttl_seconds,
            "token_type": "Bearer",
        }

    async def validate_access_token(self, access_token: str) -> OAuthToken | None:
        """Check token validity and return the OAuthToken record or None."""
        access_token_hash = self._hash_token(access_token)
        stmt = select(OAuthToken).where(OAuthToken.access_token_hash == access_token_hash)
        result = await self._session.execute(stmt)
        token = result.scalar_one_or_none()

        if token is None:
            return None

        now = datetime.now(UTC)

        if token.revoked_at is not None:
            return None

        if token.access_token_expires_at <= now:
            return None

        return token

    async def revoke_token(self, token: str) -> bool:
        """Revoke an access or refresh token.

        Checks both access_token_hash and refresh_token_hash.
        Returns True if a token was revoked, False if not found.
        """
        token_hash = self._hash_token(token)
        now = datetime.now(UTC)

        stmt = select(OAuthToken).where(
            (OAuthToken.access_token_hash == token_hash)
            | (OAuthToken.refresh_token_hash == token_hash)
        )
        result = await self._session.execute(stmt)
        oauth_token = result.scalar_one_or_none()

        if oauth_token is None:
            logger.info("oauth.revoke.token_not_found")
            return False

        if oauth_token.revoked_at is not None:
            logger.info("oauth.revoke.already_revoked", token_id=str(oauth_token.id))
            return True

        oauth_token.revoked_at = now
        await self._session.flush()

        logger.info(
            "oauth.revoke.success",
            user_id=str(oauth_token.user_id),
            token_id=str(oauth_token.id),
        )
        return True

    async def list_user_tokens(self, user_id: UUID) -> list[OAuthToken]:
        """List all active (non-revoked) tokens for a user."""
        now = datetime.now(UTC)
        stmt = (
            select(OAuthToken)
            .where(
                OAuthToken.user_id == user_id,
                OAuthToken.revoked_at.is_(None),
                OAuthToken.access_token_expires_at > now,
            )
            .order_by(OAuthToken.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _hash_token(token: str) -> str:
        """SHA256 hash a token for storage."""
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
        """S256 PKCE verification: BASE64URL(SHA256(code_verifier)) == code_challenge."""
        verifier_hash = hashlib.sha256(code_verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(verifier_hash).rstrip(b"=").decode()
        return secrets.compare_digest(expected, code_challenge)

    @staticmethod
    def _generate_token() -> str:
        """Generate a cryptographically secure URL-safe token (256 bits)."""
        return secrets.token_urlsafe(32)
