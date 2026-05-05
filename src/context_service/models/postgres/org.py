"""Organization and silo configuration models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from context_service.db.postgres import Base


class OrgPreferences(Base):
    """Organization-level preferences and settings."""

    __tablename__ = "org_preferences"

    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    default_llm: Mapped[str] = mapped_column(String(64), server_default="claude-haiku-4-5-20251001")
    embedding_model: Mapped[str] = mapped_column(String(64), server_default="jina-embeddings-v3")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    silos: Mapped[list[SiloConfig]] = relationship(back_populates="org")

    def __init__(
        self,
        org_id: UUID | str,
        default_llm: str = "claude-haiku-4-5-20251001",
        embedding_model: str = "jina-embeddings-v3",
        settings: dict[str, Any] | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.org_id = org_id  # type: ignore[assignment]
        self.default_llm = default_llm
        self.embedding_model = embedding_model
        self.settings = settings if settings is not None else {}


class SiloConfig(Base):
    """Per-silo configuration and quotas."""

    __tablename__ = "silo_config"

    silo_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("org_preferences.org_id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quotas: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    feature_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    org: Mapped[OrgPreferences] = relationship(back_populates="silos")

    def __init__(
        self,
        silo_id: UUID | str,
        org_id: UUID | str,
        name: str,
        quotas: dict[str, Any] | None = None,
        feature_flags: dict[str, Any] | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.silo_id = silo_id  # type: ignore[assignment]
        self.org_id = org_id  # type: ignore[assignment]
        self.name = name
        self.quotas = quotas if quotas is not None else {}
        self.feature_flags = feature_flags if feature_flags is not None else {}
