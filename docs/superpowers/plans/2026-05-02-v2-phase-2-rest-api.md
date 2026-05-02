# Phase 2: REST API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the REST API surface defined in Phase 1b-B OpenAPI spec, enabling non-agent consumers (Silt) to integrate via HTTP.

**Architecture:** Routes in `api/routes/v1/` call same service layer as MCP tools. Bulk ops via Dagster. Webhooks via Redis pub/sub. Feature-flagged rollout.

**Tech Stack:** FastAPI, Pydantic, Redis, Dagster

**Depends on:** Phase 1b-A (Protocol Adoption) - service layer must depend on protocol

---

## File Structure

**Route modules:**
- Create: `src/context_service/api/routes/v1/__init__.py`
- Create: `src/context_service/api/routes/v1/context.py`
- Create: `src/context_service/api/routes/v1/silos.py`
- Create: `src/context_service/api/routes/v1/webhooks.py`
- Create: `src/context_service/api/routes/v1/bulk.py`
- Create: `src/context_service/api/routes/v1/org.py`
- Create: `src/context_service/api/routes/v1/health.py`

**Supporting modules:**
- Create: `src/context_service/api/models/requests.py`
- Create: `src/context_service/api/models/responses.py`
- Create: `src/context_service/api/middleware/rate_limit.py`
- Create: `src/context_service/api/middleware/request_id.py`
- Create: `src/context_service/webhooks/service.py`
- Create: `src/context_service/webhooks/delivery.py`
- Modify: `src/context_service/api/app.py`
- Modify: `src/context_service/config/settings.py` (add REST_API_ENABLED)

**Tests:**
- Create: `tests/api/v1/test_context.py`
- Create: `tests/api/v1/test_silos.py`
- Create: `tests/api/v1/test_webhooks.py`
- Create: `tests/api/v1/test_bulk.py`

---

## Task 1: Add Feature Flag and Route Structure

**Files:**
- Modify: `src/context_service/config/settings.py`
- Create: `src/context_service/api/routes/v1/__init__.py`
- Modify: `src/context_service/api/app.py`

- [ ] **Step 1: Add REST_API_ENABLED setting**

In `config/settings.py`, add to Settings class:

```python
rest_api_enabled: bool = Field(
    default=False,
    description="Enable REST API endpoints (v1). Set REST_API_ENABLED=true.",
)
```

- [ ] **Step 2: Create v1 router package**

Create `src/context_service/api/routes/v1/__init__.py`:

```python
"""REST API v1 routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["v1"])

# Sub-routers will be included here as they're implemented
```

- [ ] **Step 3: Conditionally include v1 router in app.py**

In `api/app.py`, add:

```python
from context_service.config.settings import get_settings

def create_app() -> FastAPI:
    app = FastAPI(...)
    
    settings = get_settings()
    if settings.rest_api_enabled:
        from context_service.api.routes.v1 import router as v1_router
        app.include_router(v1_router)
    
    return app
```

- [ ] **Step 4: Commit**

```bash
git add src/context_service/config/settings.py src/context_service/api/
git commit -m "feat: add REST_API_ENABLED flag and v1 router structure"
```

---

## Task 2: Add Request/Response Models

**Files:**
- Create: `src/context_service/api/models/__init__.py`
- Create: `src/context_service/api/models/requests.py`
- Create: `src/context_service/api/models/responses.py`

- [ ] **Step 1: Create models package**

```bash
mkdir -p src/context_service/api/models
touch src/context_service/api/models/__init__.py
```

- [ ] **Step 2: Create request models**

Create `src/context_service/api/models/requests.py`:

