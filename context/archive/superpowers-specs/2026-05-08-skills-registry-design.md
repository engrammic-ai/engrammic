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
MAX_BODY_SIZE = 64 * 1024  # 64KB limit for skill body

class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(500))  # Bounded
    body: Mapped[str] = mapped_column(Text)  # Validated to MAX_BODY_SIZE
    allowed_tools: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(20))  # "builtin" | "user"
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    silo_id: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Pydantic schemas:**

```python
class SkillCreate(BaseModel):
    name: str = Field(max_length=255, pattern=r"^[a-z0-9-]+:[a-z0-9-]+$")
    description: str = Field(max_length=500)
    body: str = Field(max_length=MAX_BODY_SIZE)
    allowed_tools: list[str] | None = None

class SkillUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=MAX_BODY_SIZE)
    allowed_tools: list[str] | None = None
    # Note: name and source are immutable after creation
```

**Naming convention:**
- Built-in: `engrammic:<name>` (reserved prefix, immutable)
- User/org: `<namespace>:<name>` where namespace is chosen by creator
- Namespace extracted from name prefix (before colon) for filtering
- Names are immutable after creation (rename = delete + create)

**Builtin skills:**
- `silo_id = "*"` (sentinel for cross-silo visibility)
- `version` read from YAML frontmatter, defaults to `"1.0.0"` if absent
- If two files declare same name, startup fails hard with error listing duplicates

## API Surface

### MCP Tool: `context_skills`

Read-only for agents.

```python
context_skills(
    action: Literal["list", "get", "search"],
    name: str | None = None,       # Required for get
    query: str | None = None,      # Required for search (matches name, description)
    namespace: str | None = None,  # Filter list/search by namespace
    limit: int = 50,               # Max results for list/search (max 200)
    offset: int = 0,               # Pagination offset
)
```

MCP returns caller's silo skills + all builtins (silo_id="*"). Uses `get_mcp_auth_context()` and `derive_silo_id()` per existing patterns.

### REST Endpoints

Full CRUD for dashboard, admin-only mutations.

**Route registration order matters:** Register `/import` before `/{name}` to avoid FastAPI path conflicts.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/skills` | silo member | List skills (query: `?namespace=`, `?source=`, `?limit=`, `?offset=`) |
| GET | `/api/skills/search` | silo member | Search skills (query: `?q=`, `?namespace=`, `?limit=`) |
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
        self._load_builtin(skills_dir)  # Raises on parse error or duplicate

    def _load_builtin(self, skills_dir: Path) -> None:
        """Parse ./skills/**/*.md, populate self._builtin.
        
        Raises StartupError if:
        - Any .md file has malformed YAML frontmatter
        - Two files declare the same skill name
        """

    async def list(
        self, silo_id: str, namespace: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Skill]:
        """Merge builtin + DB query, filter by silo_id/namespace, paginate."""

    async def search(
        self, silo_id: str, query: str, namespace: str | None = None, limit: int = 50
    ) -> list[Skill]:
        """Search skills by name/description substring match."""

    async def get(self, silo_id: str, name: str) -> Skill | None:
        """Check builtin first, then DB."""

    async def create(self, silo_id: str, skill: SkillCreate) -> Skill:
        """Validate namespace not 'engrammic', sanitize body, insert to DB."""

    async def update(self, silo_id: str, name: str, skill: SkillUpdate) -> Skill:
        """403 if builtin, else update DB.
        
        Version auto-increments patch: 1.0.0 -> 1.0.1 -> ... -> 1.0.9 -> 1.0.10
        """

    async def delete(self, silo_id: str, name: str) -> None:
        """403 if builtin, else delete from DB."""

    async def import_from(
        self, silo_id: str, source_url: str, name: str, token: str | None = None
    ) -> Skill:
        """Fetch from remote instance, save as user skill.
        
        Validates source_url, rejects engrammic:* names.
        Token is used once, not stored.
        """
```

## Federation

Import copies a skill from a remote Engrammic instance:

```python
async def import_from(self, silo_id: str, source_url: str, name: str, token: str | None) -> Skill:
    # 1. Validate source_url (see Security section)
    # 2. Reject if name starts with "engrammic:" (reserved namespace)
    # 3. GET {source_url}/api/skills/{name}
    #    Authorization: Bearer {token} if provided
    # 4. Sanitize fetched body content
    # 5. Save locally with:
    #    - silo_id = caller's silo (ignore remote silo_id)
    #    - source = "user" (now mutable locally)
    #    - version = "1.0.0" (independent lineage)
    # 6. Return 409 if name conflicts with existing skill (builtin OR user)
```

Token is used for the single fetch request and not stored. No automatic sync - re-import manually for updates.

## Auth

| Operation | Requirement |
|-----------|-------------|
| list/get/search | Authenticated user in silo |
| create/update/delete | `silo:admin` role |
| import | `silo:admin` role |

Built-in skills (`source=builtin`) return 403 on any mutation attempt.

## Security

### SSRF Prevention

`import_from` must validate `source_url` before fetching:

```python
def validate_import_url(url: str) -> None:
    """Raises ValueError if URL is not safe for federation fetch."""
    parsed = urlparse(url)
    
    # Must be HTTPS (HTTP allowed only in dev mode)
    if parsed.scheme not in ("https",):  # Add "http" for local dev
        raise ValueError("Only HTTPS URLs allowed")
    
    # Resolve hostname and check against blocked ranges
    ip = socket.gethostbyname(parsed.hostname)
    blocked = [
        ipaddress.ip_network("127.0.0.0/8"),      # Loopback
        ipaddress.ip_network("10.0.0.0/8"),       # RFC-1918
        ipaddress.ip_network("172.16.0.0/12"),    # RFC-1918
        ipaddress.ip_network("192.168.0.0/16"),   # RFC-1918
        ipaddress.ip_network("169.254.0.0/16"),   # Link-local
    ]
    if any(ipaddress.ip_address(ip) in net for net in blocked):
        raise ValueError("Internal network addresses not allowed")
```

### Body Sanitization

Skill bodies are served to agents and could contain prompt injection attempts:

```python
def sanitize_skill_body(body: str) -> str:
    """Strip control characters, normalize whitespace."""
    # Remove ASCII control chars except newline/tab
    body = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", body)
    return body.strip()
```

Applied on create, update, and import.

### Namespace Restrictions

- `engrammic:*` is reserved and rejected on create/import
- No other namespace restrictions (accepted risk: squatting on well-known names)
- Orgs wanting strict namespacing can enforce `<org-slug>:*` pattern at the application layer

## Files to Create

- `src/context_service/models/skill.py` - SQLAlchemy model + Pydantic schemas
- `src/context_service/services/skills.py` - SkillService
- `src/context_service/mcp/tools/context_skills.py` - MCP tool (list/get/search)
- `src/context_service/api/routes/skills.py` - REST endpoints
- `alembic/versions/xxx_add_skills_table.py` - migration

## Performance

| Operation | Target |
|-----------|--------|
| list (cached builtins + DB, paginated) | < 50ms |
| search | < 100ms |
| get | < 20ms |
| create/update/delete | < 100ms |

Built-in skills are loaded once at startup and cached in memory.
