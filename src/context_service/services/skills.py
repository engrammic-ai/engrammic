"""Skill registry service."""

from __future__ import annotations

import builtins
import ipaddress
import re
import socket
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
import structlog
import yaml
from sqlalchemy import delete, select

from context_service.models.postgres.skill import Skill
from context_service.schemas.skill import (
    RESERVED_NAMESPACES,
    SkillCreate,
    SkillResponse,
    SkillUpdate,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _builtin_id(name: str) -> uuid.UUID:
    """Generate a stable deterministic UUID for a builtin skill."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"engrammic.skill.{name}")


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

    async def list(
        self,
        silo_id: str,
        namespace: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[SkillResponse]:
        """List skills (builtins + user skills for silo). Merge, filter by namespace, paginate."""
        builtin_skills = list(self._builtin.values())

        stmt = select(Skill).where(Skill.silo_id == silo_id)
        result = await self._db.execute(stmt)
        user_skills = [SkillResponse.model_validate(s) for s in result.scalars().all()]

        merged = builtin_skills + user_skills

        if namespace is not None:
            prefix = f"{namespace}:"
            merged = [s for s in merged if s.name.startswith(prefix)]

        return merged[offset : offset + limit]

    async def search(
        self,
        silo_id: str,
        query: str,
        namespace: str | None = None,
        limit: int = 50,
    ) -> builtins.list[SkillResponse]:
        """Search skills by name/description substring match."""
        all_skills = await self.list(silo_id, namespace=namespace, limit=10_000, offset=0)
        q = query.lower()
        return [s for s in all_skills if q in s.name.lower() or q in s.description.lower()][:limit]

    async def get(self, silo_id: str, name: str) -> SkillResponse | None:
        """Get skill by name. Check builtins first, then DB."""
        if name in self._builtin:
            return self._builtin[name]

        stmt = select(Skill).where(Skill.silo_id == silo_id, Skill.name == name)
        result = await self._db.execute(stmt)
        row = result.scalars().first()
        if row is None:
            return None
        return SkillResponse.model_validate(row)

    async def create(self, silo_id: str, skill: SkillCreate) -> SkillResponse:
        """Create user skill. Sanitize body, insert to DB."""
        sanitized_body = _sanitize_skill_body(skill.body)
        db_skill = Skill(
            name=skill.name,
            description=skill.description,
            body=sanitized_body,
            allowed_tools=skill.allowed_tools,
            source="user",
            version="1.0.0",
            silo_id=silo_id,
        )
        self._db.add(db_skill)
        await self._db.flush()
        await self._db.refresh(db_skill)
        return SkillResponse.model_validate(db_skill)

    async def update(self, silo_id: str, name: str, skill: SkillUpdate) -> SkillResponse:
        """Update user skill. 403 (PermissionError) if builtin. Auto-increment patch version."""
        if name in self._builtin:
            raise PermissionError(f"Cannot modify builtin skill '{name}'")

        stmt = select(Skill).where(Skill.silo_id == silo_id, Skill.name == name)
        result = await self._db.execute(stmt)
        db_skill = result.scalars().first()
        if db_skill is None:
            raise KeyError(f"Skill '{name}' not found")

        if skill.description is not None:
            db_skill.description = skill.description
        if skill.body is not None:
            db_skill.body = _sanitize_skill_body(skill.body)
        if skill.allowed_tools is not None:
            db_skill.allowed_tools = skill.allowed_tools

        db_skill.version = _increment_patch_version(db_skill.version)

        await self._db.flush()
        await self._db.refresh(db_skill)
        return SkillResponse.model_validate(db_skill)

    async def delete(self, silo_id: str, name: str) -> None:
        """Delete user skill. 403 (PermissionError) if builtin."""
        if name in self._builtin:
            raise PermissionError(f"Cannot delete builtin skill '{name}'")

        stmt = delete(Skill).where(Skill.silo_id == silo_id, Skill.name == name)
        result = await self._db.execute(stmt)
        if not result.rowcount:  # type: ignore[attr-defined]
            raise KeyError(f"Skill '{name}' not found")

    async def import_from(
        self,
        silo_id: str,
        source_url: str,
        name: str,
        token: str | None = None,
    ) -> SkillResponse:
        """Import a skill from a remote Engrammic instance.

        1. Validate source_url (SSRF protection)
        2. Reject if name starts with any reserved namespace ("engrammic:", "coding:", "b2b-ops:")
        3. Check for existing skill (builtin or user)
        4. Fetch from remote: GET {source_url}/api/skills/{name}
        5. Sanitize fetched body
        6. Save locally with source="user", version="1.0.0"
        """
        _validate_import_url(source_url)

        for reserved in RESERVED_NAMESPACES:
            if name.startswith(reserved):
                raise ValueError(
                    f"Skill name '{name}' uses reserved namespace '{reserved.rstrip(':')}'"
                )

        existing = await self.get(silo_id, name)
        if existing is not None:
            raise ValueError(f"Skill '{name}' already exists")

        headers: dict[str, str] = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"

        fetch_url = f"{source_url.rstrip('/')}/api/skills/{name}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=False) as client:
            try:
                response = await client.get(fetch_url, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ValueError(f"Remote server returned {e.response.status_code}") from e
            except httpx.RequestError as e:
                raise ValueError(f"Failed to fetch from remote: {e}") from e

        data = response.json()
        body = _sanitize_skill_body(str(data.get("body") or ""))
        description = str(data.get("description") or "")
        allowed_tools = data.get("allowed_tools")
        if allowed_tools is not None and not isinstance(allowed_tools, list):
            raise ValueError("Invalid allowed_tools in remote skill")

        db_skill = Skill(
            name=name,
            description=description,
            body=body,
            allowed_tools=allowed_tools,
            source="user",
            version="1.0.0",
            silo_id=silo_id,
        )
        self._db.add(db_skill)
        await self._db.flush()
        await self._db.refresh(db_skill)
        return SkillResponse.model_validate(db_skill)


def _validate_import_url(url: str, allow_http: bool = False) -> None:
    """Validate URL is safe for federation fetch. Raises ValueError if not."""
    parsed = urlparse(url)

    allowed_schemes = ("https",) if not allow_http else ("https", "http")
    if parsed.scheme not in allowed_schemes:
        raise ValueError(f"Only {', '.join(allowed_schemes)} URLs allowed")

    if not parsed.hostname:
        raise ValueError("URL must have a hostname")

    try:
        addrs = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve hostname: {e}") from e

    blocked_v4 = [
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),
    ]
    blocked_v6 = [
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
    ]

    for _family, _type, _proto, _canonname, sockaddr in addrs:
        ip_str = sockaddr[0]
        ip_addr = ipaddress.ip_address(ip_str)

        if ip_addr.version == 4:
            for net in blocked_v4:
                if ip_addr in net:
                    raise ValueError("Internal network addresses not allowed")
        else:
            for net in blocked_v6:
                if ip_addr in net:
                    raise ValueError("Internal network addresses not allowed")


def _sanitize_skill_body(body: str) -> str:
    """Strip control characters, normalize whitespace."""
    body = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", body)
    return body.strip()


def _increment_patch_version(version: str) -> str:
    """Increment patch version: 1.0.9 -> 1.0.10"""
    parts = version.split(".")
    if len(parts) != 3:
        return "1.0.1"
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{major}.{minor}.{patch + 1}"
    except ValueError:
        return "1.0.1"