```python
"""Request models for REST API v1."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Request for context_query."""
    
    query: str = Field(..., min_length=1, max_length=10000)
    silo_id: str | None = None
    limit: int = Field(default=10, ge=1, le=100)
    filters: QueryFilters | None = None


class QueryFilters(BaseModel):
    """Filters for context_query."""
    
    types: list[str] | None = None
    as_of: datetime | None = None


class RememberRequest(BaseModel):
    """Request for context_remember."""
    
    content: str = Field(..., max_length=100000)
    silo_id: str
    metadata: dict[str, Any] | None = None


class AssertRequest(BaseModel):
    """Request for context_assert."""
    
    content: str
    silo_id: str
    evidence: list[str] = Field(..., min_length=1)


class CommitRequest(BaseModel):
    """Request for context_commit."""
    
    content: str
    silo_id: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class ReflectRequest(BaseModel):
    """Request for context_reflect."""
    
    content: str
    silo_id: str
    about: list[str]


class CreateSiloRequest(BaseModel):
    """Request for create_silo."""
    
    name: str = Field(..., max_length=255)
    description: str | None = Field(default=None, max_length=1000)


class CreateWebhookRequest(BaseModel):
    """Request for create_webhook."""
    
    url: str
    secret: str | None = None
    filters: WebhookFilters | None = None


class WebhookFilters(BaseModel):
    """Webhook event filters."""
    
    event_types: list[str] | None = None
    silo_ids: list[str] | None = None
    layers: list[str] | None = None


class BulkIngestRequest(BaseModel):
    """Request for bulk_ingest."""
    
    silo_id: str
    items: list[IngestItem] = Field(..., max_length=10000)


class IngestItem(BaseModel):
    """Single item in bulk ingest."""
    
    content: str = Field(..., max_length=1048576)
    type: str = "memory"
    metadata: dict[str, Any] | None = None
```

- [ ] **Step 3: Create response models**

Create `src/context_service/api/models/responses.py`:

```python
"""Response models for REST API v1."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Error detail structure."""
    
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Standard error response."""
    
    error: ErrorDetail


class NodeResponse(BaseModel):
    """Single node response."""
    
    id: str
    silo_id: str
    type: str
    content: str
    metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime | None = None


class QueryResult(BaseModel):
    """Single query result."""
    
    node: NodeResponse
    score: float


class QueryResponse(BaseModel):
    """Query response with results."""
    
    results: list[QueryResult]


class CreateResponse(BaseModel):
    """Response for create operations."""
    
    id: str


class SiloResponse(BaseModel):
    """Silo details."""
    
    id: str
    name: str
    description: str | None = None
    org_id: str
    created_at: datetime
    archived_at: datetime | None = None
    stats: SiloStats | None = None


class SiloStats(BaseModel):
    """Silo statistics."""
    
    node_count: int
    edge_count: int
    storage_bytes: int


class PaginatedSilosResponse(BaseModel):
    """Paginated silos list."""
    
    silos: list[SiloResponse]
    next_cursor: str | None = None


class WebhookResponse(BaseModel):
    """Webhook details."""
    
    id: str
    url: str
    filters: dict[str, Any] | None = None
    created_at: datetime


class WebhookCreatedResponse(WebhookResponse):
    """Webhook creation response (includes secret)."""
    
    secret: str


class PaginatedWebhooksResponse(BaseModel):
    """Paginated webhooks list."""
    
    webhooks: list[WebhookResponse]
    next_cursor: str | None = None


class JobResponse(BaseModel):
    """Bulk job response."""
    
    job_id: str


class JobStatusResponse(BaseModel):
    """Bulk job status."""
    
    job_id: str
    status: str
    progress: JobProgress | None = None
    errors: list[JobError] | None = None


class JobProgress(BaseModel):
    """Job progress details."""
    
    total: int
    processed: int
    succeeded: int
    failed: int


class JobError(BaseModel):
    """Individual item error."""
    
    index: int
    error: str


class HealthResponse(BaseModel):
    """Health check response."""
    
    status: str


class ReadyResponse(BaseModel):
    """Readiness check response."""
    
    status: str
    checks: dict[str, bool]
```

- [ ] **Step 4: Commit**

```bash
git add src/context_service/api/models/
git commit -m "feat: add REST API request/response models"
```

---

## Task 3: Add Middleware (Request ID, Rate Limiting)

**Files:**
- Create: `src/context_service/api/middleware/__init__.py`
- Create: `src/context_service/api/middleware/request_id.py`
- Create: `src/context_service/api/middleware/rate_limit.py`

- [ ] **Step 1: Create middleware package**

```bash
mkdir -p src/context_service/api/middleware
touch src/context_service/api/middleware/__init__.py
```

- [ ] **Step 2: Create request ID middleware**

Create `src/context_service/api/middleware/request_id.py`:

```python
"""Request ID middleware for tracing."""

import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add X-Request-ID to all requests."""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        
        # Store in request state for access by handlers
        request.state.request_id = request_id
        
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        
        return response
```

- [ ] **Step 3: Create rate limiting middleware**

Create `src/context_service/api/middleware/rate_limit.py`:

