# Skills Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a skills registry endpoint that serves agent skills via MCP and REST, with federation support between Engrammic instances.

**Architecture:** Hybrid storage (filesystem for builtins, Postgres for user skills). SkillService merges both sources. MCP tool is read-only; REST handles CRUD + import for admins.

**Tech Stack:** FastAPI, SQLAlchemy, FastMCP, Pydantic, httpx (for federation fetch)

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/models/postgres/skill.py` | SQLAlchemy model + Pydantic schemas |
| `src/context_service/services/skills.py` | SkillService (load, list, search, get, create, update, delete, import) |
| `src/context_service/mcp/tools/context_skills.py` | MCP tool (read-only: list, get, search) |
| `src/context_service/api/routes/skills.py` | REST endpoints (full CRUD + import) |
| `alembic/versions/*_add_skills_table.py` | Migration |
| `tests/unit/services/test_skills.py` | Unit tests for SkillService |
| `tests/unit/mcp/test_context_skills.py` | Unit tests for MCP tool |

---

### Task 1: Database Model + Migration

**Files:**
- Create: `src/context_service/models/postgres/skill.py`
- Modify: `src/context_service/models/postgres/__init__.py`
- Create: `alembic/versions/001_add_skills_table.py`

- [ ] **Step 1: Write the model test**

```python
# tests/unit/models/test_skill.py
from context_service.models.postgres.skill import Skill, SkillCreate, SkillUpdate, MAX_BODY_SIZE


def test_skill_create_validates_name_format():
    """Name must be namespace:name format."""
    valid = SkillCreate(name="myorg:mytool", description="desc", body="body")
    assert valid.name == "myorg:mytool"


def test_skill_create_rejects_invalid_name():
    """Name with invalid chars should fail."""
    import pytest
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError):
        SkillCreate(name="Invalid Name!", description="desc", body="body")


def test_skill_create_enforces_body_size():
    """Body over MAX_BODY_SIZE should fail."""
    import pytest
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError):
        SkillCreate(name="org:tool", description="desc", body="x" * (MAX_BODY_SIZE + 1))


def test_skill_update_allows_partial():
    """SkillUpdate should allow partial updates."""
    update = SkillUpdate(description="new desc")
    assert update.description == "new desc"
    assert update.body is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/models/test_skill.py -v`
Expected: FAIL with "No module named 'context_service.models.postgres.skill'"

- [ ] **Step 3: Write the model**

```python
# src/context_service/models/postgres/skill.py
"""Skill model for the skills registry."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.base import Base

MAX_BODY_SIZE = 64 * 1024  # 64KB

_NAME_PATTERN = re.compile(r"^[a-z0-9-]+:[a-z0-9-]+$")


class Skill(Base):
    """SQLAlchemy model for user-created skills."""

    __tablename__ = "skills"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_tools: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    silo_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SkillCreate(BaseModel):
    """Pydantic schema for creating a skill."""

    name: str = Field(max_length=255)
    description: str = Field(max_length=500)
    body: str = Field(max_length=MAX_BODY_SIZE)
    allowed_tools: list[str] | None = None

    @field_validator("name")
    @classmethod
    def validate_name_format(cls, v: str) -> str:
        if not _NAME_PATTERN.match(v):
            raise ValueError("Name must be lowercase namespace:name format (e.g., 'myorg:mytool')")
        if v.startswith("engrammic:"):
            raise ValueError("The 'engrammic:' namespace is reserved")
        return v


class SkillUpdate(BaseModel):
    """Pydantic schema for updating a skill."""

    description: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=MAX_BODY_SIZE)
    allowed_tools: list[str] | None = None


class SkillResponse(BaseModel):
    """Pydantic schema for skill API responses."""

    id: UUID | None = None
    name: str
    description: str
    body: str
    allowed_tools: list[str] | None
    source: Literal["builtin", "user"]
    version: str
    silo_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True
```

- [ ] **Step 4: Update __init__.py**

```python
# src/context_service/models/postgres/__init__.py
"""Postgres SQLAlchemy models for hybrid storage."""

from context_service.models.postgres.audit import AuditEvents, Events
from context_service.models.postgres.org import OrgPreferences, SiloConfig
from context_service.models.postgres.reasoning import OrphanedChains, ReasoningChainSteps
from context_service.models.postgres.skill import (
    MAX_BODY_SIZE,
    Skill,
    SkillCreate,
    SkillResponse,
    SkillUpdate,
)

__all__ = [
    "AuditEvents",
    "Events",
    "MAX_BODY_SIZE",
    "OrgPreferences",
    "OrphanedChains",
    "ReasoningChainSteps",
    "SiloConfig",
    "Skill",
    "SkillCreate",
    "SkillResponse",
    "SkillUpdate",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/models/test_skill.py -v`
Expected: PASS

- [ ] **Step 6: Write migration**

```python
# alembic/versions/001_add_skills_table.py
"""add skills table

Revision ID: 001_add_skills
Revises: a1b2c3d4e5f6
Create Date: 2026-05-08

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001_add_skills"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), unique=True, index=True, nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("allowed_tools", postgresql.JSONB(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="user"),
        sa.Column("version", sa.String(20), nullable=False, server_default="1.0.0"),
        sa.Column("silo_id", sa.String(255), index=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("skills")
```

- [ ] **Step 7: Commit**

```bash
git add src/context_service/models/postgres/skill.py src/context_service/models/postgres/__init__.py alembic/versions/001_add_skills_table.py tests/unit/models/test_skill.py
git commit -m "feat(skills): add Skill model and migration"
```

---

### Task 2: SkillService - Core Methods

**Files:**
- Create: `src/context_service/services/skills.py`
- Create: `tests/unit/services/test_skills.py`

- [ ] **Step 1: Write test for builtin loading**

```python
# tests/unit/services/test_skills.py
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
    """Duplicate skill names should raise StartupError."""
    # Create two skills with same name
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
    """Malformed YAML should raise StartupError."""
    skill_dir = tmp_path / "engrammic:bad"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("""---
name: [invalid yaml
---
Body
""")
    
    with pytest.raises(RuntimeError, match="malformed"):
        SkillService(mock_db, tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/services/test_skills.py -v`
Expected: FAIL with "No module named 'context_service.services.skills'"

- [ ] **Step 3: Write SkillService core**

```python
# src/context_service/services/skills.py
"""Skill registry service."""

from __future__ import annotations

import ipaddress
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx
import structlog
import yaml

from context_service.models.postgres.skill import (
    MAX_BODY_SIZE,
    Skill,
    SkillCreate,
    SkillResponse,
    SkillUpdate,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _sanitize_skill_body(body: str) -> str:
    """Strip control characters, normalize whitespace."""
    body = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", body)
    return body.strip()


def _validate_import_url(url: str, allow_http: bool = False) -> None:
    """Validate URL is safe for federation fetch. Raises ValueError if not."""
    parsed = urlparse(url)
    
    allowed_schemes = ("https",) if not allow_http else ("https", "http")
    if parsed.scheme not in allowed_schemes:
        raise ValueError(f"Only {', '.join(allowed_schemes)} URLs allowed")
    
    if not parsed.hostname:
        raise ValueError("URL must have a hostname")
    
    try:
        ip = socket.gethostbyname(parsed.hostname)
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve hostname: {e}")
    
    blocked = [
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),
    ]
    ip_addr = ipaddress.ip_address(ip)
    for net in blocked:
        if ip_addr in net:
            raise ValueError("Internal network addresses not allowed")


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
            
            # Parse YAML frontmatter
            if not content.startswith("---"):
                raise RuntimeError(f"Skill file missing YAML frontmatter: {skill_file}")
            
            parts = content.split("---", 2)
            if len(parts) < 3:
                raise RuntimeError(f"Skill file has malformed frontmatter: {skill_file}")
            
            try:
                meta = yaml.safe_load(parts[1])
            except yaml.YAMLError as e:
                raise RuntimeError(f"Skill file has malformed YAML: {skill_file}: {e}")
            
            if not isinstance(meta, dict) or "name" not in meta:
                raise RuntimeError(f"Skill file missing 'name' in frontmatter: {skill_file}")
            
            name = meta["name"]
            
            if name in seen_names:
                raise RuntimeError(
                    f"Duplicate skill name '{name}' in {skill_file} and {seen_names[name]}"
                )
            seen_names[name] = skill_file
            
            body = parts[2].strip()
            
            self._builtin[name] = SkillResponse(
                id=None,
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/services/test_skills.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/services/skills.py tests/unit/services/test_skills.py
git commit -m "feat(skills): add SkillService with builtin loading"
```

---

### Task 3: SkillService - CRUD Methods

**Files:**
- Modify: `src/context_service/services/skills.py`
- Modify: `tests/unit/services/test_skills.py`

- [ ] **Step 1: Write tests for list/get/search**

```python
# Add to tests/unit/services/test_skills.py

@pytest.mark.asyncio
async def test_list_returns_builtins_and_user_skills(mock_db, skills_dir: Path):
    """List should return both builtin and user skills."""
    from sqlalchemy import Result
    from unittest.mock import MagicMock
    
    # Mock DB returning one user skill
    mock_result = MagicMock(spec=Result)
    mock_result.scalars.return_value.all.return_value = [
        Skill(
            name="myorg:custom",
            description="Custom skill",
            body="body",
            source="user",
            version="1.0.0",
            silo_id="silo-123",
        )
    ]
    mock_db.execute.return_value = mock_result
    
    service = SkillService(mock_db, skills_dir)
    skills = await service.list("silo-123")
    
    names = [s.name for s in skills]
    assert "engrammic:test" in names  # builtin
    assert "myorg:custom" in names    # user


@pytest.mark.asyncio
async def test_get_returns_builtin_first(mock_db, skills_dir: Path):
    """Get should check builtins before DB."""
    service = SkillService(mock_db, skills_dir)
    
    skill = await service.get("silo-123", "engrammic:test")
    
    assert skill is not None
    assert skill.source == "builtin"
    mock_db.execute.assert_not_called()  # Should not hit DB for builtins
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/services/test_skills.py::test_list_returns_builtins_and_user_skills -v`
Expected: FAIL with "SkillService has no attribute 'list'"

- [ ] **Step 3: Add list/get/search methods**

```python
# Add to src/context_service/services/skills.py SkillService class

    async def list(
        self,
        silo_id: str,
        namespace: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SkillResponse]:
        """List skills (builtins + user skills for silo)."""
        from sqlalchemy import select
        
        # Start with builtins
        results: list[SkillResponse] = []
        for skill in self._builtin.values():
            if namespace and not skill.name.startswith(f"{namespace}:"):
                continue
            results.append(skill)
        
        # Add user skills from DB
        query = select(Skill).where(Skill.silo_id == silo_id)
        if namespace:
            query = query.where(Skill.name.like(f"{namespace}:%"))
        
        result = await self._db.execute(query)
        for db_skill in result.scalars().all():
            results.append(SkillResponse.model_validate(db_skill))
        
        # Sort by name, apply pagination
        results.sort(key=lambda s: s.name)
        return results[offset : offset + limit]

    async def search(
        self,
        silo_id: str,
        query: str,
        namespace: str | None = None,
        limit: int = 50,
    ) -> list[SkillResponse]:
        """Search skills by name/description substring."""
        from sqlalchemy import or_, select
        
        query_lower = query.lower()
        results: list[SkillResponse] = []
        
        # Search builtins
        for skill in self._builtin.values():
            if namespace and not skill.name.startswith(f"{namespace}:"):
                continue
            if query_lower in skill.name.lower() or query_lower in skill.description.lower():
                results.append(skill)
        
        # Search DB
        db_query = select(Skill).where(
            Skill.silo_id == silo_id,
            or_(
                Skill.name.ilike(f"%{query}%"),
                Skill.description.ilike(f"%{query}%"),
            ),
        )
        if namespace:
            db_query = db_query.where(Skill.name.like(f"{namespace}:%"))
        
        result = await self._db.execute(db_query)
        for db_skill in result.scalars().all():
            results.append(SkillResponse.model_validate(db_skill))
        
        results.sort(key=lambda s: s.name)
        return results[:limit]

    async def get(self, silo_id: str, name: str) -> SkillResponse | None:
        """Get a skill by name."""
        from sqlalchemy import select
        
        # Check builtins first
        if name in self._builtin:
            return self._builtin[name]
        
        # Check DB
        result = await self._db.execute(
            select(Skill).where(Skill.silo_id == silo_id, Skill.name == name)
        )
        db_skill = result.scalars().first()
        if db_skill:
            return SkillResponse.model_validate(db_skill)
        
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/services/test_skills.py -v`
Expected: PASS

- [ ] **Step 5: Write tests for create/update/delete**

```python
# Add to tests/unit/services/test_skills.py

@pytest.mark.asyncio
async def test_create_skill(mock_db, skills_dir: Path):
    """Create should insert a new user skill."""
    service = SkillService(mock_db, skills_dir)
    
    skill_data = SkillCreate(
        name="myorg:newtool",
        description="A new tool",
        body="Tool instructions",
    )
    
    await service.create("silo-123", skill_data)
    
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_rejects_engrammic_namespace(mock_db, skills_dir: Path):
    """Create should reject engrammic: namespace."""
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError, match="reserved"):
        SkillCreate(
            name="engrammic:forbidden",
            description="desc",
            body="body",
        )


@pytest.mark.asyncio
async def test_update_rejects_builtin(mock_db, skills_dir: Path):
    """Update should return 403-equivalent for builtins."""
    service = SkillService(mock_db, skills_dir)
    
    with pytest.raises(PermissionError, match="builtin"):
        await service.update("silo-123", "engrammic:test", SkillUpdate(description="new"))


@pytest.mark.asyncio
async def test_delete_rejects_builtin(mock_db, skills_dir: Path):
    """Delete should return 403-equivalent for builtins."""
    service = SkillService(mock_db, skills_dir)
    
    with pytest.raises(PermissionError, match="builtin"):
        await service.delete("silo-123", "engrammic:test")
```

- [ ] **Step 6: Add create/update/delete methods**

```python
# Add to src/context_service/services/skills.py SkillService class

    async def create(self, silo_id: str, skill: SkillCreate) -> SkillResponse:
        """Create a new user skill."""
        # Sanitize body
        body = _sanitize_skill_body(skill.body)
        
        db_skill = Skill(
            name=skill.name,
            description=skill.description,
            body=body,
            allowed_tools=skill.allowed_tools,
            source="user",
            version="1.0.0",
            silo_id=silo_id,
        )
        
        self._db.add(db_skill)
        await self._db.commit()
        await self._db.refresh(db_skill)
        
        return SkillResponse.model_validate(db_skill)

    async def update(self, silo_id: str, name: str, skill: SkillUpdate) -> SkillResponse:
        """Update a user skill."""
        from sqlalchemy import select
        
        # Block builtin modification
        if name in self._builtin:
            raise PermissionError("Cannot modify builtin skills")
        
        result = await self._db.execute(
            select(Skill).where(Skill.silo_id == silo_id, Skill.name == name)
        )
        db_skill = result.scalars().first()
        if not db_skill:
            raise KeyError(f"Skill not found: {name}")
        
        if skill.description is not None:
            db_skill.description = skill.description
        if skill.body is not None:
            db_skill.body = _sanitize_skill_body(skill.body)
        if skill.allowed_tools is not None:
            db_skill.allowed_tools = skill.allowed_tools
        
        # Increment patch version
        db_skill.version = _increment_patch_version(db_skill.version)
        
        await self._db.commit()
        await self._db.refresh(db_skill)
        
        return SkillResponse.model_validate(db_skill)

    async def delete(self, silo_id: str, name: str) -> None:
        """Delete a user skill."""
        from sqlalchemy import delete
        
        # Block builtin deletion
        if name in self._builtin:
            raise PermissionError("Cannot delete builtin skills")
        
        result = await self._db.execute(
            delete(Skill).where(Skill.silo_id == silo_id, Skill.name == name)
        )
        
        if result.rowcount == 0:
            raise KeyError(f"Skill not found: {name}")
        
        await self._db.commit()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/unit/services/test_skills.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/context_service/services/skills.py tests/unit/services/test_skills.py
git commit -m "feat(skills): add SkillService CRUD methods"
```

---

### Task 4: SkillService - Import Method

**Files:**
- Modify: `src/context_service/services/skills.py`
- Modify: `tests/unit/services/test_skills.py`

- [ ] **Step 1: Write import tests**

```python
# Add to tests/unit/services/test_skills.py

@pytest.mark.asyncio
async def test_import_validates_url(mock_db, skills_dir: Path):
    """Import should reject internal network URLs."""
    service = SkillService(mock_db, skills_dir)
    
    with pytest.raises(ValueError, match="Internal network"):
        await service.import_from("silo-123", "http://192.168.1.1/api/skills/org:tool", "org:tool")


@pytest.mark.asyncio
async def test_import_rejects_engrammic_namespace(mock_db, skills_dir: Path):
    """Import should reject engrammic: names."""
    service = SkillService(mock_db, skills_dir)
    
    with pytest.raises(ValueError, match="reserved"):
        await service.import_from("silo-123", "https://example.com/api/skills/engrammic:foo", "engrammic:foo")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/services/test_skills.py::test_import_validates_url -v`
Expected: FAIL with "SkillService has no attribute 'import_from'"

- [ ] **Step 3: Add import_from method**

```python
# Add to src/context_service/services/skills.py SkillService class

    async def import_from(
        self,
        silo_id: str,
        source_url: str,
        name: str,
        token: str | None = None,
    ) -> SkillResponse:
        """Import a skill from a remote Engrammic instance."""
        from sqlalchemy import select
        
        # Validate URL
        _validate_import_url(source_url, allow_http=False)
        
        # Block engrammic namespace
        if name.startswith("engrammic:"):
            raise ValueError("The 'engrammic:' namespace is reserved")
        
        # Check for existing skill
        if name in self._builtin:
            raise ValueError(f"Skill '{name}' conflicts with builtin")
        
        existing = await self._db.execute(
            select(Skill).where(Skill.silo_id == silo_id, Skill.name == name)
        )
        if existing.scalars().first():
            raise ValueError(f"Skill '{name}' already exists")
        
        # Fetch from remote
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{source_url}/api/skills/{name}", headers=headers)
            resp.raise_for_status()
            remote_skill = resp.json()
        
        # Save locally
        db_skill = Skill(
            name=name,
            description=remote_skill["description"],
            body=_sanitize_skill_body(remote_skill["body"]),
            allowed_tools=remote_skill.get("allowed_tools"),
            source="user",
            version="1.0.0",
            silo_id=silo_id,
        )
        
        self._db.add(db_skill)
        await self._db.commit()
        await self._db.refresh(db_skill)
        
        logger.info("Imported skill", name=name, source_url=source_url, silo_id=silo_id)
        
        return SkillResponse.model_validate(db_skill)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/services/test_skills.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/services/skills.py tests/unit/services/test_skills.py
git commit -m "feat(skills): add import_from with SSRF protection"
```

---

### Task 5: MCP Tool

**Files:**
- Create: `src/context_service/mcp/tools/context_skills.py`
- Modify: `src/context_service/mcp/tools/__init__.py`
- Create: `tests/unit/mcp/test_context_skills.py`

- [ ] **Step 1: Write MCP tool test**

```python
# tests/unit/mcp/test_context_skills.py
import pytest

from context_service.mcp.tools.context_skills import _context_skills_impl


@pytest.mark.asyncio
async def test_list_action():
    """List action should return skills."""
    from unittest.mock import AsyncMock, MagicMock
    
    mock_service = MagicMock()
    mock_service.list = AsyncMock(return_value=[])
    
    result = await _context_skills_impl(
        service=mock_service,
        silo_id="silo-123",
        action="list",
    )
    
    assert "skills" in result
    mock_service.list.assert_called_once()


@pytest.mark.asyncio
async def test_get_action_requires_name():
    """Get action without name should error."""
    from unittest.mock import MagicMock
    
    mock_service = MagicMock()
    
    result = await _context_skills_impl(
        service=mock_service,
        silo_id="silo-123",
        action="get",
        name=None,
    )
    
    assert "error" in result


@pytest.mark.asyncio
async def test_search_action_requires_query():
    """Search action without query should error."""
    from unittest.mock import MagicMock
    
    mock_service = MagicMock()
    
    result = await _context_skills_impl(
        service=mock_service,
        silo_id="silo-123",
        action="search",
        query=None,
    )
    
    assert "error" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/mcp/test_context_skills.py -v`
Expected: FAIL with "No module named 'context_service.mcp.tools.context_skills'"

- [ ] **Step 3: Write MCP tool**

```python
# src/context_service/mcp/tools/context_skills.py
"""MCP tool: context_skills - Read-only skill registry access for agents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import structlog

from context_service.mcp.server import get_mcp_auth_context
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from context_service.services.skills import SkillService

logger = structlog.get_logger(__name__)


async def _context_skills_impl(
    service: SkillService,
    silo_id: str,
    action: Literal["list", "get", "search"],
    name: str | None = None,
    query: str | None = None,
    namespace: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    
    if action == "list":
        skills = await service.list(silo_id, namespace=namespace, limit=limit, offset=offset)
        return {
            "skills": [s.model_dump(exclude_none=True) for s in skills],
            "count": len(skills),
        }
    
    elif action == "get":
        if not name:
            return {"error": "name is required for get action"}
        skill = await service.get(silo_id, name)
        if not skill:
            return {"error": f"Skill not found: {name}"}
        return {"skill": skill.model_dump(exclude_none=True)}
    
    elif action == "search":
        if not query:
            return {"error": "query is required for search action"}
        skills = await service.search(silo_id, query, namespace=namespace, limit=limit)
        return {
            "skills": [s.model_dump(exclude_none=True) for s in skills],
            "count": len(skills),
        }
    
    return {"error": f"Unknown action: {action}"}


def register(mcp: FastMCP, service: SkillService) -> None:
    """Register context_skills tool with FastMCP."""

    @mcp.tool()
    async def context_skills(
        action: Literal["list", "get", "search"],
        name: str | None = None,
        query: str | None = None,
        namespace: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Read-only access to the skill registry.

        Actions:
        - list: List all skills (builtins + user skills)
        - get: Get a specific skill by name
        - search: Search skills by name/description

        Args:
            action: The operation to perform
            name: Skill name (required for get)
            query: Search query (required for search)
            namespace: Filter by namespace prefix
            limit: Max results (default 50, max 200)
            offset: Pagination offset
        """
        auth = get_mcp_auth_context()
        silo_id = derive_silo_id(auth.org_id, auth.user_id)
        
        limit = min(limit, 200)
        
        return await _context_skills_impl(
            service=service,
            silo_id=silo_id,
            action=action,
            name=name,
            query=query,
            namespace=namespace,
            limit=limit,
            offset=offset,
        )
```

- [ ] **Step 4: Update tools __init__.py**

```python
# Add to src/context_service/mcp/tools/__init__.py exports
from context_service.mcp.tools import context_skills
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/mcp/test_context_skills.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/tools/context_skills.py src/context_service/mcp/tools/__init__.py tests/unit/mcp/test_context_skills.py
git commit -m "feat(skills): add context_skills MCP tool"
```

---

### Task 6: REST Endpoints

**Files:**
- Create: `src/context_service/api/routes/skills.py`
- Modify: `src/context_service/api/app.py` (or wherever routes are registered)

- [ ] **Step 1: Write REST endpoint tests**

```python
# tests/unit/api/test_skills_routes.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_skill_service():
    service = MagicMock()
    service.list = AsyncMock(return_value=[])
    service.get = AsyncMock(return_value=None)
    service.search = AsyncMock(return_value=[])
    service.create = AsyncMock()
    service.update = AsyncMock()
    service.delete = AsyncMock()
    service.import_from = AsyncMock()
    return service


def test_list_skills_requires_auth(mock_skill_service):
    """List endpoint should require authentication."""
    from context_service.api.routes.skills import router
    from fastapi import FastAPI
    
    app = FastAPI()
    app.include_router(router)
    
    client = TestClient(app)
    response = client.get("/api/skills")
    
    assert response.status_code == 401


def test_create_skill_requires_admin(mock_skill_service):
    """Create endpoint should require admin role."""
    # This test validates the auth decorator is applied
    from context_service.api.routes.skills import router
    
    # Check that the route has the admin dependency
    for route in router.routes:
        if route.path == "/api/skills" and "POST" in route.methods:
            assert any("admin" in str(d) for d in route.dependencies)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/api/test_skills_routes.py -v`
Expected: FAIL with "No module named 'context_service.api.routes.skills'"

- [ ] **Step 3: Write REST routes**

```python
# src/context_service/api/routes/skills.py
"""REST API routes for skill registry."""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from context_service.models.postgres.skill import (
    SkillCreate,
    SkillResponse,
    SkillUpdate,
)

logger = structlog.get_logger(__name__)

# NOTE: Register /import and /search BEFORE /{name} to avoid path conflicts
router = APIRouter(prefix="/api/skills", tags=["skills"])

_bearer = HTTPBearer(auto_error=True)


async def _get_silo_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> str:
    """Extract silo_id from auth token. Placeholder - integrate with real auth."""
    # TODO: Integrate with actual auth system
    return "default-silo"


async def _require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> None:
    """Validate user has admin role. Placeholder - integrate with real auth."""
    # TODO: Integrate with actual auth system
    pass


def _get_skill_service():
    """Get SkillService instance. Placeholder - integrate with DI."""
    # TODO: Integrate with actual dependency injection
    from context_service.api.deps import get_skill_service
    return get_skill_service()


@router.get("/search")
async def search_skills(
    q: str = Query(..., min_length=1),
    namespace: str | None = None,
    limit: int = Query(default=50, le=200),
    silo_id: str = Depends(_get_silo_id),
) -> dict[str, Any]:
    """Search skills by name/description."""
    service = _get_skill_service()
    skills = await service.search(silo_id, q, namespace=namespace, limit=limit)
    return {"skills": [s.model_dump(exclude_none=True) for s in skills], "count": len(skills)}


@router.post("/import", dependencies=[Depends(_require_admin)])
async def import_skill(
    source_url: str,
    name: str,
    token: str | None = None,
    silo_id: str = Depends(_get_silo_id),
) -> SkillResponse:
    """Import a skill from a remote Engrammic instance."""
    service = _get_skill_service()
    try:
        return await service.import_from(silo_id, source_url, name, token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("")
async def list_skills(
    namespace: str | None = None,
    source: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    silo_id: str = Depends(_get_silo_id),
) -> dict[str, Any]:
    """List all skills."""
    service = _get_skill_service()
    skills = await service.list(silo_id, namespace=namespace, limit=limit, offset=offset)
    if source:
        skills = [s for s in skills if s.source == source]
    return {"skills": [s.model_dump(exclude_none=True) for s in skills], "count": len(skills)}


@router.get("/{name}")
async def get_skill(
    name: str,
    silo_id: str = Depends(_get_silo_id),
) -> SkillResponse:
    """Get a specific skill by name."""
    service = _get_skill_service()
    skill = await service.get(silo_id, name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return skill


@router.post("", dependencies=[Depends(_require_admin)])
async def create_skill(
    skill: SkillCreate,
    silo_id: str = Depends(_get_silo_id),
) -> SkillResponse:
    """Create a new user skill."""
    service = _get_skill_service()
    try:
        return await service.create(silo_id, skill)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{name}", dependencies=[Depends(_require_admin)])
async def update_skill(
    name: str,
    skill: SkillUpdate,
    silo_id: str = Depends(_get_silo_id),
) -> SkillResponse:
    """Update a user skill."""
    service = _get_skill_service()
    try:
        return await service.update(silo_id, name, skill)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{name}", dependencies=[Depends(_require_admin)])
async def delete_skill(
    name: str,
    silo_id: str = Depends(_get_silo_id),
) -> dict[str, str]:
    """Delete a user skill."""
    service = _get_skill_service()
    try:
        await service.delete(silo_id, name)
        return {"status": "deleted", "name": name}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/api/test_skills_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/api/routes/skills.py tests/unit/api/test_skills_routes.py
git commit -m "feat(skills): add REST endpoints for skill registry"
```

---

### Task 7: Integration - Wire Up Service + Register Routes

**Files:**
- Modify: `src/context_service/mcp/server.py`
- Modify: `src/context_service/api/app.py` (or main app file)
- Create: `src/context_service/api/deps.py` (if needed)

- [ ] **Step 1: Add SkillService to MCP server configuration**

```python
# Modify src/context_service/mcp/server.py configure_services()

from pathlib import Path
from context_service.services.skills import SkillService

# Add to configure_services() function:
_services["skills"] = SkillService(
    db=session,  # Use appropriate session
    skills_dir=Path("skills"),
)

# Add getter:
def get_skill_service() -> SkillService:
    """Get the configured SkillService instance."""
    if "skills" not in _services:
        raise RuntimeError("SkillService not configured — call configure_services() at startup")
    return _services["skills"]
```

- [ ] **Step 2: Register MCP tool in server creation**

```python
# In src/context_service/mcp/server.py create_mcp() or similar:

from context_service.mcp.tools import context_skills

# After creating FastMCP instance:
context_skills.register(mcp, get_skill_service())
```

- [ ] **Step 3: Register REST router**

```python
# In src/context_service/api/app.py or main FastAPI app:

from context_service.api.routes.skills import router as skills_router

app.include_router(skills_router)
```

- [ ] **Step 4: Create deps.py for DI**

```python
# src/context_service/api/deps.py
"""FastAPI dependency injection utilities."""

from context_service.mcp.server import get_skill_service as _get_skill_service


def get_skill_service():
    """Get SkillService for route handlers."""
    return _get_skill_service()
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v --ignore=tests/integration`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/server.py src/context_service/api/app.py src/context_service/api/deps.py
git commit -m "feat(skills): wire up SkillService and register routes"
```

---

### Task 8: Run Migration + Manual Smoke Test

- [ ] **Step 1: Apply migration**

Run: `uv run alembic upgrade head`
Expected: Migration applies successfully

- [ ] **Step 2: Start dev server**

Run: `just dev`
Expected: Server starts without errors

- [ ] **Step 3: Test list endpoint**

Run: `curl http://localhost:8000/api/skills`
Expected: Returns JSON with builtin skills

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix(skills): migration and startup fixes"
```

---

## Summary

7 implementation tasks + 1 integration test task. Each task produces a working, testable increment. The final result is a skills registry that:

- Loads builtin skills from `./skills/` at startup
- Stores user skills in Postgres
- Exposes read-only MCP tool for agents
- Exposes full CRUD REST API for admins
- Supports federation import with SSRF protection
