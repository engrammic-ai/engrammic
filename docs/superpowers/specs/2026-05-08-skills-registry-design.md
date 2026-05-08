# Skills Registry Design

Distribution endpoint for agent skills via MCP and REST.

## Context

Skills are markdown files with YAML frontmatter that teach agents how to use Engrammic tools. Currently they live in the filesystem with no distribution mechanism. This design adds a registry that serves skills to agent runtimes and enables federation between Engrammic instances.

## Decisions

| Aspect | Decision |
|--------|----------|
| Storage | Hybrid: `./skills/` for builtin, Postgres for user-created |
| Surfaces | MCP tool (read-only) + REST (full CRUD) |
| Scope | Silo-level, admin-only mutations |
| Federation | One-time import via REST, becomes local user skill |
| Naming | `engrammic:*` reserved, user skills use custom namespace |

## Schema

```python
class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    allowed_tools: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(20))  # "builtin" | "user"
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    silo_id: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
```

Naming convention:
- Built-in: `engrammic:<name>` (reserved prefix, immutable)
- User/org: `<namespace>:<name>` where namespace is chosen by creator
- Namespace is extracted from the name prefix (everything before the colon) for filtering

## API Surface

### MCP Tool: `context_skills`

Read-only for agents.

```python
context_skills(
    action: Literal["list", "get"],
    name: str | None = None,      # Required for get
    namespace: str | None = None, # Filter list by namespace
)
```

### REST Endpoints

Full CRUD for dashboard, admin-only mutations.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/skills` | silo member | List skills (query: `?namespace=`, `?source=`) |
| GET | `/api/skills/{name}` | silo member | Get single skill |
| POST | `/api/skills` | silo admin | Create user skill |
| PUT | `/api/skills/{name}` | silo admin | Update user skill |
| DELETE | `/api/skills/{name}` | silo admin | Delete user skill |
| POST | `/api/skills/import` | silo admin | Import from remote instance |

## SkillService

```python
class SkillService:
    def __init__(self, db: AsyncSession, skills_dir: Path):
        self._db = db
        self._builtin: dict[str, Skill] = {}
        self._load_builtin(skills_dir)

    def _load_builtin(self, skills_dir: Path) -> None:
        """Parse ./skills/**/*.md, populate self._builtin."""

    async def list(self, silo_id: str, namespace: str | None = None) -> list[Skill]:
        """Merge builtin + DB query, filter by silo_id/namespace."""

    async def get(self, silo_id: str, name: str) -> Skill | None:
        """Check builtin first, then DB."""

    async def create(self, silo_id: str, skill: SkillCreate) -> Skill:
        """Validate namespace not 'engrammic', insert to DB."""

    async def update(self, silo_id: str, name: str, skill: SkillUpdate) -> Skill:
        """403 if builtin, else update DB. Patch version auto-increments (1.0.0 -> 1.0.1)."""

    async def delete(self, silo_id: str, name: str) -> None:
        """403 if builtin, else delete from DB."""

    async def import_from(self, silo_id: str, source_url: str, name: str, token: str | None = None) -> Skill:
        """Fetch from remote instance, save as user skill."""
```

## Federation

Import copies a skill from a remote Engrammic instance:

```python
async def import_from(self, silo_id: str, source_url: str, name: str, token: str | None) -> Skill:
    # GET {source_url}/api/skills/{name}
    # Authorization: Bearer {token} if provided
    # Save locally with:
    #   - silo_id = caller's silo (ignore remote silo_id)
    #   - source = "user" (now mutable locally)
    #   - version = "1.0.0" (independent lineage)
    # Return 409 if name conflicts with existing user skill
```

No automatic sync. Re-import manually for updates.

## Auth

| Operation | Requirement |
|-----------|-------------|
| list/get | Authenticated user in silo |
| create/update/delete | `silo:admin` role |
| import | `silo:admin` role |

Built-in skills (`source=builtin`) return 403 on any mutation attempt.

## Files to Create

- `src/context_service/models/skill.py` - SQLAlchemy model
- `src/context_service/services/skills.py` - SkillService
- `src/context_service/mcp/tools/context_skills.py` - MCP tool (list/get)
- `src/context_service/api/routes/skills.py` - REST endpoints
- `alembic/versions/xxx_add_skills_table.py` - migration

## Performance

| Operation | Target |
|-----------|--------|
| list (cached builtins + DB) | < 50ms |
| get | < 20ms |
| create/update/delete | < 100ms |

Built-in skills are loaded once at startup and cached in memory.