```python
"""Rate limiting middleware using Redis token bucket."""

from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from context_service.config.settings import get_settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiting per org."""
    
    def __init__(self, app, redis_client):
        super().__init__(app)
        self.redis = redis_client
        self.settings = get_settings()
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for health endpoints
        if request.url.path in ("/health", "/ready", "/metrics"):
            return await call_next(request)
        
        # Get org_id from auth context (set by auth middleware)
        org_id = getattr(request.state, "org_id", None)
        if not org_id:
            return await call_next(request)
        
        # Determine rate limit based on endpoint
        is_bulk = request.url.path.startswith("/v1/ingest")
        limit = 10 if is_bulk else 1000
        window = 60  # seconds
        
        key = f"ratelimit:{org_id}:{request.url.path}"
        
        # Token bucket check
        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, window)
        
        ttl = await self.redis.ttl(key)
        
        if current > limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Rate limit exceeded",
                    }
                },
                headers={
                    "Retry-After": str(ttl),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + ttl),
                },
            )
        
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current))
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + ttl)
        
        return response
```

- [ ] **Step 4: Commit**

```bash
git add src/context_service/api/middleware/
git commit -m "feat: add request ID and rate limiting middleware"
```

---

## Task 4: Implement Health Endpoints

**Files:**
- Create: `src/context_service/api/routes/v1/health.py`
- Test: `tests/api/v1/test_health.py`

- [ ] **Step 1: Write health endpoint tests**

Create `tests/api/v1/test_health.py`:

```python
"""Test health endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient):
    """Health endpoint should return ok."""
    response = await client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_returns_checks(client: AsyncClient):
    """Ready endpoint should return dependency checks."""
    response = await client.get("/v1/ready")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "checks" in data
```

- [ ] **Step 2: Implement health routes**

Create `src/context_service/api/routes/v1/health.py`:

```python
"""Health and readiness endpoints."""

from fastapi import APIRouter, Depends

from context_service.api.models.responses import HealthResponse, ReadyResponse
from context_service.stores.memgraph import MemgraphClient
from context_service.stores.qdrant import QdrantStore
from context_service.stores.redis import RedisClient

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Basic liveness check."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def readiness_check(
    memgraph: MemgraphClient = Depends(),
    qdrant: QdrantStore = Depends(),
    redis: RedisClient = Depends(),
) -> ReadyResponse:
    """Readiness check with dependency health."""
    checks = {
        "memgraph": await memgraph.health_check(),
        "qdrant": await qdrant.health_check(),
        "redis": await redis.health_check(),
    }
    
    all_healthy = all(checks.values())
    
    return ReadyResponse(
        status="ok" if all_healthy else "degraded",
        checks=checks,
    )
```

- [ ] **Step 3: Include in v1 router**

Update `src/context_service/api/routes/v1/__init__.py`:

```python
from fastapi import APIRouter

from context_service.api.routes.v1.health import router as health_router

router = APIRouter(prefix="/v1")
router.include_router(health_router)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/api/v1/test_health.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/context_service/api/routes/v1/ tests/api/v1/
git commit -m "feat: implement health endpoints"
```

---

## Task 5: Implement Context Endpoints

**Files:**
- Create: `src/context_service/api/routes/v1/context.py`
- Test: `tests/api/v1/test_context.py`

- [ ] **Step 1: Write context endpoint tests**

Create `tests/api/v1/test_context.py`:

```python
"""Test context endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_context_get_not_found(client: AsyncClient, auth_headers: dict):
    """Get non-existent context returns 404."""
    response = await client.get(
        "/v1/context/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_context_remember_creates_node(client: AsyncClient, auth_headers: dict):
    """Remember should create a memory node."""
    response = await client.post(
        "/v1/context/remember",
        json={"content": "Test memory", "silo_id": "test-silo"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert "id" in response.json()


@pytest.mark.asyncio
async def test_context_query_returns_results(client: AsyncClient, auth_headers: dict):
    """Query should return results."""
    response = await client.post(
        "/v1/context/query",
        json={"query": "test", "silo_id": "test-silo"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert "results" in response.json()
```

- [ ] **Step 2: Implement context routes**

Create `src/context_service/api/routes/v1/context.py`:

