"""CRUD service for per-silo tag configuration."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from context_service.models.tag_config import DEFAULT_CONSTRAINTS, DEFAULT_SETTINGS, SiloTagConfig


class TagConfigService:
    """Service layer for reading and mutating SiloTagConfig records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, silo_id: UUID) -> SiloTagConfig | None:
        """Return config for silo, or None if not found."""
        return await self._session.get(SiloTagConfig, silo_id)

    async def get_or_create(self, silo_id: UUID) -> SiloTagConfig:
        """Return existing config or create one with defaults."""
        cfg = await self.get(silo_id)
        if cfg is not None:
            return cfg

        cfg = SiloTagConfig()
        cfg.silo_id = silo_id
        cfg.core_tags = []
        cfg.dynamic_tags = []
        cfg.settings = DEFAULT_SETTINGS.copy()
        cfg.constraints = DEFAULT_CONSTRAINTS.copy()

        self._session.add(cfg)
        await self._session.flush()
        return cfg

    async def add_core_tags(self, silo_id: UUID, tags: list[str]) -> SiloTagConfig:
        """Add tags to core_tags, deduplicating."""
        cfg = await self.get_or_create(silo_id)
        existing = set(cfg.core_tags or [])
        merged = list(existing | set(tags))
        cfg.core_tags = merged
        await self._session.flush()
        return cfg

    async def add_dynamic_tags(self, silo_id: UUID, tags: list[str]) -> SiloTagConfig:
        """Add tags to dynamic_tags, deduplicating."""
        cfg = await self.get_or_create(silo_id)
        existing = set(cfg.dynamic_tags or [])
        merged = list(existing | set(tags))
        cfg.dynamic_tags = merged
        await self._session.flush()
        return cfg

    async def remove_dynamic_tags(self, silo_id: UUID, tags: list[str]) -> SiloTagConfig:
        """Remove tags from dynamic_tags. Raises KeyError if config does not exist."""
        cfg = await self.get(silo_id)
        if cfg is None:
            raise KeyError(str(silo_id))

        to_remove = set(tags)
        cfg.dynamic_tags = [t for t in (cfg.dynamic_tags or []) if t not in to_remove]
        await self._session.flush()
        return cfg

    async def update_settings(self, silo_id: UUID, updates: dict[str, Any]) -> SiloTagConfig:
        """Merge updates into settings. Raises KeyError if config does not exist."""
        cfg = await self.get(silo_id)
        if cfg is None:
            raise KeyError(str(silo_id))

        cfg.settings = {**(cfg.settings or {}), **updates}
        await self._session.flush()
        return cfg

    async def update_constraints(self, silo_id: UUID, updates: dict[str, Any]) -> SiloTagConfig:
        """Merge updates into constraints. Raises KeyError if config does not exist."""
        cfg = await self.get(silo_id)
        if cfg is None:
            raise KeyError(str(silo_id))

        cfg.constraints = {**(cfg.constraints or {}), **updates}
        await self._session.flush()
        return cfg

    async def get_all_tags(self, silo_id: UUID) -> list[str]:
        """Return deduplicated union of core and dynamic tags, or [] if not found."""
        cfg = await self.get(silo_id)
        if cfg is None:
            return []
        return cfg.all_tags()
