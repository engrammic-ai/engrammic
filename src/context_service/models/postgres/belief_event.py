"""BeliefEvent model — audit trail for agent write actions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base


class BeliefEvent(Base):
    """Record of a single agent belief action (assert, retract, challenge, supersede)."""

    __tablename__ = "belief_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    silo_id: Mapped[str] = mapped_column(String, nullable=False)
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_node_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("idx_events_silo_agent", "silo_id", "agent_id", "created_at"),
        Index("idx_events_node", "target_node_id", "created_at"),
    )

    def __init__(
        self,
        id: str,
        silo_id: str,
        agent_id: str,
        action: str,
        target_node_id: str,
    ) -> None:
        super().__init__()
        self.id = id
        self.silo_id = silo_id
        self.agent_id = agent_id
        self.action = action
        self.target_node_id = target_node_id
