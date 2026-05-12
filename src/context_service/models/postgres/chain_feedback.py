"""Chain delivery and feedback tracking models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Float, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base


class ChainDelivery(Base):
    """Tracks when a reasoning chain is returned to an agent."""

    __tablename__ = "chain_delivery"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    chain_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_chain_delivery_session_id", "session_id"),
        Index("ix_chain_delivery_delivered_at", "delivered_at"),
    )


class ChainFeedback(Base):
    """Stores usefulness signals for delivered chains."""

    __tablename__ = "chain_feedback"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    chain_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    signal: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_chain_feedback_chain_id", "chain_id"),)
