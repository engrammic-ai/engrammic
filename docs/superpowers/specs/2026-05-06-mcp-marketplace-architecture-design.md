# MCP Marketplace Architecture

Split architecture for Delta Prime MCP marketplace release: public thin client, private cloud backend, optional OSS self-host.

## Overview

Three repositories serve different purposes:

| Repo | Visibility | Purpose |
|------|-----------|---------|
| delta-prime/mcp-client | Public | Marketplace listing, thin proxy to backend |
| delta-prime/engine | Public | OSS self-host backend (deferred) |
| delta-prime/context-service | Private | Full cloud backend |

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
│       ├── config.py            # Settings from .env
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

```python
class DeltaPrimeClient:
    def __init__(self, settings: Settings):
        self.base_url = settings.backend_url
        self.token = settings.api_key or self._load_oauth_token()
    
    async def post(self, path: str, data: dict) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}{path}",
                json=data,
                headers={"Authorization": f"Bearer {self.token}"}
            )
            resp.raise_for_status()
            return resp.json()
    
    def _load_oauth_token(self) -> str:
        # Load from credentials_path, trigger OAuth if missing
        ...
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
async def store(req: StoreRequest, auth: AuthContext = Depends(get_auth)):
    return await _context_store_impl(
        intent=req.intent,
        content=req.content,
        silo_id=derive_silo_id(auth.org_id),
        ...
    )
```

### QoL Endpoints

```
GET  /v1/health              # Service health
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

## Authentication

### Auth Flow

mcp-client forwards credentials, context-service validates:

```
mcp-client              context-service
    │                        │
    │  Authorization:        │
    │  Bearer <token>        │
    │───────────────────────▶│
    │                        │  validate token
    │                        │  extract org_id
    │                        │  derive silo_id
    │                        │  enforce isolation
    │        response        │
    │◀───────────────────────│
```

### API Key Flow

1. User creates key in dashboard (tied to their org)
2. User sets `DELTA_PRIME_API_KEY` in `.env`
3. mcp-client sends `Authorization: Bearer <key>` on every request
4. context-service looks up key, gets org_id, derives silo_id

### OAuth Flow

1. User runs first MCP command (or explicit `delta-prime login`)
2. No stored token found, browser opens
3. User authenticates via WorkOS
4. Token saved to `~/.delta-prime/credentials.json`
5. Subsequent calls use stored token
6. context-service validates with WorkOS, extracts org_id

### Tenant Isolation

All isolation logic stays in context-service:

- Auth middleware validates token, extracts org_id
- silo_id derived from org_id
- All queries scoped to silo_id
- mcp-client never sees or interprets tenant data

## OSS Engine (Deferred)

delta-prime/engine implements the same REST surface with minimal dependencies:

- SQLite or embedded graph for storage
- No auth (local single-tenant)
- No signals, clustering, or custodian

Feature split:

| OSS (free self-host) | Cloud-only |
|---------------------|------------|
| Basic store/recall | Semantic search (embeddings) |
| Simple graph | Custodian/consensus promotion |
| Time-travel | Heat/freshness/priority signals |
| | Auto-tagging |
| | Clustering/summaries |

Users point mcp-client at `http://localhost:8000`:

```
DELTA_PRIME_BACKEND_URL=http://localhost:8000
```

## Offline Behavior

v1: Fail immediately if backend unreachable. No queueing or caching.

Future consideration: queue writes, cache recent recalls.

## Implementation Order

1. Add REST endpoints to context-service (4 core + QoL)
2. Create mcp-client repo with thin proxy
3. Set up OAuth flow with WorkOS
4. Test end-to-end with Claude Desktop
5. Publish to MCP marketplace
6. (Later) Implement delta-prime/engine for self-host
