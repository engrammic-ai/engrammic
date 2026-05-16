"""Reads silo_config.preset from Postgres for the PresetResolver."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from context_service.db.postgres import get_session
from context_service.models.postgres.org import SiloConfig


class PostgresBindingSource:
    """BindingSource backed by the Postgres silo_config table."""

    async def get_silo_preset_name(self, silo_id: str) -> str | None:
        async with get_session() as session:
            stmt = select(SiloConfig.preset).where(SiloConfig.silo_id == UUID(silo_id))
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
