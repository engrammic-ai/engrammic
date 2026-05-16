"""Tests for the TTL-cached silo->preset resolver."""

from __future__ import annotations

import pytest

from context_service.mcp.preset_resolver import PresetResolver


class _FakeBindingSource:
    """Stands in for the Postgres silo_config.preset lookup."""

    def __init__(self, value: str | None):
        self.value = value
        self.calls = 0

    async def get_silo_preset_name(self, silo_id: str) -> str | None:
        self.calls += 1
        return self.value


@pytest.mark.asyncio
async def test_resolves_bound_preset():
    src = _FakeBindingSource("b2b-ops")
    r = PresetResolver(binding_source=src, default_preset="coding", ttl_seconds=60)
    p = await r.resolve("silo-1")
    assert p.name == "b2b-ops"
    assert p.namespace == "b2b-ops"


@pytest.mark.asyncio
async def test_falls_back_to_default_when_unbound():
    src = _FakeBindingSource(None)
    r = PresetResolver(binding_source=src, default_preset="coding", ttl_seconds=60)
    p = await r.resolve("silo-1")
    assert p.name == "coding"


@pytest.mark.asyncio
async def test_unknown_bound_name_falls_back_to_default():
    src = _FakeBindingSource("garbage-preset")
    r = PresetResolver(binding_source=src, default_preset="coding", ttl_seconds=60)
    p = await r.resolve("silo-1")
    assert p.name == "coding"


@pytest.mark.asyncio
async def test_cache_avoids_repeat_db_calls_within_ttl():
    src = _FakeBindingSource("coding")
    r = PresetResolver(binding_source=src, default_preset="coding", ttl_seconds=60)
    await r.resolve("silo-1")
    await r.resolve("silo-1")
    assert src.calls == 1
