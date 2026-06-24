# WorkOS Auth Completion Design

**Date:** 2026-05-17
**Status:** Approved
**Author:** Claude + User
**Reviewed:** Opus subagent

## Summary

Complete WorkOS integration for invite-based demo: add User model for profile tracking, ToolUsage model for usage metrics, and wire into existing auth flow.

## Context

WorkOS sealed-session auth is already working (SDK v6). Missing pieces for demo:
- No persistent User record (can't track who signed up, last active)
- No usage metrics (can't see which tools users invoke)

Demo requirements:
- Magic link invites via WorkOS (already works)
- Basic user profile (email, name, joined, last active)
- Usage tracking (which MCP tools, how often)
- Each user = own org = own silo (already supported)

## Design

### Data Model

**User table** (`models/postgres/user.py`):

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workos_user_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    org_id: Mapped[str] = mapped_column(String(255), index=True)
    silo_id: Mapped[str] = mapped_column(String(255), index=True)  # Derived from org_id, stored for query convenience
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
```

**ToolUsage table** (`models/postgres/usage.py`):

```python
class ToolUsage(Base):
    __tablename__ = "tool_usage"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    silo_id: Mapped[str] = mapped_column(String(255), index=True)
    tool_name: Mapped[str] = mapped_column(String(100))  # Verb name from mcp_tools.yaml (e.g., "remember", "recall")
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
```

**ToolUsageSummary** (`services/usage.py`):

```python
@dataclass
class ToolUsageSummary:
    tool_name: str
    count: int
    last_used: datetime
```

**Indexes (explicit in migration):**
- `users.workos_user_id` (unique)
- `users.org_id`
- `users.silo_id`
- `tool_usage(user_id, called_at)` - composite for per-user queries
- `tool_usage(silo_id, called_at)` - composite for per-silo queries

### Auth Flow Enhancement

**Current:**
```
Magic Link -> verify_session() -> AuthContext(org_id, user_id, email)
```

**Enhanced:**
```
Magic Link -> verify_session() -> upsert_user() -> AuthContext(org_id, user_id, email, db_user_id)
```

**AuthContext changes** (`auth/context.py`):

```python
@dataclass
class AuthContext:
    org_id: str
    user_id: str          # WorkOS user ID
    email: str | None
    is_dev: bool
    agent_id: str | None
    session_id: str
    db_user_id: UUID | None  # Postgres User.id; None means dev mode OR Postgres unavailable
```

Note: `db_user_id = None` means either:
1. Dev mode (`AUTH_ENABLED=false`)
2. Postgres unavailable during auth (fail-open for demo; auth succeeds, user tracking skipped)

**Error handling:** If Postgres is unavailable during `upsert_user()`, log warning and continue with `db_user_id=None`. Auth should not fail due to user tracking failure. This is acceptable for demo scope.

**User upsert** (`services/user.py`):

```python
class UserService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def upsert_user(
        self,
        workos_user_id: str,
        org_id: str,
        silo_id: str,
        email: str,
        name: str | None = None
    ) -> User:
        """Create user if not exists, always update last_active_at."""
```

**Database session:** Services receive `AsyncSession` via constructor injection. The auth path obtains a session from `get_session()` context manager (existing pattern in codebase).

Called from `auth/workos_client.py` after successful `verify_session()`.

### Usage Tracking

**Hook location:** MCP tool dispatch in `mcp/server.py`

**Tool name convention:** Use verb names from `mcp_tools.yaml` (e.g., `remember`, `recall`, `learn`), not internal names (`context_remember`). This matches the agent-facing surface.

**Implementation:**
```python
async def track_tool_usage(auth: AuthContext, tool_name: str):
    if auth.db_user_id is None:
        return  # Dev mode or Postgres unavailable, skip tracking
    asyncio.create_task(_record_usage(auth.db_user_id, derive_silo_id(auth.org_id), tool_name))

async def _record_usage(user_id: UUID, silo_id: str, tool_name: str):
    try:
        async with get_session() as session:
            usage_service = UsageService(session)
            await usage_service.record_usage(user_id, silo_id, tool_name)
    except Exception as e:
        log.warning("usage_tracking_failed", error=str(e))
```

Fire-and-forget to avoid blocking tool execution. Errors swallowed and logged.

**Usage service** (`services/usage.py`):

```python
class UsageService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def record_usage(self, user_id: UUID, silo_id: str, tool_name: str) -> None:
        """Insert ToolUsage row."""

    async def get_user_usage(self, user_id: UUID, since: datetime | None = None) -> list[ToolUsageSummary]:
        """Aggregate usage by tool for a user."""

    async def get_silo_usage(self, silo_id: str, since: datetime | None = None) -> list[ToolUsageSummary]:
        """Aggregate usage by tool for a silo."""
```

### Retention (Disabled by Default)

**Dagster job:** `pipelines/jobs/usage_retention.py`

Deletes ToolUsage rows older than configured retention period.

**Config** (`config/settings.yaml`):

```yaml
usage:
  retention_enabled: false  # Enable manually when needed
  retention_days: 90
```

Job exists but schedule not registered unless `retention_enabled: true`. For demo, manual cleanup via SQL is sufficient if table grows large.

## File Changes

| File | Change |
|------|--------|
| `models/postgres/user.py` | New: User model |
| `models/postgres/usage.py` | New: ToolUsage model, ToolUsageSummary dataclass |
| `models/postgres/__init__.py` | Export new models |
| `alembic/versions/xxx_add_user_usage.py` | Migration with explicit composite indexes |
| `auth/context.py` | Add db_user_id field |
| `auth/workos_client.py` | Call upsert_user after verify (fail-open on error) |
| `services/user.py` | New: UserService |
| `services/usage.py` | New: UsageService |
| `mcp/server.py` | Add usage tracking hook |
| `pipelines/jobs/usage_retention.py` | New: retention job (disabled by default) |
| `pipelines/jobs/__init__.py` | Export job |
| `config/settings.yaml` | Add usage config section |
| `tests/services/test_user.py` | New: user service tests |
| `tests/services/test_usage.py` | New: usage service tests |
| `tests/integration/test_auth_user_sync.py` | New: auth+user integration |

## Out of Scope

- OAuth login flow (`/auth/callback`) - WorkOS hosted UI handles magic links
- RBAC / roles - not needed for demo
- Session table / revocation - overkill for current phase
- Full audit logging - usage table covers demo needs
- Duration tracking - can add later if needed
- User metadata JSONB - add when there's a use case

## Testing

1. **User service:** upsert creates new, updates existing, refreshes last_active_at
2. **Usage service:** record inserts, aggregation queries return correct ToolUsageSummary
3. **Auth integration:** verify_session upserts user, AuthContext has db_user_id
4. **Auth fail-open:** Postgres down during auth -> auth succeeds, db_user_id=None
5. **Usage tracking:** tool calls create ToolUsage rows with verb names (integration test)
6. **Retention job:** deletes old rows when enabled (unit test)

## Rollout

1. Run migration
2. Deploy with usage tracking enabled
3. Verify users created on auth
4. Verify tool usage rows appearing with correct verb names
5. Query usage data via Postgres or build simple admin endpoint later
