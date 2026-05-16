"""Pydantic schemas for the skills registry."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from context_service.models.postgres.skill import _NAME_PATTERN, MAX_BODY_SIZE

RESERVED_NAMESPACES: tuple[str, ...] = ("engrammic:", "coding:", "b2b-ops:")


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
        for reserved in RESERVED_NAMESPACES:
            if v.startswith(reserved):
                raise ValueError(f"The '{reserved}' namespace is reserved")
        return v


class SkillUpdate(BaseModel):
    """Pydantic schema for updating a skill."""

    description: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=MAX_BODY_SIZE)
    allowed_tools: list[str] | None = None


class SkillResponse(BaseModel):
    """Pydantic schema for skill API responses."""

    id: UUID
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
