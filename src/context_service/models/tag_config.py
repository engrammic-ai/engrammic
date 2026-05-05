"""SQLAlchemy model for per-silo tag configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import String, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base

DEFAULT_SETTINGS: dict[str, Any] = {
    "min_tags": 2,
    "max_tags": 5,
    "cosine_threshold": 0.4,
    "promotion_threshold": 3,
    "demotion_days": 30,
    "synonym_threshold": 0.85,
}

DEFAULT_CONSTRAINTS: dict[str, Any] = {
    "hierarchy": {},
    "layer_hints": {},
    "mutual_exclusion": [],
}


class SiloTagConfig(Base):
    """Per-silo tag configuration stored in Postgres."""

    __tablename__ = "silo_tag_configs"

    silo_id: Mapped[UUID] = mapped_column(primary_key=True)
    core_tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, server_default="{}")
    dynamic_tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default="{}"
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=lambda: DEFAULT_SETTINGS.copy())
    constraints: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=lambda: DEFAULT_CONSTRAINTS.copy()
    )
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(onupdate=func.now(), default=None)

    def all_tags(self) -> list[str]:
        """Return combined core + dynamic tags."""
        return list(set((self.core_tags or []) + (self.dynamic_tags or [])))
