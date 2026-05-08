"""Tests for SkillService core methods."""

from datetime import UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from context_service.schemas.skill import SkillUpdate
from context_service.services.skills import (
    SkillService,
    _increment_patch_version,
    _sanitize_skill_body,
)


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Create a temp skills directory with test skills."""
    skill_dir = tmp_path / "engrammic:test"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("""---
name: engrammic:test
description: A test skill
allowed-tools:
  - mcp__engrammic__context_store
---

Test skill body content.
""")
    return tmp_path


def test_load_builtin_skills(mock_db, skills_dir: Path):
    """SkillService should load builtin skills from filesystem."""
    service = SkillService(mock_db, skills_dir)

    assert "engrammic:test" in service._builtin
    skill = service._builtin["engrammic:test"]
    assert skill.description == "A test skill"
    assert skill.source == "builtin"
    assert skill.silo_id == "*"


def test_load_builtin_fails_on_duplicate(mock_db, tmp_path: Path):
    """Duplicate skill names should raise RuntimeError."""
    for subdir in ["engrammic:dup", "engrammic:dup-copy"]:
        d = tmp_path / subdir
        d.mkdir()
        (d / "SKILL.md").write_text("""---
name: engrammic:dup
description: Duplicate
---
Body
""")

    with pytest.raises(RuntimeError, match="Duplicate"):
        SkillService(mock_db, tmp_path)


def test_load_builtin_fails_on_malformed_yaml(mock_db, tmp_path: Path):
    """Malformed YAML should raise RuntimeError."""
    skill_dir = tmp_path / "engrammic:bad"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("""---
name: [invalid yaml
---
Body
""")

    with pytest.raises(RuntimeError, match="malformed"):
        SkillService(mock_db, tmp_path)


# --- Helper function tests ---


def test_sanitize_skill_body_strips_control_chars():
    raw = "hello\x00world\x1fbye"
    assert _sanitize_skill_body(raw) == "helloworld bye".replace(" ", "")
    assert "\x00" not in _sanitize_skill_body(raw)
    assert "\x1f" not in _sanitize_skill_body(raw)


def test_sanitize_skill_body_strips_whitespace():
    assert _sanitize_skill_body("  hello  ") == "hello"


def test_increment_patch_version_basic():
    assert _increment_patch_version("1.0.0") == "1.0.1"
    assert _increment_patch_version("1.0.9") == "1.0.10"
    assert _increment_patch_version("2.3.7") == "2.3.8"


def test_increment_patch_version_invalid_fallback():
    assert _increment_patch_version("1.0") == "1.0.1"
    assert _increment_patch_version("bad") == "1.0.1"
    assert _increment_patch_version("1.x.0") == "1.0.1"


# --- CRUD method tests ---


def _make_db_skill_mock(name: str = "user:skill", silo_id: str = "silo-123") -> MagicMock:
    """Create a mock DB skill row."""
    from datetime import datetime

    m = MagicMock()
    m.id = uuid4()
    m.name = name
    m.description = "A user skill"
    m.body = "User skill body"
    m.allowed_tools = None
    m.source = "user"
    m.version = "1.0.0"
    m.silo_id = silo_id
    m.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    m.updated_at = datetime(2024, 1, 1, tzinfo=UTC)
    return m


def _mock_db_returning(rows: list) -> AsyncMock:
    """Build a mock db that returns given rows from execute."""
    db = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = rows
    scalars_mock.first.return_value = rows[0] if rows else None
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    db.execute.return_value = result_mock
    return db


@pytest.mark.asyncio
async def test_list_returns_builtins_and_user_skills(skills_dir: Path):
    """List should return both builtin and user skills."""
    user_row = _make_db_skill_mock("user:custom")
    db = _mock_db_returning([user_row])

    service = SkillService(db, skills_dir)
    result = await service.list("silo-123")

    names = [s.name for s in result]
    assert "engrammic:test" in names
    assert "user:custom" in names


@pytest.mark.asyncio
async def test_list_filters_by_namespace(skills_dir: Path):
    """List with namespace filter should only return matching skills."""
    user_row = _make_db_skill_mock("user:custom")
    db = _mock_db_returning([user_row])

    service = SkillService(db, skills_dir)
    result = await service.list("silo-123", namespace="engrammic")

    assert all(s.name.startswith("engrammic:") for s in result)


@pytest.mark.asyncio
async def test_list_paginates(skills_dir: Path):
    """List offset/limit should paginate results."""
    db = _mock_db_returning([])
    service = SkillService(db, skills_dir)

    all_skills = await service.list("silo-123", limit=100)
    page = await service.list("silo-123", limit=1, offset=0)

    assert len(page) == min(1, len(all_skills))


@pytest.mark.asyncio
async def test_get_returns_builtin_first(mock_db, skills_dir: Path):
    """Get should check builtins before DB."""
    service = SkillService(mock_db, skills_dir)
    skill = await service.get("silo-123", "engrammic:test")

    assert skill is not None
    assert skill.source == "builtin"
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_returns_user_skill_from_db(skills_dir: Path):
    """Get should fall back to DB for non-builtin skills."""
    user_row = _make_db_skill_mock("user:custom")
    db = _mock_db_returning([user_row])

    service = SkillService(db, skills_dir)
    skill = await service.get("silo-123", "user:custom")

    assert skill is not None
    assert skill.name == "user:custom"
    assert skill.source == "user"


@pytest.mark.asyncio
async def test_get_returns_none_for_missing(skills_dir: Path):
    """Get should return None for unknown skills."""
    db = _mock_db_returning([])
    service = SkillService(db, skills_dir)
    result = await service.get("silo-123", "no:such")
    assert result is None


@pytest.mark.asyncio
async def test_update_rejects_builtin(mock_db, skills_dir: Path):
    """Update should raise PermissionError for builtins."""
    service = SkillService(mock_db, skills_dir)
    with pytest.raises(PermissionError, match="builtin"):
        await service.update("silo-123", "engrammic:test", SkillUpdate(description="new"))


@pytest.mark.asyncio
async def test_delete_rejects_builtin(mock_db, skills_dir: Path):
    """Delete should raise PermissionError for builtins."""
    service = SkillService(mock_db, skills_dir)
    with pytest.raises(PermissionError, match="builtin"):
        await service.delete("silo-123", "engrammic:test")


@pytest.mark.asyncio
async def test_update_increments_version(skills_dir: Path):
    """Update should auto-increment patch version."""
    user_row = _make_db_skill_mock("user:custom")
    user_row.version = "1.0.3"
    db = _mock_db_returning([user_row])

    # Make refresh update the version on the mock row
    async def fake_refresh(obj: object) -> None:
        pass

    db.refresh = fake_refresh

    service = SkillService(db, skills_dir)
    await service.update("silo-123", "user:custom", SkillUpdate(description="updated"))

    assert user_row.version == "1.0.4"


@pytest.mark.asyncio
async def test_update_raises_key_error_for_missing(skills_dir: Path):
    """Update should raise KeyError if skill not found."""
    db = _mock_db_returning([])
    service = SkillService(db, skills_dir)
    with pytest.raises(KeyError):
        await service.update("silo-123", "no:such", SkillUpdate(description="x"))
