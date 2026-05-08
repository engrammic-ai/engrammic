"""Skill model for the skills registry."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base

MAX_BODY_SIZE = 64 * 1024  # 64KB

_NAME_PATTERN = re.compile(r"^[a-z0-9-]+:[a-z0-9-]+$")


class Skill(Base):
    """SQLAlchemy model for user-created skills."""

    __tablename__ = "skills"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_tools: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    silo_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SkillCreate(BaseModel):
    """Pydantic schema for creating a skill."""

    name: str = Field(max_length=255)
    description: str = Field(max_length=500)
    body: str = Field(max_length=MAX_BODY_SIZE)
    allowed_tools: list[str] | None = None

    @field_validator("name")
    @classmethod
    def validate_name_format(cls, v: str) -> str:
        if not _NAME_PATTERN.match(v):
            raise ValueError("Name must be lowercase namespace:name format (e.g., 'myorg:mytool')")
        if v.startswith("engrammic:"):
            raise ValueError("The 'engrammic:' namespace is reserved")
        return v


class SkillUpdate(BaseModel):
    """Pydantic schema for updating a skill."""

    description: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=MAX_BODY_SIZE)
    allowed_tools: list[str] | None = None


class SkillResponse(BaseModel):
    """Pydantic schema for skill API responses."""

    id: UUID | None = None
    name: str
    description: str
    body: str
    allowed_tools: list[str] | None
    source: Literal["builtin", "user"]
    version: str
    silo_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
