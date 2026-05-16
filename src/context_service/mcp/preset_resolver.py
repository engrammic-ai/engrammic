"""Resolve a silo to its ICP Preset, with a small in-process TTL cache.

Binding source of truth: Postgres silo_config.preset. Definitions come from
the PresetRegistry (mcp_presets.yaml). Unknown or absent bindings fall back to
the configured default preset.
"""

from __future__ import annotations

import time
from typing import Protocol

import structlog

from context_service.mcp.tools.preset_registry import Preset, get_preset

logger = structlog.get_logger(__name__)


class BindingSource(Protocol):
    """Reads the raw preset name bound to a silo (or None)."""

    async def get_silo_preset_name(self, silo_id: str) -> str | None: ...


class PresetResolver:
    """Silo -> Preset with TTL caching."""

    def __init__(
        self,
        binding_source: BindingSource,
        default_preset: str,
        ttl_seconds: float = 60.0,
    ) -> None:
        self._src = binding_source
        self._default = default_preset
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, Preset]] = {}

    async def resolve(self, silo_id: str) -> Preset:
        now = time.monotonic()
        cached = self._cache.get(silo_id)
        if cached is not None and (now - cached[0]) < self._ttl:
            return cached[1]

        raw_name = await self._src.get_silo_preset_name(silo_id)
        preset = self._resolve_name(raw_name)
        self._cache[silo_id] = (now, preset)
        return preset

    def _resolve_name(self, raw_name: str | None) -> Preset:
        name = raw_name or self._default
        try:
            return get_preset(name)
        except KeyError:
            logger.warning(
                "invalid_mcp_preset", preset=name, fallback=self._default
            )
            return get_preset(self._default)
