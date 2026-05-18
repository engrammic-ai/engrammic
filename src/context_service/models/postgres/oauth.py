"""OAuth SQLAlchemy models for MCP OAuth flow."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from context_service.db.postgres import Base

if TYPE_CHECKING:
    from context_service.models.postgres.user import User


class OAuthAuthorizationRequest(Base):
    """PKCE state storage for OAuth authorization requests."""

    __tablename__ = "oauth_authorization_requests"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    state: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    code_challenge_method: Mapped[str] = mapped_column(
        String(10), server_default=text("'S256'"), nullable=False
    )
    redirect_uri: Mapped[str] = mapped_column(Text(), nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope: Mapped[str | None] = mapped_column(Text(), nullable=True)
    workos_state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    authorization_codes: Mapped[list[OAuthAuthorizationCode]] = relationship(
        back_populates="authorization_request"
    )


class OAuthAuthorizationCode(Base):
    """Single-use authorization codes."""

    __tablename__ = "oauth_authorization_codes"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    code: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    authorization_request_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("oauth_authorization_requests.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="authorization_codes")
    authorization_request: Mapped[OAuthAuthorizationRequest | None] = relationship(
        back_populates="authorization_codes"
    )


class OAuthToken(Base):
    """Access and refresh tokens stored as hashes."""

    __tablename__ = "oauth_tokens"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    access_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    refresh_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    scope: Mapped[str | None] = mapped_column(Text(), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="oauth_tokens")
