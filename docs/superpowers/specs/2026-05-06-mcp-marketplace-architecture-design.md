# MCP Marketplace Architecture

Split architecture for Engrammic MCP marketplace release: public thin client, private cloud backend, optional OSS self-host.

## Overview

Three repositories serve different purposes:

| Repo                        | Visibility | Purpose                                    |
| --------------------------- | ---------- | ------------------------------------------ |
| delta-prime/mcp-client      | Public     | Marketplace listing, thin proxy to backend |
| delta-prime/engine          | Public     | OSS self-host backend (deferred)           |
| delta-prime/context-service | Private    | Full cloud backend                         |

## Architecture

```
┌─────────────────────────────┐
│  Agent (Claude, Cursor...)  │
└─────────────┬───────────────┘
              │ MCP protocol
              ▼
┌─────────────────────────────┐
│  delta-prime/mcp-client     │  Public repo, marketplace
│  - MCP server (FastMCP)     │
│  - HTTP client to backend   │
│  - OAuth + API key auth     │
└─────────────┬───────────────┘
              │ HTTPS
              ▼
┌─────────────────────────────┐
│  context-service OR engine  │  Cloud or self-host
│  - REST API surface         │
│  - Auth validation          │
│  - Tenant isolation         │
│  - Storage layer            │
└─────────────────────────────┘
```

## mcp-client Repository

### Structure

```
delta-prime/mcp-client/
├── src/
│   └── delta_prime_mcp/
│       ├── __init__.py
│       ├── __main__.py          # Entry: python -m delta_prime_mcp
│       ├── server.py            # FastMCP server, registers tools
│       ├── client.py            # HTTP client to backend
│       ├── auth.py              # OAuth flow + API key handling
│       ├── credentials.py       # Secure credential storage
│       ├── config.py            # Settings from .env
│       ├── errors.py            # Error sanitization
│       └── tools/
│           ├── context_store.py
│           ├── context_recall.py
│           ├── context_link.py
│           └── context_admin.py
├── .env.example
├── pyproject.toml
├── README.md
└── LICENSE
```

### Configuration

Environment variables (prefix `DELTA_PRIME_`):

```
DELTA_PRIME_BACKEND_URL=https://api.deltaprime.ai
DELTA_PRIME_API_KEY=dp_xxx
```

Settings model:

```python
class Settings(BaseSettings):
    backend_url: str = "https://api.deltaprime.ai"
    api_key: str | None = None
    credentials_path: Path = Path.home() / ".delta-prime" / "credentials.json"

    model_config = SettingsConfigDict(env_prefix="DELTA_PRIME_")
```

### Credential Storage

OAuth tokens are stored securely:

```python
# credentials.py

def store_credentials(token: str, refresh_token: str) -> None:
    """Store OAuth credentials securely."""
    creds_path = get_credentials_path()
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    
    creds_path.write_text(json.dumps({
        "access_token": token,
        "refresh_token": refresh_token,
        "stored_at": datetime.utcnow().isoformat(),
    }))
    
    # Restrict file permissions (owner read/write only)
    creds_path.chmod(0o600)

def load_credentials() -> dict | None:
    """Load stored credentials, return None if missing or unreadable."""
    creds_path = get_credentials_path()
    if not creds_path.exists():
        return None
    
    # Verify permissions before reading
    if creds_path.stat().st_mode & 0o077:
        logger.warning("Credentials file has insecure permissions, refusing to read")
        return None
    
    return json.loads(creds_path.read_text())
```

Future: consider OS keychain integration via `keyring` library for additional protection.

### Tool Implementation

Each tool is a thin pass-through:

```python
async def context_store(
    intent: Literal["remember", "assert", "commit", "reflect"],
    content: str,
    tags: list[str] | None = None,
    ...
) -> dict[str, Any]:
    client = get_client()
    return await client.post("/v1/context/store", {
        "intent": intent,
        "content": content,
        "tags": tags,
        ...
    })
```

### HTTP Client

The client uses a singleton `httpx.AsyncClient` for connection pooling and handles token refresh:

