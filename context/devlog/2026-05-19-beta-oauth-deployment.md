# Beta OAuth Deployment - 2026-05-19

## Summary

Completed full OAuth authentication flow for beta.engrammic.ai MCP server. First successful authenticated MCP tool call via WorkOS AuthKit.

## Issues Fixed

### 1. Dynamic Client Registration (RFC 7591)

Claude Code's MCP client expects dynamic client registration. Added `/oauth/register` endpoint.

**File:** `src/context_service/api/routes/oauth.py`

```python
@router.post("/oauth/register")
async def register_client(request_body: dict | None = None) -> dict:
    client_id = f"client_{uuid.uuid4().hex[:16]}"
    return {
        "client_id": client_id,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        ...
    }
```

Also added `registration_endpoint` to OAuth metadata response.

### 2. OAuth Issuer Mismatch

Metadata was returning `api.engrammic.ai` (prod) instead of `beta.engrammic.ai`.

**Fix:** Added env var to Cloud Run:
```bash
gcloud run services update engrammic-beta-api \
  --update-env-vars="OAUTH__ISSUER=https://beta.engrammic.ai"
```

### 3. WorkOS Provider Parameter

WorkOS requires `provider="authkit"` for AuthKit flows. Was passing `None`.

**File:** `src/context_service/auth/workos_authkit.py`

```python
# Before
provider=None,  # Let WorkOS choose

# After  
provider="authkit",
```

### 4. User Model Timezone Issue

`users.created_at` and `users.last_active_at` were `TIMESTAMP WITHOUT TIME ZONE`, causing asyncpg errors when inserting timezone-aware datetimes.

**File:** `src/context_service/models/postgres/user.py`

```python
# Before
created_at: Mapped[datetime] = mapped_column(server_default=func.now())

# After
created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True), server_default=func.now()
)
```

**Migration:** `alembic/versions/0008_fix_user_datetime_tz.py`

Ran via SSH to StatefulHost (Cloud SQL is private-only):
```bash
gcloud compute ssh engrammic-beta-stateful --tunnel-through-iap --command="
  docker run --rm postgres:16-alpine psql 'postgresql://...' -c '
    ALTER TABLE users ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE 
    USING created_at AT TIME ZONE UTC;
    ALTER TABLE users ALTER COLUMN last_active_at TYPE TIMESTAMP WITH TIME ZONE 
    USING last_active_at AT TIME ZONE UTC;
  '
"
```

## Verification

Successfully stored memory via authenticated MCP:
```json
{
  "node_id": "ea8522f5-5b31-41b8-ae7d-53fe74569d6f",
  "layer": "memory",
  "silo_id": "93179d2b-c1dc-5f95-a4f4-4ce89855a88d"
}
```

## Outstanding Items

### Migration Automation

Currently migrations require manual SSH to StatefulHost. Options:
1. **Cloud Run job** (recommended) - Dedicated job runs migrations before API deploy
2. **Startup migration** - API runs alembic on boot
3. **Pulumi hook** - Post-deploy trigger

### WorkOS Redirect URIs

Needed in WorkOS Staging environment:
- `https://beta.engrammic.ai/oauth/callback`
- `http://localhost:*` (for MCP clients)

Sign-in URI should be set to: `https://beta.engrammic.ai/oauth/authorize`

## Files Changed

- `src/context_service/api/routes/oauth.py` - Dynamic client registration
- `src/context_service/auth/workos_authkit.py` - provider="authkit"
- `src/context_service/models/postgres/user.py` - Timezone-aware datetime columns
- `alembic/versions/0008_fix_user_datetime_tz.py` - Migration
- `.mcp.json` - Updated URL to beta.engrammic.ai
