"""Tool usage tracking models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base


class ToolUsage(Base):
    """Record of a single MCP tool invocation by a user."""

    __tablename__ = "tool_usage"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    silo_id: Mapped[str] = mapped_column(String(255), index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    called_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def __init__(
        self,
        user_id: UUID | str,
        silo_id: str,
        tool_name: str,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.id = uuid4()
        self.user_id = user_id if isinstance(user_id, UUID) else UUID(user_id)
        self.silo_id = silo_id
        self.tool_name = tool_name


@dataclass
class ToolUsageSummary:
    """Aggregated tool usage statistics for a user."""

    tool_name: str
    count: int
    last_used: datetime