```python
# client.py

_client: httpx.AsyncClient | None = None

def get_http_client() -> httpx.AsyncClient:
    """Return singleton HTTP client for connection reuse."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=30.0,
            http2=True,
        )
    return _client

class DeltaPrimeClient:
    def __init__(self, settings: Settings):
        self.base_url = settings.backend_url
        self.settings = settings
        self._token: str | None = settings.api_key
        self._refresh_token: str | None = None
        
        if not self._token:
            self._load_oauth_credentials()

    def _load_oauth_credentials(self) -> None:
        creds = load_credentials()
        if creds:
            self._token = creds.get("access_token")
            self._refresh_token = creds.get("refresh_token")
    
    async def post(self, path: str, data: dict) -> dict:
        return await self._request("POST", path, data)
    
    async def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        client = get_http_client()
        request_id = str(uuid.uuid4())
        
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Request-ID": request_id,
        }
        
        resp = await client.request(
            method,
            f"{self.base_url}{path}",
            json=data,
            headers=headers,
        )
        
        # Retry once on 401 with token refresh
        if resp.status_code == 401 and self._refresh_token:
            if await self._refresh_access_token():
                headers["Authorization"] = f"Bearer {self._token}"
                resp = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=data,
                    headers=headers,
                )
        
        return self._handle_response(resp, request_id)
    
    async def _refresh_access_token(self) -> bool:
        """Attempt to refresh the access token. Returns True on success."""
        try:
            client = get_http_client()
            resp = await client.post(
                f"{self.base_url}/v1/auth/token/refresh",
                json={"refresh_token": self._refresh_token},
            )
            if resp.status_code == 200:
                data = resp.json()
                self._token = data["access_token"]
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                store_credentials(self._token, self._refresh_token)
                return True
        except Exception:
            pass
        return False
    
    def _handle_response(self, resp: httpx.Response, request_id: str) -> dict:
        """Handle response, sanitizing errors before returning to agent."""
        if resp.status_code >= 400:
            # Log full error locally for debugging
            logger.error(
                "Backend error",
                status=resp.status_code,
                request_id=request_id,
                body=resp.text[:500],
            )
            # Return sanitized error to agent
            raise DeltaPrimeError(
                code=_status_to_error_code(resp.status_code),
                message=_sanitize_error_message(resp),
                request_id=request_id,
            )
        return resp.json()
```

### Error Handling

Errors are sanitized before surfacing to agents:

```python
# errors.py

class DeltaPrimeError(Exception):
    def __init__(self, code: str, message: str, request_id: str):
        self.code = code
        self.message = message
        self.request_id = request_id
    
    def to_dict(self) -> dict:
        return {
            "error": self.code,
            "message": self.message,
            "request_id": self.request_id,
        }

def _status_to_error_code(status: int) -> str:
    return {
        400: "invalid_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        429: "rate_limited",
    }.get(status, "internal_error")

def _sanitize_error_message(resp: httpx.Response) -> str:
    """Return a safe error message, stripping internal details."""
    try:
        data = resp.json()
        if "message" in data and not _contains_internal_details(data["message"]):
            return data["message"]
    except Exception:
        pass
    
    return {
        400: "Invalid request parameters",
        401: "Authentication failed - try logging in again",
        403: "Access denied",
        404: "Resource not found",
        429: "Rate limit exceeded - please slow down",
    }.get(resp.status_code, "An unexpected error occurred")

def _contains_internal_details(msg: str) -> bool:
    """Check if message contains internal implementation details."""
    patterns = ["Traceback", "File \"", "line ", "memgraph", "qdrant", "silo_"]
    return any(p.lower() in msg.lower() for p in patterns)
```

## REST API Surface (context-service)

### Core Endpoints

Four endpoints mirroring MCP tools:

```
POST /v1/context/store
POST /v1/context/recall
POST /v1/context/link
POST /v1/context/admin
```

Implementation calls existing internal functions:

```python
@router.post("/v1/context/store")
async def store(
    req: StoreRequest,
    auth: AuthContext = Depends(get_auth),
    request_id: str = Header(alias="X-Request-ID", default_factory=lambda: str(uuid.uuid4())),
):
    return await _context_store_impl(
        intent=req.intent,
        content=req.content,
        silo_id=await resolve_silo_id(auth.org_id),
        ...
    )
```

### QoL Endpoints

```
GET  /v1/health              # Service health (see Health Contract below)
GET  /v1/status              # Detailed status (DB connections)
GET  /v1/auth/whoami         # org_id, user_id, email, plan tier
POST /v1/auth/token/refresh  # Refresh OAuth token
GET  /v1/usage               # Current period usage
GET  /v1/usage/limits        # Plan limits and quotas
```

### Request/Response Models

Same shapes as MCP tool parameters, defined as Pydantic models. OpenAPI docs generated automatically.

Example store request:

```json
{
  "intent": "remember",
  "content": "User prefers dark mode",
  "tags": ["preferences"],
  "decay_class": "persistent"
}
```

Example response:

```json
{
  "node_id": "abc123",
  "layer": "memory",
  "created_at": "2026-05-06T12:00:00Z"
}
```

### Health Contract

`/v1/health` returns service readiness for load balancer routing:

```json
{
  "status": "healthy" | "degraded" | "unhealthy",
  "checks": {
    "memgraph": "ok" | "error",
    "qdrant": "ok" | "error", 
    "redis": "ok" | "error" | "disabled"
  }
}
```

| Condition | Status | HTTP |
|-----------|--------|------|
| All checks pass | healthy | 200 |
| Redis down (non-critical) | degraded | 200 |
| Memgraph or Qdrant down | unhealthy | 503 |

`/v1/status` returns detailed diagnostics (auth required, not for load balancers).

### Rate Limiting

Rate limits are enforced at the REST layer before storage operations:

