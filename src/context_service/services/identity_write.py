"""Fire-and-forget helpers for multi-agent identity write operations.

Both functions are designed to be called as background tasks after a successful
node write. Failures are swallowed with a warning log — they must not interrupt
the primary write path.
"""

from __future__ import annotations

import asyncio

import structlog

from context_service.auth.identity import IdentityContext

logger = structlog.get_logger(__name__)


async def upsert_agent(identity: IdentityContext) -> None:
    """Upsert Agent row for the current writer. Creates on first write, updates last_seen after."""
    try:
        from sqlalchemy import text
        from sqlalchemy.dialects.postgresql import insert

        from context_service.db.postgres import get_session
        from context_service.models.postgres.agent import Agent

        async with get_session() as session:
            stmt = (
                insert(Agent)
                .values(
                    id=identity.agent_id,
                    silo_id=identity.tenant_id,
                )
                .on_conflict_do_update(
                    index_elements=["id", "silo_id"],
                    set_={"last_seen": text("now()")},
                )
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as exc:
        logger.warning("upsert_agent_failed", agent_id=identity.agent_id, error=str(exc))


async def log_belief_event(
    identity: IdentityContext,
    action: str,
    target_node_id: str,
) -> None:
    """Insert a BeliefEvent record for the given node write action."""
    try:
        import uuid

        from context_service.db.postgres import get_session
        from context_service.models.postgres.belief_event import BeliefEvent

        event_id = str(uuid.uuid4())
        async with get_session() as session:
            session.add(
                BeliefEvent(
                    id=event_id,
                    silo_id=identity.tenant_id,
                    agent_id=identity.agent_id,
                    action=action,
                    target_node_id=target_node_id,
                )
            )
            await session.commit()
    except Exception as exc:
        logger.warning(
            "log_belief_event_failed",
            agent_id=identity.agent_id,
            action=action,
            target_node_id=target_node_id,
            error=str(exc),
        )


def fire_and_forget_identity_writes(
    identity: IdentityContext,
    action: str,
    target_node_id: str,
) -> None:
    """Schedule agent upsert + event log as background asyncio tasks."""
    asyncio.create_task(upsert_agent(identity))
    asyncio.create_task(log_belief_event(identity, action, target_node_id))
