"""User model for WorkOS-authenticated users."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from context_service.db.postgres import Base

if TYPE_CHECKING:
    from context_service.models.postgres.oauth import OAuthAuthorizationCode, OAuthToken


class User(Base):
    """User authenticated via WorkOS."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workos_user_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    org_id: Mapped[str] = mapped_column(String(255), index=True)
    silo_id: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    oauth_tokens: Mapped[list[OAuthToken]] = relationship(back_populates="user")
    authorization_codes: Mapped[list[OAuthAuthorizationCode]] = relationship(back_populates="user")

    def __init__(
        self,
        workos_user_id: str,
        org_id: str,
        silo_id: str,
        email: str,
        name: str | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.id = uuid4()
        self.workos_user_id = workos_user_id
        self.org_id = org_id
        self.silo_id = silo_id
        self.email = email
        self.name = name
