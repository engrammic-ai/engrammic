"""Tool usage tracking models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base


class ToolUsage(Base):
    """Record of a single MCP tool invocation by a user."""

    __tablename__ = "tool_usage"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    silo_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    def __init__(
        self,
        user_id: UUID | str,
        silo_id: str,
        tool_name: str,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.id = uuid4()
        self.user_id = user_id  # type: ignore[assignment]
        self.silo_id = silo_id
        self.tool_name = tool_name
        self.called_at = datetime.now(UTC)


@dataclass
class ToolUsageSummary:
    """Aggregated tool usage statistics for a user."""

    tool_name: str
    count: int
    last_used: datetime
