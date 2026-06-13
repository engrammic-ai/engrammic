"""Repository layer for Postgres hybrid storage operations."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from context_service.db.postgres import get_session
from context_service.models.postgres.org import OrgPreferences, SiloConfig
from context_service.models.postgres.reasoning import (
    OrphanedChains,
    ReasoningChainSteps,
)
from context_service.telemetry.metrics import record_db_query


class PostgresStore:
    """Async repository for Postgres-backed hybrid storage."""

    async def ensure_silo_config(self, silo_id: UUID, org_id: UUID, name: str = "default") -> None:
        """Ensure OrgPreferences and SiloConfig exist for the given silo.

        Uses INSERT ... ON CONFLICT DO NOTHING for idempotent creation.
        """
        start = time.perf_counter()
        try:
            async with get_session() as session:
                org_stmt = insert(OrgPreferences).values(org_id=org_id)
                org_stmt = org_stmt.on_conflict_do_nothing(index_elements=["org_id"])
                await session.execute(org_stmt)

                silo_stmt = insert(SiloConfig).values(
                    silo_id=silo_id,
                    org_id=org_id,
                    name=name,
                )
                silo_stmt = silo_stmt.on_conflict_do_nothing(index_elements=["silo_id"])
                await session.execute(silo_stmt)
        finally:
            record_db_query("postgres.ensure_silo_config", (time.perf_counter() - start) * 1000)

    async def upsert_chain_steps(
        self, chain_id: UUID, silo_id: UUID, steps: list[dict[str, Any]], org_id: UUID | None = None
    ) -> None:
        """Upsert reasoning chain steps with ON CONFLICT UPDATE.

        If org_id is provided, ensures the silo config exists first.
        """
        if org_id is not None:
            await self.ensure_silo_config(silo_id, org_id)

        start = time.perf_counter()
        try:
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
                result = await session.execute(stmt)
                if result.rowcount != 1:  # type: ignore[attr-defined]
                    raise RuntimeError(
                        f"upsert_chain_steps expected rowcount=1, got {result.rowcount} "  # type: ignore[attr-defined]
                        f"for chain_id={chain_id}"
                    )
        finally:
            record_db_query("postgres.upsert_chain_steps", (time.perf_counter() - start) * 1000)

    async def get_chain_steps(self, chain_id: UUID) -> list[dict[str, Any]] | None:
        """Fetch steps by chain_id. Returns None if not found."""
        start = time.perf_counter()
        try:
            async with get_session() as session:
                stmt = select(ReasoningChainSteps.steps).where(
                    ReasoningChainSteps.chain_id == chain_id
                )
                result = await session.execute(stmt)
                row: list[dict[str, Any]] | None = result.scalar_one_or_none()
                return row
        finally:
            record_db_query("postgres.get_chain_steps", (time.perf_counter() - start) * 1000)

    async def delete_chain_steps(self, chain_id: UUID) -> bool:
        """Delete chain steps. Returns True if row existed."""
        start = time.perf_counter()
        try:
            async with get_session() as session:
                stmt = delete(ReasoningChainSteps).where(ReasoningChainSteps.chain_id == chain_id)
                result = await session.execute(stmt)
                return bool(result.rowcount and result.rowcount > 0)  # type: ignore[attr-defined]
        finally:
            record_db_query("postgres.delete_chain_steps", (time.perf_counter() - start) * 1000)

    async def get_chain_steps_batch(
        self, chain_ids: list[UUID]
    ) -> dict[UUID, list[dict[str, Any]]]:
        """Fetch steps for multiple chains in one query."""
        if not chain_ids:
            return {}
        start = time.perf_counter()
        try:
            async with get_session() as session:
                stmt = select(ReasoningChainSteps.chain_id, ReasoningChainSteps.steps).where(
                    ReasoningChainSteps.chain_id.in_(chain_ids)
                )
                result = await session.execute(stmt)
                return {row.chain_id: row.steps for row in result}
        finally:
            record_db_query("postgres.get_chain_steps_batch", (time.perf_counter() - start) * 1000)

    async def add_orphaned_chain(self, chain_id: UUID, silo_id: UUID, error: str) -> None:
        """Add chain to dead-letter table."""
        start = time.perf_counter()
        try:
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
                result = await session.execute(stmt)
                if result.rowcount != 1:  # type: ignore[attr-defined]
                    raise RuntimeError(
                        f"add_orphaned_chain expected rowcount=1, got {result.rowcount} "  # type: ignore[attr-defined]
                        f"for chain_id={chain_id}"
                    )
        finally:
            record_db_query("postgres.add_orphaned_chain", (time.perf_counter() - start) * 1000)
