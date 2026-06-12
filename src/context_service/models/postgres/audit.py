"""Event and audit event models for observability and compliance."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base

# list[str] stored as JSONB array
_StrList = list[str]
# dict stored as JSONB object
_JsonDict = dict[str, Any]


class Events(Base):
    """Agent and pipeline events with optional TTL for ephemeral entries."""

    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    silo_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("silo_config.silo_id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_chain_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    step_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_events_silo_type_created", "silo_id", "event_type", "created_at"),
        Index(
            "ix_events_expires_at_partial",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
    )

    def __init__(
        self,
        silo_id: UUID | str,
        event_type: str,
        content: str,
        source_chain_id: UUID | str | None = None,
        agent_id: str | None = None,
        step_count: int | None = None,
        outcome: str | None = None,
        expires_at: datetime | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.id = uuid4()
        self.silo_id = silo_id
        self.event_type = event_type
        self.content = content
        self.source_chain_id = source_chain_id
        self.agent_id = agent_id
        self.step_count = step_count
        self.outcome = outcome
        self.expires_at = expires_at


class AuditEvents(Base):
    """Immutable audit log of actor-driven changes for compliance."""

    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    silo_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("silo_config.silo_id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_audit_events_silo_created", "silo_id", "created_at"),
        Index("ix_audit_events_actor_created", "actor_id", "created_at"),
    )

    def __init__(
        self,
        silo_id: UUID | str,
        event_type: str,
        actor_id: str,
        actor_type: str,
        payload: dict[str, Any] | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.id = uuid4()
        self.silo_id = silo_id
        self.event_type = event_type
        self.actor_id = actor_id
        self.actor_type = actor_type
        self.payload = payload if payload is not None else {}


class ErasureAuditLog(Base):
    """Immutable GDPR erasure audit log recording every right-to-erasure request."""

    __tablename__ = "erasure_audit_log"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    silo_id: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    # 'user', 'admin', 'system'
    requester_type: Mapped[str] = mapped_column(Text, nullable=False)
    requester_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # array of erased node IDs stored as JSONB
    node_ids: Mapped[_StrList] = mapped_column(JSONB, nullable=False)
    cascade_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    # 'completed', 'partial', 'failed'
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_details: Mapped[_JsonDict | None] = mapped_column(JSONB, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_erasure_audit_log_silo_id", "silo_id"),
        Index("ix_erasure_audit_log_request_id", "request_id"),
        Index("ix_erasure_audit_log_requested_at", "requested_at"),
    )

    def __init__(
        self,
        silo_id: str,
        request_id: str,
        requester_type: str,
        node_ids: list[str],
        status: str,
        requested_at: datetime,
        requester_id: str | None = None,
        cascade_count: int = 0,
        error_details: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.id = uuid4()
        self.silo_id = silo_id
        self.request_id = request_id
        self.requester_type = requester_type
        self.requester_id = requester_id
        self.node_ids = node_ids
        self.cascade_count = cascade_count
        self.status = status
        self.error_details = error_details
        self.requested_at = requested_at
        self.completed_at = completed_at
