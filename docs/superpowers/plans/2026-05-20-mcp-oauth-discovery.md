# MCP Dual Auth (API Key + OAuth) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support both API key and OAuth authentication for MCP clients. API keys for simplicity (teammates, CI), OAuth for users who prefer browser login.

**Architecture:** Try API key lookup first, fall back to OAuth token verification. Add RFC 9728 protected resource metadata for OAuth discovery. Support token revocation for logout.

**Tech Stack:** FastAPI, PostgreSQL (API keys table), RFC 9728, RFC 8414

---

### Task 1: Create API Keys Table

**Files:**
- Create: `src/context_service/models/postgres/api_key.py`
- Modify: `src/context_service/models/postgres/__init__.py`
- Create: `alembic/versions/xxxx_add_api_keys_table.py`

- [ ] **Step 1: Create the model**

```python
# src/context_service/models/postgres/api_key.py
"""API key model for MCP authentication."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.models.postgres.base import Base


class APIKey(Base):
    """API key for MCP authentication.
    
    Keys are hashed (SHA-256) before storage. The plaintext is shown
    once at creation and never stored.
    """

    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # SHA-256 hex
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g. "Cursor", "CI"
    scopes: Mapped[str] = mapped_column(String(255), default="read write")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 2: Export from __init__.py**

Add to `src/context_service/models/postgres/__init__.py`:

```python
from context_service.models.postgres.api_key import APIKey

__all__ = [..., "APIKey"]
```

- [ ] **Step 3: Create migration**

```bash
uv run alembic revision --autogenerate -m "add api_keys table"
```

- [ ] **Step 4: Run migration**

```bash
uv run just db-migrate
```

- [ ] **Step 5: Commit**

```bash
git add src/context_service/models/postgres/api_key.py src/context_service/models/postgres/__init__.py alembic/versions/
git commit -m "feat(auth): add API keys table"
```

---

### Task 2: API Key Service

**Files:**
- Create: `src/context_service/services/api_key.py`
- Test: `tests/services/test_api_key.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/services/test_api_key.py
"""Tests for API key service."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from context_service.services.api_key import APIKeyService


@pytest.mark.asyncio
async def test_create_and_verify_api_key(db_session: AsyncSession, test_user) -> None:
    """Test API key creation and verification."""
    svc = APIKeyService(db_session)
    
    # Create key - returns plaintext once
    plaintext, api_key = await svc.create_key(
        user_id=test_user.id,
        name="Test Key",
    )
    
    assert plaintext.startswith("eng_")
    assert len(plaintext) == 36  # eng_ + 32 hex chars
    assert api_key.name == "Test Key"
    
    # Verify key
    result = await svc.verify_key(plaintext)
    assert result is not None
    assert result.user_id == test_user.id


@pytest.mark.asyncio
async def test_revoked_key_fails_verification(db_session: AsyncSession, test_user) -> None:
    """Test that revoked keys fail verification."""
    svc = APIKeyService(db_session)
    
    plaintext, api_key = await svc.create_key(user_id=test_user.id, name="Test")
    await svc.revoke_key(api_key.id)
    
    result = await svc.verify_key(plaintext)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_api_key.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the service**

```python
# src/context_service/services/api_key.py
"""API key management service."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from context_service.models.postgres.api_key import APIKey


