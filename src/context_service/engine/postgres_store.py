"""Repository layer for Postgres hybrid storage operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult

from context_service.db.postgres import get_session
from context_service.models.postgres.reasoning import (
    OrphanedChains,
    ReasoningChainSteps,
)


class PostgresStore:
    """Async repository for Postgres-backed hybrid storage."""

    async def upsert_chain_steps(
        self, chain_id: UUID, silo_id: UUID, steps: list[dict[str, Any]]
    ) -> None:
        """Upsert reasoning chain steps with ON CONFLICT UPDATE."""
        async with get_session() as session:
            stmt = insert(ReasoningChainSteps).values(
                chain_id=chain_id,
                silo_id=silo_id,
                steps=steps,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["chain_id"],
                set_={"steps": stmt.excluded.steps},
            )
            await session.execute(stmt)

    async def get_chain_steps(self, chain_id: UUID) -> list[dict[str, Any]] | None:
        """Fetch steps by chain_id. Returns None if not found."""
        async with get_session() as session:
            stmt = select(ReasoningChainSteps.steps).where(
                ReasoningChainSteps.chain_id == chain_id
            )
            result = await session.execute(stmt)
            row: list[dict[str, Any]] | None = result.scalar_one_or_none()
            return row

    async def delete_chain_steps(self, chain_id: UUID) -> bool:
        """Delete chain steps. Returns True if row existed."""
        async with get_session() as session:
            stmt = delete(ReasoningChainSteps).where(
                ReasoningChainSteps.chain_id == chain_id
            )
            result: CursorResult[Any] = await session.execute(stmt)  # type: ignore[assignment]
            return result.rowcount > 0

    async def add_orphaned_chain(
        self, chain_id: UUID, silo_id: UUID, error: str
    ) -> None:
        """Add chain to dead-letter table."""
        async with get_session() as session:
            stmt = insert(OrphanedChains).values(
                chain_id=chain_id,
                silo_id=silo_id,
                last_error=error,
                retry_count=1,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["chain_id"],
                set_={
                    "retry_count": OrphanedChains.retry_count + 1,
                    "last_error": error,
                },
            )
            await session.execute(stmt)
