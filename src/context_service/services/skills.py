"""Skill registry service."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import yaml

from context_service.schemas.skill import SkillResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_BUILTIN_UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid.NAMESPACE_DNS


def _builtin_id(name: str) -> uuid.UUID:
    """Generate a stable deterministic UUID for a builtin skill."""
    return uuid.uuid5(_BUILTIN_UUID_NAMESPACE, f"engrammic.skill.{name}")


class SkillService:
    """Service for managing agent skills."""

    def __init__(self, db: AsyncSession, skills_dir: Path):
        self._db = db
        self._builtin: dict[str, SkillResponse] = {}
        self._load_builtin(skills_dir)

    def _load_builtin(self, skills_dir: Path) -> None:
        """Load builtin skills from filesystem."""
        if not skills_dir.exists():
            logger.warning("Skills directory does not exist", path=str(skills_dir))
            return

        seen_names: dict[str, Path] = {}

        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            content = skill_file.read_text()

            if not content.startswith("---"):
                raise RuntimeError(f"Skill file missing YAML frontmatter: {skill_file}")

            parts = content.split("---", 2)
            if len(parts) < 3:
                raise RuntimeError(f"Skill file has malformed frontmatter: {skill_file}")

            try:
                meta = yaml.safe_load(parts[1])
            except yaml.YAMLError as e:
                raise RuntimeError(f"Skill file has malformed YAML: {skill_file}: {e}") from e

            if not isinstance(meta, dict) or "name" not in meta:
                raise RuntimeError(f"Skill file missing 'name' in frontmatter: {skill_file}")

            name: str = meta["name"]

            if name in seen_names:
                raise RuntimeError(
                    f"Duplicate skill name '{name}' in {skill_file} and {seen_names[name]}"
                )
            seen_names[name] = skill_file

            body = parts[2].strip()

            self._builtin[name] = SkillResponse(
                id=_builtin_id(name),
                name=name,
                description=meta.get("description", ""),
                body=body,
                allowed_tools=meta.get("allowed-tools"),
                source="builtin",
                version=meta.get("version", "1.0.0"),
                silo_id="*",
                created_at=None,
                updated_at=None,
            )

        logger.info("Loaded builtin skills", count=len(self._builtin))
