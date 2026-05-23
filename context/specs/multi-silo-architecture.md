# Multi-Silo Architecture Spec

Status: **DRAFT** (deferred to post-closed-beta)
Date: 2026-05-23
Engrammic node: `9ec51915-f937-4338-a999-6d430cc92597`

## Problem

Current model: 1 silo per org via `derive_silo_id(org_id)`. All context within an org is flat with no sub-structure. `session_id` is tracked but not used for query scoping.

Gap: No way to partition context within an org for teams, projects, or workspaces. Engineers need isolation boundaries without reimplementing multi-tenancy.

## Design Principles

1. **Flat silos over hierarchy** - No imposed workspace/project structure. Engineers create silos as needed. Hierarchy can be layered later via silo groups/tags.

2. **Agent doesn't resolve workspace** - Matches industry pattern (Mem0, Zep, LangMem). Boundary injected by calling layer. Agents receive pre-scoped context and cannot query or escape their boundary.

3. **Session binds to silo** - Avoids "which silo did this go to?" ambiguity. Cross-silo is explicit opt-in.

4. **Transparent enforcement** - Tools operate on `session.default_silo_id`. No silo param on agent-facing tools.

## Architecture

### Silo Model

```
org
├── silo: backend-api
├── silo: infra
└── silo: product-roadmap
```

- Silo = opaque container, whatever boundary makes sense to the engineer
- Hard isolation - no accidental cross-silo leakage
- Each silo is self-contained (easier GDPR erasure, export, migration)

### Access Control

```sql
CREATE TABLE silo_memberships (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    silo_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',  -- member, admin, owner
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, silo_id)
);

CREATE TABLE agent_silo_restrictions (
    agent_id TEXT NOT NULL,
    silo_id TEXT NOT NULL,
    PRIMARY KEY (agent_id, silo_id)
);

CREATE INDEX idx_memberships_user ON silo_memberships(user_id);
CREATE INDEX idx_memberships_silo ON silo_memberships(silo_id);
```

- User-level membership with optional agent-level restrictions (subtractive only)
- Agents inherit user's access unless explicitly scoped down
- API keys can be org-scoped or silo-scoped

### AuthContext Evolution

```python
@dataclass
class SiloAccess:
    silo_id: str
    role: str  # member, admin, owner
    is_default: bool

@dataclass
class AuthContext:
    org_id: str
    user_id: str
    email: str | None
    is_dev: bool
    agent_id: str | None
    session_id: str | None
    db_user_id: UUID | None
    # New fields:
    accessible_silos: list[SiloAccess]
    effective_silos: list[SiloAccess]  # After agent restrictions
    default_silo_id: str
    session_silo_id: str | None  # Locked at session creation
```

### Session Binding Flow

```
Agent connects (OAuth token or API key)
       ↓
Server resolves identity (user_id, org_id)
       ↓
Server looks up silo memberships from DB
       ↓
AuthContext populated with accessible silos + default
       ↓
Session bound to default_silo_id (or X-Silo-Id if provided)
       ↓
MCP tools operate on session.silo_id transparently
```

### Sub-Silo Scoping

Decay class determines scope within silo:

| Decay Class | Scope | Use Case |
|-------------|-------|----------|
| ephemeral | session | Working memory, current task |
| standard | user within silo | Personal observations |
| durable | user within silo | Long-term personal knowledge |
| permanent | silo-wide | Shared team knowledge |

### Cross-Silo Queries

Explicit opt-in, not union by default:

```python
recall(query="...")                           # default silo only
recall(query="...", silos=["alpha", "beta"])  # explicit multi-silo
recall(query="...", silos="*")                # all accessible (slower)
```

Rationale:
- Provenance clarity - agent knows where results came from
- Performance predictability - union across N silos = N queries
- Security surface - implicit union is a data leak vector

### Harness Integration

Most harnesses (Claude Code, Cursor) use stdio transport with no HTTP headers.

Options for silo selection:
1. **Server-side default** - auth identity -> lookup default silo -> use it (works today)
2. **Env var** - harness sets `ENGRAMMIC_SILO=backend-api` in MCP config
3. **Init pattern** - agent calls `patterns(action="use_silo", silo="x")` at session start

Recommended: Server-side default for most cases, env var for explicit override.

## Industry Research

### MCP Protocol

No standard for multi-tenancy. `Mcp-Session-Id` header exists but doesn't define tenant context. Common patterns:
- Path-based routing (`/{tenant}/mcp/`)
- One instance per tenant (Cloudflare Durable Objects)
- JWT claims at gateway (Traefik Hub)

Source: `668b83bf-f13b-4ce9-8d36-5a8617dd710c`

### Agent Memory Systems

All converge on same pattern: agent doesn't resolve workspace.

| System | Scoping Model |
|--------|---------------|
| Mem0 | Composable IDs (user_id, agent_id, app_id, run_id). API key -> org |
| Zep | User -> Session hierarchy. Memory at user-graph level |
| LangMem | Namespace tuples with runtime template injection |

Source: `ee960123-3f8a-457a-baf4-d9556743c59e`

## Migration Path

1. Add `silo_memberships` table
2. Bootstrap memberships: existing users -> their org's current silo (is_default=true)
3. Extend AuthContext with new fields
4. Update `get_mcp_auth_context()` to resolve memberships
5. Add management REST API / CLI (deferred)

## Edge Cases

- **Default silo ambiguity** - Fail loudly if user has no default set
- **Silo creation permissions** - Admin-only or quota-based to prevent sprawl
- **Cross-silo links** - Must check access to both endpoints
- **Silo deletion** - Soft delete + retention period, affects GDPR erasure flow

## Management Surface (Deferred)

```bash
engrammic silo create backend-api
engrammic silo grant backend-api --user=alice@co.com --role=admin
engrammic silo set-default --user=alice@co.com --silo=backend-api
engrammic apikey create --silo=backend-api --name="CI runner"
```

REST API, CLI, optional GitOps config file. Dashboard UI later.

## References

- Reasoning chain: `99d85c7b-5534-4cc5-8307-eb6cbf4cc757`
- Design decision: `852d8339-8560-4247-85fe-2e84a819bed5`
- Industry patterns: `ee960123-3f8a-457a-baf4-d9556743c59e`
- MCP research: `668b83bf-f13b-4ce9-8d36-5a8617dd710c`
- Current multi-tenancy: `7c87262c-f7e5-46ff-ad0f-ec3ff8cfe906`
