"""Reasoning chain storage models for hybrid Postgres backend."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, DateTime, Float, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base


class ReasoningChainSteps(Base):
    """Stores reasoning chain step sequences per silo."""

    __tablename__ = "reasoning_chain_steps"

    chain_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    silo_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("silo_config.silo_id"),
        nullable=False,
    )
    steps: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    # TX7 TRACE fields
    conclusion: Mapped[str | None] = mapped_column(String, nullable=True)
    conclusion_embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_hypothesis_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    traced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_reasoning_chain_steps_silo_id", "silo_id"),)


class OrphanedChains(Base):
    """Dead-letter table for reasoning chains that failed processing."""

    __tablename__ = "orphaned_chains"

    chain_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    silo_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    failed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    retry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