```python
"""Context CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID

from context_service.api.auth_dep import get_auth_context, AuthContext
from context_service.api.deps import get_context_service
from context_service.api.models.requests import (
    QueryRequest,
    RememberRequest,
    AssertRequest,
    CommitRequest,
    ReflectRequest,
)
from context_service.api.models.responses import (
    NodeResponse,
    QueryResponse,
    QueryResult,
    CreateResponse,
)
from context_service.services.context import ContextService

router = APIRouter(prefix="/context", tags=["context"])


@router.get("/{id}", response_model=NodeResponse)
async def context_get(
    id: UUID,
    auth: AuthContext = Depends(get_auth_context),
    service: ContextService = Depends(get_context_service),
) -> NodeResponse:
    """Get context node by ID."""
    node = await service.get(str(id), silo_id=auth.default_silo_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    return NodeResponse(
        id=str(node.id),
        silo_id=node.silo_id,
        type=node.type,
        content=node.content,
        metadata=node.metadata,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


@router.post("/query", response_model=QueryResponse)
async def context_query(
    request: QueryRequest,
    auth: AuthContext = Depends(get_auth_context),
    service: ContextService = Depends(get_context_service),
) -> QueryResponse:
    """Semantic search for context."""
    silo_id = request.silo_id or auth.default_silo_id
    
    results = await service.query(
        query=request.query,
        silo_id=silo_id,
        limit=request.limit,
        as_of=request.filters.as_of if request.filters else None,
    )
    
    return QueryResponse(
        results=[
            QueryResult(
                node=NodeResponse(
                    id=str(r.node.id),
                    silo_id=r.node.silo_id,
                    type=r.node.type,
                    content=r.node.content,
                    metadata=r.node.metadata,
                    created_at=r.node.created_at,
                    updated_at=r.node.updated_at,
                ),
                score=r.score,
            )
            for r in results
        ]
    )


@router.post("/remember", response_model=CreateResponse, status_code=201)
async def context_remember(
    request: RememberRequest,
    auth: AuthContext = Depends(get_auth_context),
    service: ContextService = Depends(get_context_service),
) -> CreateResponse:
    """Store a memory."""
    # Verify silo ownership
    await auth.assert_silo_access(request.silo_id)
    
    node_id = await service.store(
        content=request.content,
        silo_id=request.silo_id,
        type="memory",
        metadata=request.metadata,
    )
    
    return CreateResponse(id=str(node_id))


@router.post("/assert", response_model=CreateResponse, status_code=201)
async def context_assert(
    request: AssertRequest,
    auth: AuthContext = Depends(get_auth_context),
    service: ContextService = Depends(get_context_service),
) -> CreateResponse:
    """Assert a knowledge claim with evidence."""
    await auth.assert_silo_access(request.silo_id)
    
    node_id = await service.assert_claim(
        content=request.content,
        silo_id=request.silo_id,
        evidence_ids=request.evidence,
    )
    
    return CreateResponse(id=str(node_id))


@router.post("/commit", response_model=CreateResponse, status_code=201)
async def context_commit(
    request: CommitRequest,
    auth: AuthContext = Depends(get_auth_context),
    service: ContextService = Depends(get_context_service),
) -> CreateResponse:
    """Commit a wisdom-level belief."""
    await auth.assert_silo_access(request.silo_id)
    
    node_id = await service.commit_belief(
        content=request.content,
        silo_id=request.silo_id,
        confidence=request.confidence,
    )
    
    return CreateResponse(id=str(node_id))


@router.post("/reflect", response_model=CreateResponse, status_code=201)
async def context_reflect(
    request: ReflectRequest,
    auth: AuthContext = Depends(get_auth_context),
    service: ContextService = Depends(get_context_service),
) -> CreateResponse:
    """Create a meta-observation."""
    await auth.assert_silo_access(request.silo_id)
    
    node_id = await service.reflect(
        content=request.content,
        silo_id=request.silo_id,
        about_ids=request.about,
    )
    
    return CreateResponse(id=str(node_id))
```

- [ ] **Step 3: Include in v1 router**

Update `__init__.py`:

```python
from context_service.api.routes.v1.context import router as context_router
router.include_router(context_router)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/api/v1/test_context.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/context_service/api/routes/v1/ tests/api/v1/
git commit -m "feat: implement context endpoints"
```

---

## Task 6: Implement Silo Endpoints

**Files:**
- Create: `src/context_service/api/routes/v1/silos.py`
- Test: `tests/api/v1/test_silos.py`

- [ ] **Step 1: Write silo endpoint tests**

Create `tests/api/v1/test_silos.py`:

