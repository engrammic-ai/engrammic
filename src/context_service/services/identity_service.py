"""Identity service: auto-create agents and log belief events."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from context_service.auth.identity import IdentityContext

logger = structlog.get_logger(__name__)


async def ensure_agent(ctx: IdentityContext) -> None:
    """Create Agent row on first write if it doesn't exist yet.

    Uses INSERT ... ON CONFLICT DO NOTHING so concurrent first-writes are safe.
    Also bumps last_seen on every call.
    """
    try:
        from sqlalchemy.dialects.postgresql import insert

        from context_service.db.postgres import get_session
        from context_service.models.postgres.agent import Agent

        async with get_session() as session:
            stmt = (
                insert(Agent)
                .values(
                    id=ctx.agent_id,
                    silo_id=ctx.tenant_id,
                    trust_score=0.5,
                    beliefs_validated=0,
                    beliefs_contradicted=0,
                    first_seen=datetime.now(UTC),
                    last_seen=datetime.now(UTC),
                )
                .on_conflict_do_update(
                    index_elements=["silo_id", "id"],
                    set_={"last_seen": datetime.now(UTC)},
                )
            )
            await session.execute(stmt)
    except Exception as exc:
        logger.warning(
            "ensure_agent_failed",
            agent_id=ctx.agent_id,
            silo_id=ctx.tenant_id,
            error=str(exc),
        )


async def log_belief_event(
    ctx: IdentityContext,
    action: str,
    target_node_id: str,
) -> None:
    """Insert a row into belief_events for auditing.

    Best-effort: logs warning on failure, does not raise.

    Args:
        ctx: Resolved identity for the current request.
        action: "asserted", "retracted", or "superseded".
        target_node_id: ID of the node the action applies to.
    """
    try:
        from context_service.db.postgres import get_session
        from context_service.models.postgres.belief_event import BeliefEvent

        event = BeliefEvent(
            id=str(uuid.uuid4()),
            silo_id=ctx.tenant_id,
            agent_id=ctx.agent_id,
            action=action,
            target_node_id=target_node_id,
        )
        async with get_session() as session:
            session.add(event)
    except Exception as exc:
        logger.warning(
            "log_belief_event_failed",
            action=action,
            agent_id=ctx.agent_id,
            silo_id=ctx.tenant_id,
            target_node_id=target_node_id,
            error=str(exc),
        )


def fire_and_forget_identity_writes(
    ctx: IdentityContext,
    action: str,
    target_node_id: str,
) -> None:
    """Schedule agent upsert + event log as background asyncio tasks.

    Neither task blocks the write response. Both swallow errors internally.
    """
    asyncio.create_task(ensure_agent(ctx))
    asyncio.create_task(log_belief_event(ctx, action, target_node_id))
