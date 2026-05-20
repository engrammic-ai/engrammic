# MCP OAuth Implementation with WorkOS

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Enable closed beta partners to connect MCP clients (Claude Desktop, etc.) to Engrammic via OAuth 2.1 + PKCE, authenticating through WorkOS.

**Architecture:** Partners authenticate via WorkOS AuthKit, we issue our own opaque tokens stored in Postgres, tokens map to org_id/silo_id for multi-tenancy.

**Tech Stack:** Python 3.13, FastAPI, WorkOS SDK v6, SQLAlchemy, Alembic, asyncpg

---

## Context

Closed beta partners need a way to connect their MCP clients to `https://api.engrammic.ai/mcp`. Currently the MCP server requires GCP IAM auth (internal only). We need public OAuth endpoints that:
1. Let partners authenticate via WorkOS (magic link or SSO)
2. Issue tokens that MCP clients can use
3. Track connected clients per partner org
4. Enforce silo isolation via org_id mapping

---

## Architecture Flow

```
MCP Client (Claude Desktop)
       |
       | 1. GET /.well-known/oauth-authorization-server
       v
[Discovery Metadata] -> returns endpoints + PKCE support
       |
       | 2. GET /oauth/authorize?code_challenge=...&redirect_uri=localhost:PORT/callback
       v
[Engrammic] -> stores PKCE params -> redirects to WorkOS AuthKit
       |
       | 3. User authenticates with WorkOS (magic link/SSO)
       v
[WorkOS] -> redirects back to /oauth/callback?code=...
       |
       | 4. Exchange WorkOS code for session, create/lookup user
       v
[Engrammic] -> issues authorization_code -> redirects to MCP client callback
       |
       | 5. POST /oauth/token (code + code_verifier)
       v
[Engrammic] -> validates PKCE, issues access_token + refresh_token
       |
       | 6. MCP requests with Bearer access_token
       v
[Engrammic MCP Server] -> validates token -> resolves org_id/silo_id
```

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `alembic/versions/0007_add_oauth_tables.py` | Migration for OAuth tables |
| `src/context_service/models/postgres/oauth.py` | SQLAlchemy models |
| `src/context_service/services/oauth.py` | OAuth business logic |
| `src/context_service/api/routes/oauth.py` | OAuth endpoints |
| `src/context_service/auth/workos_authkit.py` | WorkOS AuthKit helpers |
| `src/context_service/mcp/server.py` | Token validation integration |
| `src/context_service/config/settings.py` | OAuthConfig additions |

---

### Task 1: Postgres Migration for OAuth Tables

**Files:**
- Create: `alembic/versions/0007_add_oauth_tables.py`

- [ ] **Step 1: Create migration file**

Three tables needed:

```python
# oauth_authorization_requests - PKCE state storage
op.create_table(
    "oauth_authorization_requests",
    sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("state", sa.String(255), nullable=False),
    sa.Column("code_challenge", sa.String(128), nullable=False),
    sa.Column("code_challenge_method", sa.String(10), server_default="S256"),
    sa.Column("redirect_uri", sa.Text, nullable=False),
    sa.Column("client_id", sa.String(255)),
    sa.Column("scope", sa.Text),
    sa.Column("workos_state", sa.String(255)),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("id"),
    sa.UniqueConstraint("state"),
)

# oauth_authorization_codes - single-use codes
op.create_table(
    "oauth_authorization_codes",
    sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("code", sa.String(255), nullable=False),
    sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("authorization_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("oauth_authorization_requests.id")),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("used_at", sa.DateTime(timezone=True)),
    sa.PrimaryKeyConstraint("id"),
    sa.UniqueConstraint("code"),
)

# oauth_tokens - access + refresh tokens
op.create_table(
    "oauth_tokens",
    sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("access_token_hash", sa.String(64), nullable=False),  # SHA256 hash
    sa.Column("refresh_token_hash", sa.String(64)),
    sa.Column("scope", sa.Text),
    sa.Column("client_id", sa.String(255)),
    sa.Column("client_name", sa.String(255)),
    sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
    sa.PrimaryKeyConstraint("id"),
)
op.create_index("ix_oauth_tokens_user_id", "oauth_tokens", ["user_id"])
op.create_index("ix_oauth_tokens_access_token_hash", "oauth_tokens", ["access_token_hash"])
op.create_index("ix_oauth_tokens_refresh_token_hash", "oauth_tokens", ["refresh_token_hash"])
```

- [ ] **Step 2: Run migration locally**