class APIKeyService:
    """Service for creating and verifying API keys."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_key(
        self,
        user_id: UUID,
        name: str,
        scopes: str = "read write",
        expires_at: datetime | None = None,
    ) -> tuple[str, APIKey]:
        """Create a new API key.
        
        Returns (plaintext_key, api_key_record). The plaintext is only
        available at creation time - store it securely.
        """
        # Generate key: eng_ prefix + 32 random hex chars
        raw = secrets.token_hex(16)
        plaintext = f"eng_{raw}"
        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()

        api_key = APIKey(
            user_id=user_id,
            key_hash=key_hash,
            name=name,
            scopes=scopes,
            expires_at=expires_at,
        )
        self._session.add(api_key)
        await self._session.flush()
        return plaintext, api_key

    async def verify_key(self, plaintext: str) -> APIKey | None:
        """Verify an API key and return the record if valid.
        
        Returns None if key is invalid, revoked, or expired.
        """
        if not plaintext.startswith("eng_"):
            return None

        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        now = datetime.now(timezone.utc)

        stmt = select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.revoked_at.is_(None),
        )
        result = await self._session.execute(stmt)
        api_key = result.scalar_one_or_none()

        if api_key is None:
            return None

        # Check expiry
        if api_key.expires_at and api_key.expires_at < now:
            return None

        # Update last_used_at
        await self._session.execute(
            update(APIKey)
            .where(APIKey.id == api_key.id)
            .values(last_used_at=now)
        )

        return api_key

    async def revoke_key(self, key_id: UUID) -> bool:
        """Revoke an API key. Returns True if key existed."""
        result = await self._session.execute(
            update(APIKey)
            .where(APIKey.id == key_id, APIKey.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        return result.rowcount > 0

    async def list_keys(self, user_id: UUID) -> list[APIKey]:
        """List all non-revoked keys for a user."""
        stmt = select(APIKey).where(
            APIKey.user_id == user_id,
            APIKey.revoked_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/services/test_api_key.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/services/api_key.py tests/services/test_api_key.py
git commit -m "feat(auth): add API key service"
```

---

### Task 3: Dual Auth in MCP Server

**Files:**
- Modify: `src/context_service/mcp/server.py`
- Test: `tests/mcp/test_dual_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/test_dual_auth.py
"""Tests for dual auth (API key + OAuth) in MCP server."""

import pytest


@pytest.mark.asyncio
async def test_api_key_auth_accepted(client, test_api_key) -> None:
    """Test that API key auth works for MCP."""
    response = await client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {test_api_key}"},
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )
    # Should not be 401
    assert response.status_code != 401


@pytest.mark.asyncio
async def test_oauth_token_auth_accepted(client, test_oauth_token) -> None:
    """Test that OAuth token auth works for MCP."""
    response = await client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {test_oauth_token}"},
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )
    assert response.status_code != 401
```

- [ ] **Step 2: Update get_mcp_auth_context to try API key first**

In `src/context_service/mcp/server.py`, modify `get_mcp_auth_context()`:

```python
async def get_mcp_auth_context() -> AuthContext:
    """Resolve authentication from HTTP headers.
    
    Tries in order:
    1. API key (Bearer eng_xxx) - lookup in DB
    2. OAuth token (Bearer xxx) - verify via token store
    3. Dev mode fallback (if auth_enabled=false)
    """
    from fastmcp.server.dependencies import get_http_headers

    from context_service.config.settings import get_settings
    from context_service.mcp.auth import MCPAuthError

    headers = get_http_headers()
    auth_header = headers.get("authorization")
    settings = get_settings()

    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:]  # Strip "Bearer "
        
        # Try API key first (starts with eng_)
        if token.startswith("eng_"):
            auth = await _resolve_api_key_auth(token)
            if auth:
                return auth
            if settings.auth_enabled:
                raise MCPAuthError("Invalid API key")
        
        # Try OAuth token
        auth = await _resolve_oauth_auth(token, headers)
        if auth:
            return auth
        
        if settings.auth_enabled:
            raise MCPAuthError("Invalid or expired token")

    # No auth header
    if settings.auth_enabled:
        raise MCPAuthError("Missing Authorization header")
    
    # Dev mode fallback
    return _dev_auth_context(headers, settings)


async def _resolve_api_key_auth(token: str) -> AuthContext | None:
    """Resolve auth context from API key."""
    from context_service.db.postgres import get_session
    from context_service.services.api_key import APIKeyService
    from context_service.services.user import UserService

    try:
        async with get_session() as session:
            api_key_svc = APIKeyService(session)
            api_key = await api_key_svc.verify_key(token)
            if api_key is None:
                return None

            user_svc = UserService(session)
            user = await user_svc.get_user(api_key.user_id)
            if user is None:
                return None

            return AuthContext(
                org_id=user.org_id,
                user_id=user.workos_user_id,
                email=user.email,
                is_dev=False,
                agent_id=f"apikey:{api_key.id}",
                session_id=None,
                db_user_id=user.id,
            )
    except Exception:
        return None
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/mcp/test_dual_auth.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/server.py tests/mcp/test_dual_auth.py
git commit -m "feat(mcp): support dual auth (API key + OAuth)"
```

---

### Task 4: Protected Resource Metadata Endpoint

**Files:**
- Modify: `src/context_service/api/routes/oauth.py`
- Test: `tests/api/routes/test_oauth.py`

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/api/routes/test_oauth.py

@pytest.mark.asyncio
async def test_protected_resource_metadata(client: AsyncClient) -> None:
    """Test RFC 9728 protected resource metadata endpoint."""
    response = await client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    
    data = response.json()
    assert "resource" in data
    assert "authorization_servers" in data
    assert len(data["authorization_servers"]) >= 1
```

- [ ] **Step 2: Add the endpoint**

Add to `src/context_service/api/routes/oauth.py`:

```python
@router.get(
    "/.well-known/oauth-protected-resource",
    operation_id="protected_resource_metadata",
    summary="RFC 9728 OAuth protected resource metadata",
)
async def protected_resource_metadata() -> dict[str, str | list[str]]:
    """Return OAuth 2.0 protected resource metadata per RFC 9728.
    
    Tells MCP clients where to find the authorization server.
    """
    settings = get_settings()
    issuer = settings.oauth.issuer
    return {
        "resource": f"{issuer}/mcp",
        "authorization_servers": [issuer],
        "scopes_supported": ["read", "write"],
        "bearer_methods_supported": ["header"],
    }
```

- [ ] **Step 3: Run test**

Run: `uv run pytest tests/api/routes/test_oauth.py::test_protected_resource_metadata -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/api/routes/oauth.py tests/api/routes/test_oauth.py
git commit -m "feat(oauth): add RFC 9728 protected resource metadata"
```

---

### Task 5: WWW-Authenticate Header on 401

**Files:**
- Modify: `src/context_service/mcp/auth.py`

- [ ] **Step 1: Update 401 response**

In `src/context_service/mcp/auth.py`, update the `MCPAuthMiddleware.__call__` exception handler:

```python
except ValueError as e:
    logger.warning("MCP auth failed", error=str(e))
    # Build resource_metadata URL for OAuth discovery
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    resource_metadata_url = f"{scheme}://{host}/.well-known/oauth-protected-resource"
    
    return JSONResponse(
        status_code=401,
        content={"error": str(e)},
        headers={
            "WWW-Authenticate": f'Bearer resource_metadata="{resource_metadata_url}"',
        },
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/mcp/auth.py
git commit -m "feat(mcp): add WWW-Authenticate header for OAuth discovery"
```

---

### Task 6: API Key Admin Endpoints

**Files:**
- Create: `src/context_service/api/routes/api_keys.py`
- Modify: `src/context_service/api/app.py`

- [ ] **Step 1: Create admin endpoints**

```python
# src/context_service/api/routes/api_keys.py
"""API key management endpoints."""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from context_service.api.deps import get_current_user
from context_service.db.postgres import get_session
from context_service.models.postgres.user import User
from context_service.services.api_key import APIKeyService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class CreateKeyRequest(BaseModel):
    name: str


class CreateKeyResponse(BaseModel):
    key: str  # Plaintext, shown once
    id: UUID
    name: str


class KeyInfo(BaseModel):
    id: UUID
    name: str
    created_at: str
    last_used_at: str | None


@router.post("", response_model=CreateKeyResponse)
async def create_api_key(
    request: CreateKeyRequest,
    current_user: User = Depends(get_current_user),
) -> CreateKeyResponse:
    """Create a new API key. The key is shown once - save it securely."""
    async with get_session() as session:
        svc = APIKeyService(session)
        plaintext, api_key = await svc.create_key(
            user_id=current_user.id,
            name=request.name,
        )
        await session.commit()
        
    return CreateKeyResponse(
        key=plaintext,
        id=api_key.id,
        name=api_key.name,
    )


@router.get("", response_model=list[KeyInfo])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
) -> list[KeyInfo]:
    """List your API keys (without the secret)."""
    async with get_session() as session:
        svc = APIKeyService(session)
        keys = await svc.list_keys(current_user.id)
        
    return [
        KeyInfo(
            id=k.id,
            name=k.name,
            created_at=k.created_at.isoformat(),
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
        )
        for k in keys
    ]


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Revoke an API key."""
    async with get_session() as session:
        svc = APIKeyService(session)
        # Verify ownership
        keys = await svc.list_keys(current_user.id)
        if not any(k.id == key_id for k in keys):
            raise HTTPException(status_code=404, detail="Key not found")
        
        await svc.revoke_key(key_id)
        await session.commit()
        
    return {"status": "revoked"}
