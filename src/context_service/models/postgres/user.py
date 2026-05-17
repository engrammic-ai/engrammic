"""User model for WorkOS-authenticated demo users."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base


class User(Base):
    """Demo user authenticated via WorkOS magic link."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workos_user_id: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    org_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    silo_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

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
        self.created_at = datetime.now(UTC)
        self.last_active_at = datetime.now(UTC)