```python
"""Test silo endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_silos(client: AsyncClient, auth_headers: dict):
    """List silos returns paginated response."""
    response = await client.get("/v1/silos", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "silos" in data
    assert "next_cursor" in data


@pytest.mark.asyncio
async def test_create_silo(client: AsyncClient, auth_headers: dict):
    """Create silo returns new silo."""
    response = await client.post(
        "/v1/silos",
        json={"name": "Test Silo", "description": "A test"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert "id" in response.json()
```

- [ ] **Step 2: Implement silo routes**

Create `src/context_service/api/routes/v1/silos.py`:

```python
"""Silo management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import UUID

from context_service.api.auth_dep import get_auth_context, AuthContext
from context_service.api.deps import get_silo_service
from context_service.api.models.requests import CreateSiloRequest
from context_service.api.models.responses import (
    SiloResponse,
    PaginatedSilosResponse,
)
from context_service.services.silo import SiloService

router = APIRouter(prefix="/silos", tags=["silos"])


@router.get("", response_model=PaginatedSilosResponse)
async def list_silos(
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    include_archived: bool = False,
    auth: AuthContext = Depends(get_auth_context),
    service: SiloService = Depends(get_silo_service),
) -> PaginatedSilosResponse:
    """List silos for current org."""
    silos, next_cursor = await service.list_for_org(
        org_id=auth.org_id,
        cursor=cursor,
        limit=limit,
        include_archived=include_archived,
    )
    
    return PaginatedSilosResponse(
        silos=[
            SiloResponse(
                id=str(s.id),
                name=s.name,
                description=s.description,
                org_id=s.org_id,
                created_at=s.created_at,
                archived_at=s.archived_at,
            )
            for s in silos
        ],
        next_cursor=next_cursor,
    )


@router.post("", response_model=SiloResponse, status_code=201)
async def create_silo(
    request: CreateSiloRequest,
    auth: AuthContext = Depends(get_auth_context),
    service: SiloService = Depends(get_silo_service),
) -> SiloResponse:
    """Create a new silo."""
    silo = await service.create(
        name=request.name,
        description=request.description,
        org_id=auth.org_id,
    )
    
    return SiloResponse(
        id=str(silo.id),
        name=silo.name,
        description=silo.description,
        org_id=silo.org_id,
        created_at=silo.created_at,
    )


@router.get("/{silo_id}", response_model=SiloResponse)
async def get_silo(
    silo_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
    service: SiloService = Depends(get_silo_service),
) -> SiloResponse:
    """Get silo details."""
    await auth.assert_silo_access(str(silo_id))
    
    silo = await service.get(str(silo_id))
    if not silo:
        raise HTTPException(status_code=404, detail="Silo not found")
    
    return SiloResponse(
        id=str(silo.id),
        name=silo.name,
        description=silo.description,
        org_id=silo.org_id,
        created_at=silo.created_at,
        archived_at=silo.archived_at,
    )


@router.delete("/{silo_id}", status_code=204)
async def delete_silo(
    silo_id: UUID,
    hard: bool = False,
    auth: AuthContext = Depends(get_auth_context),
    service: SiloService = Depends(get_silo_service),
) -> None:
    """Delete silo (soft by default, hard requires admin)."""
    await auth.assert_silo_access(str(silo_id))
    
    if hard:
        auth.require_role("admin")
        await service.hard_delete(str(silo_id), auth.user_id)
    else:
        await service.soft_delete(str(silo_id))


@router.post("/{silo_id}/restore", response_model=SiloResponse)
async def restore_silo(
    silo_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
    service: SiloService = Depends(get_silo_service),
) -> SiloResponse:
    """Restore archived silo."""
    await auth.assert_silo_access(str(silo_id))
    
    silo = await service.restore(str(silo_id))
    
    return SiloResponse(
        id=str(silo.id),
        name=silo.name,
        description=silo.description,
        org_id=silo.org_id,
        created_at=silo.created_at,
    )
```

- [ ] **Step 3: Include in v1 router and commit**

```bash
git add src/context_service/api/routes/v1/ tests/api/v1/
git commit -m "feat: implement silo endpoints"
```

---

## Task 7: Implement Webhook Endpoints

**Files:**
- Create: `src/context_service/webhooks/__init__.py`
- Create: `src/context_service/webhooks/service.py`
- Create: `src/context_service/api/routes/v1/webhooks.py`
- Test: `tests/api/v1/test_webhooks.py`

