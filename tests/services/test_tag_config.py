"""Tests for TagConfigService CRUD operations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from context_service.models.tag_config import DEFAULT_CONSTRAINTS, DEFAULT_SETTINGS, SiloTagConfig
from context_service.services.tag_config import TagConfigService

SILO_ID = uuid4()


def _make_config(**kwargs) -> SiloTagConfig:
    cfg = SiloTagConfig()
    cfg.silo_id = kwargs.get("silo_id", SILO_ID)
    cfg.core_tags = kwargs.get("core_tags", [])
    cfg.dynamic_tags = kwargs.get("dynamic_tags", [])
    cfg.settings = kwargs.get("settings", DEFAULT_SETTINGS.copy())
    cfg.constraints = kwargs.get("constraints", DEFAULT_CONSTRAINTS.copy())
    return cfg


@pytest.fixture
def session() -> AsyncMock:
    s = AsyncMock()
    s.get = AsyncMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    return s


@pytest.fixture
def service(session: AsyncMock) -> TagConfigService:
    return TagConfigService(session)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_none_when_not_exists(service: TagConfigService, session: AsyncMock):
    session.get.return_value = None

    result = await service.get(SILO_ID)

    assert result is None
    session.get.assert_awaited_once_with(SiloTagConfig, SILO_ID)


@pytest.mark.asyncio
async def test_get_returns_existing_config(service: TagConfigService, session: AsyncMock):
    cfg = _make_config()
    session.get.return_value = cfg

    result = await service.get(SILO_ID)

    assert result is cfg


# ---------------------------------------------------------------------------
# get_or_create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_returns_new_config_when_not_exists(
    service: TagConfigService, session: AsyncMock
):
    session.get.return_value = None

    result = await service.get_or_create(SILO_ID)

    assert result.silo_id == SILO_ID
    assert result.core_tags == []
    assert result.dynamic_tags == []
    assert result.settings == DEFAULT_SETTINGS
    assert result.constraints == DEFAULT_CONSTRAINTS
    session.add.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_or_create_returns_existing_config(
    service: TagConfigService, session: AsyncMock
):
    cfg = _make_config(core_tags=["python"])
    session.get.return_value = cfg

    result = await service.get_or_create(SILO_ID)

    assert result is cfg
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# add_core_tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_core_tags_appends_new_tags(service: TagConfigService, session: AsyncMock):
    cfg = _make_config(core_tags=["python"])
    session.get.return_value = cfg

    result = await service.add_core_tags(SILO_ID, ["rust", "go"])

    assert "rust" in result.core_tags
    assert "go" in result.core_tags
    assert "python" in result.core_tags
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_core_tags_deduplicates(service: TagConfigService, session: AsyncMock):
    cfg = _make_config(core_tags=["python"])
    session.get.return_value = cfg

    result = await service.add_core_tags(SILO_ID, ["python", "python"])

    assert result.core_tags.count("python") == 1


@pytest.mark.asyncio
async def test_add_core_tags_creates_config_if_missing(
    service: TagConfigService, session: AsyncMock
):
    session.get.return_value = None

    result = await service.add_core_tags(SILO_ID, ["rust"])

    assert "rust" in result.core_tags


# ---------------------------------------------------------------------------
# add_dynamic_tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_dynamic_tags_appends_new_tags(service: TagConfigService, session: AsyncMock):
    cfg = _make_config(dynamic_tags=["async"])
    session.get.return_value = cfg

    result = await service.add_dynamic_tags(SILO_ID, ["oop", "fp"])

    assert "oop" in result.dynamic_tags
    assert "fp" in result.dynamic_tags
    assert "async" in result.dynamic_tags


@pytest.mark.asyncio
async def test_add_dynamic_tags_deduplicates(service: TagConfigService, session: AsyncMock):
    cfg = _make_config(dynamic_tags=["async"])
    session.get.return_value = cfg

    result = await service.add_dynamic_tags(SILO_ID, ["async"])

    assert result.dynamic_tags.count("async") == 1


# ---------------------------------------------------------------------------
# remove_dynamic_tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_dynamic_tags_removes_specified(
    service: TagConfigService, session: AsyncMock
):
    cfg = _make_config(dynamic_tags=["async", "oop", "fp"])
    session.get.return_value = cfg

    result = await service.remove_dynamic_tags(SILO_ID, ["oop"])

    assert "oop" not in result.dynamic_tags
    assert "async" in result.dynamic_tags
    assert "fp" in result.dynamic_tags
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_dynamic_tags_ignores_missing(
    service: TagConfigService, session: AsyncMock
):
    cfg = _make_config(dynamic_tags=["async"])
    session.get.return_value = cfg

    result = await service.remove_dynamic_tags(SILO_ID, ["nonexistent"])

    assert result.dynamic_tags == ["async"]


@pytest.mark.asyncio
async def test_remove_dynamic_tags_raises_when_config_missing(
    service: TagConfigService, session: AsyncMock
):
    session.get.return_value = None

    with pytest.raises(KeyError, match=str(SILO_ID)):
        await service.remove_dynamic_tags(SILO_ID, ["oop"])


# ---------------------------------------------------------------------------
# update_settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_settings_merges_values(service: TagConfigService, session: AsyncMock):
    cfg = _make_config()
    session.get.return_value = cfg

    result = await service.update_settings(SILO_ID, {"max_tags": 10})

    assert result.settings["max_tags"] == 10
    assert result.settings["min_tags"] == DEFAULT_SETTINGS["min_tags"]
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_settings_raises_when_config_missing(
    service: TagConfigService, session: AsyncMock
):
    session.get.return_value = None

    with pytest.raises(KeyError, match=str(SILO_ID)):
        await service.update_settings(SILO_ID, {"max_tags": 10})


# ---------------------------------------------------------------------------
# update_constraints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_constraints_merges_values(service: TagConfigService, session: AsyncMock):
    cfg = _make_config()
    session.get.return_value = cfg

    result = await service.update_constraints(SILO_ID, {"mutual_exclusion": ["a", "b"]})

    assert result.constraints["mutual_exclusion"] == ["a", "b"]
    assert "hierarchy" in result.constraints
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_constraints_raises_when_config_missing(
    service: TagConfigService, session: AsyncMock
):
    session.get.return_value = None

    with pytest.raises(KeyError, match=str(SILO_ID)):
        await service.update_constraints(SILO_ID, {"hierarchy": {}})


# ---------------------------------------------------------------------------
# get_all_tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_all_tags_returns_union(service: TagConfigService, session: AsyncMock):
    cfg = _make_config(core_tags=["python", "rust"], dynamic_tags=["async", "rust"])
    session.get.return_value = cfg

    result = await service.get_all_tags(SILO_ID)

    assert set(result) == {"python", "rust", "async"}


@pytest.mark.asyncio
async def test_get_all_tags_returns_empty_when_config_missing(
    service: TagConfigService, session: AsyncMock
):
    session.get.return_value = None

    result = await service.get_all_tags(SILO_ID)

    assert result == []