```bash
just db-migrate
```

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/0007_add_oauth_tables.py
git commit -m "feat: add OAuth tables for MCP authentication"
```

---

### Task 2: SQLAlchemy Models

**Files:**
- Create: `src/context_service/models/postgres/oauth.py`
- Modify: `src/context_service/models/postgres/__init__.py`

- [ ] **Step 1: Create OAuth models**

```python
# src/context_service/models/postgres/oauth.py
"""OAuth models for MCP client authentication."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from context_service.models.postgres.base import Base


class OAuthAuthorizationRequest(Base):
    """PKCE authorization request state."""

    __tablename__ = "oauth_authorization_requests"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default="gen_random_uuid()")
    state: Mapped[str] = mapped_column(String(255), unique=True)
    code_challenge: Mapped[str] = mapped_column(String(128))
    code_challenge_method: Mapped[str] = mapped_column(String(10), default="S256")
    redirect_uri: Mapped[str] = mapped_column(Text)
    client_id: Mapped[str | None] = mapped_column(String(255))
    scope: Mapped[str | None] = mapped_column(Text)
    workos_state: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthAuthorizationCode(Base):
    """Single-use authorization code."""

    __tablename__ = "oauth_authorization_codes"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default="gen_random_uuid()")
    code: Mapped[str] = mapped_column(String(255), unique=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    authorization_request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("oauth_authorization_requests.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthToken(Base):
    """OAuth access and refresh tokens."""

    __tablename__ = "oauth_tokens"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default="gen_random_uuid()")
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    access_token_hash: Mapped[str] = mapped_column(String(64))
    refresh_token_hash: Mapped[str | None] = mapped_column(String(64))
    scope: Mapped[str | None] = mapped_column(Text)
    client_id: Mapped[str | None] = mapped_column(String(255))
    client_name: Mapped[str | None] = mapped_column(String(255))
    access_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship("User", back_populates="oauth_tokens")
```

- [ ] **Step 2: Update __init__.py exports**

- [ ] **Step 3: Commit**

```bash
git add src/context_service/models/postgres/oauth.py src/context_service/models/postgres/__init__.py
git commit -m "feat: add OAuth SQLAlchemy models"
```

---

### Task 3: OAuth Service Layer

**Files:**
- Create: `src/context_service/services/oauth.py`

- [ ] **Step 1: Create OAuthService class**

Key methods:
- `create_authorization_request()` - Store PKCE state
- `get_authorization_request(state)` - Retrieve by state
- `create_authorization_code(user_id, request_id)` - Create single-use code
- `exchange_code_for_tokens(code, code_verifier)` - Validate PKCE, issue tokens
- `refresh_access_token(refresh_token)` - Issue new access token
- `validate_access_token(access_token)` - Check token validity
- `revoke_token(token)` - Revoke access or refresh token
- `list_user_tokens(user_id)` - List active tokens for user

Helper functions:
- `_hash_token(token)` - SHA256 hash for storage
- `_verify_pkce(code_verifier, code_challenge)` - S256 verification
- `_generate_token()` - Cryptographically secure token generation

- [ ] **Step 2: Commit**

```bash
git add src/context_service/services/oauth.py
git commit -m "feat: add OAuth service layer"
```

---

### Task 4: WorkOS AuthKit Integration

**Files:**
- Create: `src/context_service/auth/workos_authkit.py`

- [ ] **Step 1: Create AuthKit helpers**

```python
async def get_authorization_url(redirect_uri: str, state: str) -> str:
    """Generate WorkOS AuthKit authorization URL."""

async def exchange_code_for_user(code: str) -> dict:
    """Exchange WorkOS code for user info. Returns {id, email, organization_id}."""
```

Follow pattern from existing `workos_client.py`.

- [ ] **Step 2: Commit**

```bash
git add src/context_service/auth/workos_authkit.py
git commit -m "feat: add WorkOS AuthKit integration"
```

---

### Task 5: OAuth Routes

**Files:**
- Create: `src/context_service/api/routes/oauth.py`

- [ ] **Step 1: Create OAuth endpoints**

```python
router = APIRouter(tags=["oauth"])

@router.get("/.well-known/oauth-authorization-server")
async def oauth_metadata() -> dict:
    """RFC 8414 OAuth metadata."""
    return {
        "issuer": settings.oauth_issuer,
        "authorization_endpoint": f"{settings.oauth_issuer}/oauth/authorize",
        "token_endpoint": f"{settings.oauth_issuer}/oauth/token",
        "revocation_endpoint": f"{settings.oauth_issuer}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["read", "write"],
    }

@router.get("/oauth/authorize")
async def authorize(...) -> RedirectResponse:
    """Start OAuth flow, redirect to WorkOS."""

@router.get("/oauth/callback")
async def callback(...) -> RedirectResponse:
    """Handle WorkOS callback, redirect to MCP client."""

@router.post("/oauth/token")
async def token(...) -> dict:
    """Exchange code for tokens or refresh tokens."""

@router.post("/oauth/revoke")
async def revoke(...) -> Response:
    """Revoke token (RFC 7009)."""
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/api/routes/oauth.py
git commit -m "feat: add OAuth routes for MCP authentication"
```

---

### Task 6: Register Routes in App

**Files:**
- Modify: `src/context_service/api/app.py`

- [ ] **Step 1: Include OAuth router**

```python
from context_service.api.routes import oauth

# In create_app():
app.include_router(oauth.router)
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/api/app.py
git commit -m "feat: register OAuth routes in FastAPI app"
```

---

### Task 7: Token Validation in MCP Server

**Files:**
- Modify: `src/context_service/mcp/server.py`

- [ ] **Step 1: Add OAuth token resolution path**

Update `get_mcp_auth_context()`:

```python
async def get_mcp_auth_context() -> AuthContext:
    headers = get_http_headers(...)
    auth_header = headers.get("authorization")
    
    if auth_header:
        token = auth_header.removeprefix("Bearer ").strip()
        
        # Try OAuth token first (our issued tokens)
        oauth_context = await _resolve_oauth_token(token)
        if oauth_context:
            return oauth_context
        
        # Fall back to WorkOS sealed session (existing path)
        return await resolve_mcp_auth_from_header(auth_header)
    
    # Dev mode fallback (existing)
    ...
```

- [ ] **Step 2: Add _resolve_oauth_token helper**

```python
async def _resolve_oauth_token(token: str) -> AuthContext | None:
    """Resolve auth context from our OAuth token."""
    async with get_session() as session:
        oauth_svc = OAuthService(session)
        oauth_token = await oauth_svc.validate_access_token(token)
        if not oauth_token:
            return None
        
        user = await session.get(User, oauth_token.user_id)
        return AuthContext(
            org_id=user.org_id,
            user_id=user.workos_user_id,
            email=user.email,
            is_dev=False,
            db_user_id=user.id,
        )
```

- [ ] **Step 3: Commit**

```bash
git add src/context_service/mcp/server.py
git commit -m "feat: add OAuth token validation to MCP auth"
```

---

### Task 8: Configuration Updates

**Files:**
- Modify: `src/context_service/config/settings.py`

- [ ] **Step 1: Add OAuthConfig**

```python
class OAuthConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    
    issuer: str = "https://api.engrammic.ai"
    access_token_ttl_seconds: int = 3600  # 1 hour
    refresh_token_ttl_days: int = 90
    authorization_code_ttl_seconds: int = 600  # 10 minutes
    allowed_redirect_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"]
    )
```

- [ ] **Step 2: Add to Settings class**

```python
oauth: OAuthConfig = Field(default_factory=OAuthConfig)
```

- [ ] **Step 3: Commit**

```bash
git add src/context_service/config/settings.py
git commit -m "feat: add OAuth configuration"
```

---

### Task 9: Integration Tests

**Files:**
- Create: `tests/integration/test_oauth.py`

- [ ] **Step 1: Create test cases**

- Test OAuth metadata endpoint
- Test authorization flow (mock WorkOS)
- Test token exchange with PKCE
- Test token refresh
- Test token revocation
- Test MCP auth with OAuth token

- [ ] **Step 2: Commit**

```bash
git add tests/integration/test_oauth.py
git commit -m "test: add OAuth integration tests"
```

---

### Task 10: Final Verification

- [ ] **Step 1: Run linting**

```bash
just check
```

- [ ] **Step 2: Run tests**

```bash
just test tests/integration/test_oauth.py
```

- [ ] **Step 3: Test with Claude Desktop**

1. Configure Claude Desktop to connect to beta MCP URL
2. Verify OAuth flow redirects to WorkOS
3. Verify token issuance and MCP tool access

---

## Security Considerations

1. **PKCE Enforcement**: Always require S256, reject plain
2. **Redirect URI Validation**: Only allow localhost for MCP clients
3. **Token Storage**: Store SHA256 hashes, not raw tokens
4. **Constant-Time Comparison**: Use `secrets.compare_digest`
5. **Rate Limiting**: Apply to `/oauth/token` endpoint
6. **HTTPS Only**: Enforce in production (except localhost callbacks)

---

## Environment Variables

```bash
# Existing (already configured)
WORKOS_API_KEY=...
WORKOS_CLIENT_ID=...
WORKOS_COOKIE_PASSWORD=...

# New
OAUTH_ISSUER=https://api.engrammic.ai
OAUTH_ACCESS_TOKEN_TTL=3600
OAUTH_REFRESH_TOKEN_TTL_DAYS=90
```

---

## Post-Implementation

1. **WorkOS Dashboard**: Configure redirect URI for AuthKit
2. **Partner Onboarding**: Create WorkOS orgs for beta partners
3. **Documentation**: Add MCP OAuth connection guide
4. **Monitoring**: Add metrics for OAuth token issuance/validation