```python
@router.post("/v1/context/store")
@rate_limit(tier="org", limits={"free": 100, "pro": 1000, "enterprise": 10000})
async def store(...):
    ...
```

Enforcement uses Redis token bucket keyed by `org_id`. Rate-limited requests return:

```json
{
  "error": "rate_limited",
  "message": "Rate limit exceeded",
  "retry_after": 60
}
```

With headers:
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1715000000
Retry-After: 60
```

## Authentication

### Auth Flow

mcp-client forwards credentials, context-service validates:

```
mcp-client              context-service
    │                        │
    │  Authorization:        │
    │  Bearer <token>        │
    │  X-Request-ID: uuid    │
    │───────────────────────▶│
    │                        │  validate token
    │                        │  extract org_id
    │                        │  resolve silo_id (DB lookup)
    │                        │  check rate limit
    │                        │  enforce isolation
    │        response        │
    │◀───────────────────────│
```

### API Key Flow

1. User creates key in dashboard (tied to their org)
2. User sets `DELTA_PRIME_API_KEY` in `.env`
3. mcp-client sends `Authorization: Bearer <key>` on every request
4. context-service looks up key in DB, gets org_id, resolves silo_id

### OAuth Flow

1. User runs first MCP command (or explicit `delta-prime login`)
2. No stored token found, browser opens
3. User authenticates via WorkOS
4. Token saved to `~/.delta-prime/credentials.json` with `chmod 600`
5. Subsequent calls use stored token, auto-refresh on 401
6. context-service validates with WorkOS, extracts org_id

### Tenant Isolation

All isolation logic stays in context-service:

- Auth middleware validates token, extracts org_id
- `resolve_silo_id(org_id)` performs DB lookup (not a hash)
- silo_id is an opaque UUID stored in the `orgs` table
- All queries scoped to silo_id
- mcp-client never sees or interprets tenant data

**Current policy: 1:1 org-to-silo.** Each organization gets exactly one silo. Multi-silo support is deferred.

The silo_id derivation is a database lookup, not a deterministic transform:

```python
async def resolve_silo_id(org_id: str) -> str:
    """Lookup silo_id for org. Raises if org not found."""
    row = await db.fetchone(
        "SELECT silo_id FROM orgs WHERE org_id = $1",
        org_id,
    )
    if not row:
        raise AuthError("Organization not found")
    return row["silo_id"]
```

This prevents enumeration attacks since silo_id cannot be derived from org_id without database access. The DB lookup also allows future multi-silo support without API changes (mcp-client stays unchanged).

## OSS Engine (Deferred)

delta-prime/engine implements the same REST surface with minimal dependencies:

- SQLite or embedded graph for storage
- No auth (local single-tenant)
- No signals, clustering, or custodian

### Feature Split

| OSS (free self-host) | Cloud-only                      |
| -------------------- | ------------------------------- |
| Basic store/recall   | Semantic search (embeddings)    |
| Simple graph         | Custodian/consensus promotion   |
| Time-travel          | Heat/freshness/priority signals |
|                      | Auto-tagging                    |
|                      | Clustering/summaries            |

### Compatibility Contract

The OSS engine MUST implement these endpoints with compatible behavior:

**Required (identical behavior):**
- `POST /v1/context/store` (all intents)
- `POST /v1/context/recall` (fetch mode, graph mode)
- `POST /v1/context/link`
- `GET /v1/health`

**Partial (graceful degradation):**
- `POST /v1/context/recall` with `mode: "search"` returns:
  ```json
  {"error": "not_supported", "message": "Semantic search requires Engrammic Cloud"}
  ```
- `POST /v1/context/admin` silo operations return `not_supported`

**Not implemented:**
- `/v1/auth/*` (no auth in OSS)
- `/v1/usage/*` (no metering)

A shared OpenAPI schema defines the contract. CI runs compatibility tests against both backends.

Users point mcp-client at `http://localhost:8000`:

```
DELTA_PRIME_BACKEND_URL=http://localhost:8000
```

## API Versioning

All endpoints are under `/v1/`. Versioning policy:

- Breaking changes require a new version (`/v2/`)
- `/v1/` will be maintained for minimum 12 months after `/v2/` release
- Deprecation announced via `Sunset` header:
  ```
  Sunset: Sat, 01 May 2027 00:00:00 GMT
  Deprecation: true
  ```
- mcp-client will warn users when `Deprecation: true` header is present

## Offline Behavior

v1: Fail immediately if backend unreachable. No queueing or caching.

Future consideration: queue writes, cache recent recalls.

## Implementation Order

1. Add REST endpoints to context-service (4 core + QoL)
2. Implement rate limiting middleware
3. Create mcp-client repo with thin proxy
4. Implement secure credential storage
5. Add token refresh handling
6. Set up OAuth flow with WorkOS
7. Test end-to-end with Claude Desktop
8. Publish to MCP marketplace
9. (Later) Implement delta-prime/engine for self-host