Due to length constraints, this task follows the same pattern:
1. Write tests
2. Create webhook service for CRUD
3. Create webhook routes
4. Include in router
5. Commit

- [ ] **Step 1-5: Implement webhook endpoints following pattern above**

Key implementation points:
- Store webhooks in Redis or Postgres
- Generate HMAC secret on creation
- Support secret rotation with 24h overlap
- Implement filter matching

- [ ] **Step 6: Commit**

```bash
git add src/context_service/webhooks/ src/context_service/api/routes/v1/ tests/api/v1/
git commit -m "feat: implement webhook endpoints"
```

---

## Task 8: Implement Bulk Ingest

**Files:**
- Create: `src/context_service/api/routes/v1/bulk.py`
- Modify: `src/context_service/pipelines/assets/` (add bulk ingest job)
- Test: `tests/api/v1/test_bulk.py`

- [ ] **Step 1: Implement bulk ingest endpoint**

```python
@router.post("/ingest", response_model=JobResponse, status_code=202)
async def bulk_ingest(
    request: BulkIngestRequest,
    auth: AuthContext = Depends(get_auth_context),
    service: BulkService = Depends(get_bulk_service),
) -> JobResponse:
    """Start bulk ingest job."""
    # Check payload size
    if len(request.items) > 10000:
        raise HTTPException(
            status_code=413,
            detail={"code": "PAYLOAD_TOO_LARGE", "message": "Max 10000 items"}
        )
    
    await auth.assert_silo_access(request.silo_id)
    
    job_id = await service.start_ingest_job(
        silo_id=request.silo_id,
        items=request.items,
        org_id=auth.org_id,
    )
    
    return JobResponse(job_id=str(job_id))
```

- [ ] **Step 2: Implement job status endpoint**

- [ ] **Step 3: Wire Dagster job for async processing**

- [ ] **Step 4: Commit**

```bash
git add src/context_service/api/routes/v1/ src/context_service/pipelines/ tests/api/v1/
git commit -m "feat: implement bulk ingest endpoints"
```

---

## Task 9: Implement Webhook Delivery

**Files:**
- Create: `src/context_service/webhooks/delivery.py`
- Create: `src/context_service/webhooks/events.py`

- [ ] **Step 1: Create event publisher**

Publish events to Redis pub/sub when nodes are created/updated.

- [ ] **Step 2: Create delivery worker**

Subscribe to events, match against webhook filters, deliver with HMAC signature.

- [ ] **Step 3: Implement retry logic**

Exponential backoff: 1s, 5s, 30s, 5m, 30m

- [ ] **Step 4: Commit**

```bash
git add src/context_service/webhooks/
git commit -m "feat: implement webhook delivery"
```

---

## Task 10: Final Integration and Testing

- [ ] **Step 1: Update app.py with all middleware**

```python
def create_app() -> FastAPI:
    app = FastAPI(...)
    
    # Middleware
    app.add_middleware(RequestIDMiddleware)
    if settings.rest_api_enabled:
        app.add_middleware(RateLimitMiddleware, redis_client=redis)
    
    # Routes
    if settings.rest_api_enabled:
        from context_service.api.routes.v1 import router as v1_router
        app.include_router(v1_router)
    
    return app
```

- [ ] **Step 2: Run full test suite**

```bash
just check
just test
```

- [ ] **Step 3: Test with REST_API_ENABLED=true**

```bash
REST_API_ENABLED=true just dev
# In another terminal:
curl http://localhost:8000/v1/health
```

- [ ] **Step 4: Create PR**

```bash
git push -u origin phase-v2-rest-api
gh pr create --title "Phase 2: REST API implementation" --body "$(cat <<'EOF'
## Summary
- Implemented all REST API v1 endpoints per OpenAPI spec
- Added request ID and rate limiting middleware
- Implemented webhook registration and delivery
- Implemented bulk ingest with Dagster job
- Feature-flagged behind REST_API_ENABLED

## Endpoints
- Health: /health, /ready
- Context: get, query, remember, assert, commit, reflect
- Silos: CRUD, restore
- Webhooks: register, list, delete, rotate-secret
- Bulk: ingest, status

## Test plan
- [x] All unit tests pass
- [x] Integration tests with REST_API_ENABLED=true
- [x] Typecheck and lint pass
- [x] Manual curl tests

Spec: docs/superpowers/specs/2026-05-02-arch-cleanup-perf-rest-api.md
EOF
)"
```
