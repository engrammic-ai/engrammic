"""Agent identity model for multi-agent coherence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base


class Agent(Base):
    """Registered agent within a silo."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    silo_id: Mapped[str] = mapped_column(String, primary_key=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    trust_score: Mapped[float] = mapped_column(Float, server_default=text("0.5"))
    beliefs_validated: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    beliefs_contradicted: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __init__(
        self,
        id: str,
        silo_id: str,
        role: str | None = None,
        parent_agent_id: str | None = None,
        trust_score: float = 0.5,
        beliefs_validated: int = 0,
        beliefs_contradicted: int = 0,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.id = id
        self.silo_id = silo_id
        self.role = role
        self.parent_agent_id = parent_agent_id
        self.trust_score = trust_score
        self.beliefs_validated = beliefs_validated
        self.beliefs_contradicted = beliefs_contradicted