```

- [ ] **Step 2: Register router**

Add to `src/context_service/api/app.py`:

```python
from context_service.api.routes.api_keys import router as api_keys_router

app.include_router(api_keys_router)
```

- [ ] **Step 3: Commit**

```bash
git add src/context_service/api/routes/api_keys.py src/context_service/api/app.py
git commit -m "feat(api): add API key management endpoints"
```

---

### Task 7: Update Cursor Config

**Files:**
- Modify: `../cursor/.cursor/mcp.json`
- Modify: `../cursor/README.md`

- [ ] **Step 1: Simplify config for OAuth discovery**

```json
{
  "mcpServers": {
    "engrammic": {
      "url": "https://beta.engrammic.ai/mcp"
    }
  }
}
```

- [ ] **Step 2: Add API key alternative to README**

Add to `../cursor/README.md`:

```markdown
## Authentication Options

### Option 1: Browser Login (OAuth)
Just open Cursor and use a tool - you'll be prompted to login via browser.

### Option 2: API Key
1. Get an API key from the Engrammic dashboard
2. Set environment variable: `export ENGRAMMIC_API_KEY=eng_xxx`
3. Update `.cursor/mcp.json`:
   ```json
   {
     "mcpServers": {
       "engrammic": {
         "url": "https://beta.engrammic.ai/mcp",
         "headers": {
           "Authorization": "Bearer ${env:ENGRAMMIC_API_KEY}"
         }
       }
     }
   }
   ```
```

- [ ] **Step 3: Commit and push**

```bash
cd ../cursor
git add .cursor/mcp.json README.md
git commit -m "docs: add dual auth options (OAuth + API key)"
git push
```

---

### Task 8: Verify End-to-End

- [ ] **Step 1: Run checks**

```bash
uv run just check
```

- [ ] **Step 2: Run tests**

```bash
uv run just test
```

- [ ] **Step 3: Manual verification**

1. Start dev server with `auth_enabled=true`
2. Test OAuth discovery:
   ```bash
   curl http://localhost:8000/.well-known/oauth-protected-resource
   ```
3. Test 401 with WWW-Authenticate:
   ```bash
   curl -i http://localhost:8000/mcp
   ```
4. Test API key auth (after creating a key)

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(auth): complete dual auth (API key + OAuth) for MCP"
```
