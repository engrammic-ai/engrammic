"""Tests for SkillService core methods."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from context_service.services.skills import SkillService


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
