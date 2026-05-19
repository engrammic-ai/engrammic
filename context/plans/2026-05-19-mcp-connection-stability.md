# MCP Connection Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MCP connections resilient to transient backend errors and fix root cause of VPC Connector instability.

**Architecture:** Error boundaries catch backend exceptions at tool level, preventing FastMCP session corruption. Session recovery middleware returns HTTP 404 on corrupted sessions, triggering spec-compliant client re-initialization. Direct VPC Egress replaces VPC Connector for reliable networking.

**Tech Stack:** FastMCP, Starlette ASGI, Pulumi GCP, Cloud Run v2

**Spec:** [docs/superpowers/specs/2026-05-19-mcp-connection-stability-design.md](../../docs/superpowers/specs/2026-05-19-mcp-connection-stability-design.md)

---

## File Structure

### Phase 1: Application Code
| File | Responsibility |
|------|----------------|
| `src/context_service/mcp/error_boundary.py` | Decorator to catch backend errors, classify, and wrap cleanly |
| `src/context_service/mcp/session_recovery.py` | ASGI middleware to return 404 on session corruption |
| `src/context_service/api/app.py` | Wire middleware into MCP dispatcher |
| `tests/mcp/test_error_boundary.py` | Unit tests for error classification and boundary |
| `tests/mcp/test_session_recovery.py` | Tests for middleware 404 behavior |

### Phase 2: Infrastructure
| File | Responsibility |
|------|----------------|
| `infra/components/cloudrun.py` | Direct VPC Egress config, remove connector |
| `infra/components/network.py` | Firewall rule for Cloud Run subnet |

---

## Phase 1: Error Boundaries + Session Recovery

### Task 1: Error Boundary Module

**Files:**
- Create: `src/context_service/mcp/error_boundary.py`
- Create: `tests/mcp/test_error_boundary.py`

- [ ] **Step 1: Write failing test for backend classification**

```python
# tests/mcp/test_error_boundary.py
import pytest
from context_service.mcp.error_boundary import _classify_backend


class TestClassifyBackend:
    def test_qdrant_error(self):
        from qdrant_client.http.exceptions import UnexpectedResponse
        exc = UnexpectedResponse(status_code=500, reason_phrase="error", content=b"")
        assert _classify_backend(exc) == "qdrant"

    def test_redis_error(self):
        from redis.exceptions import ConnectionError
        exc = ConnectionError("Connection refused")
        assert _classify_backend(exc) == "redis"

    def test_memgraph_error(self):
        exc = Exception("neo4j.exceptions.ServiceUnavailable: Connection refused")
        assert _classify_backend(exc) == "memgraph"

    def test_postgres_error(self):
        exc = Exception("asyncpg.exceptions.ConnectionDoesNotExistError")
        assert _classify_backend(exc) == "postgres"

    def test_unknown_error(self):
        exc = ValueError("something else")
        assert _classify_backend(exc) == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_error_boundary.py::TestClassifyBackend -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'context_service.mcp.error_boundary'"

- [ ] **Step 3: Implement _classify_backend**

```python
# src/context_service/mcp/error_boundary.py
"""Error boundary for MCP tools.

Catches backend exceptions and wraps them in MCPBackendError to prevent
FastMCP session corruption. Backend errors are classified for logging
and retry decisions.
"""
from __future__ import annotations


def _classify_backend(e: Exception) -> str:
    """Identify which backend caused the error."""
    error_str = str(type(e).__module__) + str(type(e).__name__) + str(e)
    error_lower = error_str.lower()
    if "qdrant" in error_lower:
        return "qdrant"
    if "neo4j" in error_lower or "memgraph" in error_lower:
        return "memgraph"
    if "redis" in error_lower:
        return "redis"
    if "postgres" in error_lower or "asyncpg" in error_lower:
        return "postgres"
    return "unknown"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/test_error_boundary.py::TestClassifyBackend -v`
Expected: PASS

- [ ] **Step 5: Write failing test for retriable classification**

```python
# tests/mcp/test_error_boundary.py (append)
from context_service.mcp.error_boundary import _is_retriable


class TestIsRetriable:
    def test_timeout_is_retriable(self):
        exc = Exception("Connection timeout after 30s")
        assert _is_retriable(exc) is True

    def test_connection_refused_is_retriable(self):
        exc = Exception("Connection refused")
        assert _is_retriable(exc) is True

    def test_unavailable_is_retriable(self):
        exc = Exception("Service temporarily unavailable")
        assert _is_retriable(exc) is True

    def test_validation_error_not_retriable(self):
        exc = ValueError("Invalid node_id format")
        assert _is_retriable(exc) is False

    def test_auth_error_not_retriable(self):
        exc = Exception("Authentication failed")
        assert _is_retriable(exc) is False
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_error_boundary.py::TestIsRetriable -v`
Expected: FAIL with "cannot import name '_is_retriable'"

- [ ] **Step 7: Implement _is_retriable**

```python
# src/context_service/mcp/error_boundary.py (append)


def _is_retriable(e: Exception) -> bool:
    """Determine if error is transient and retriable."""
    error_str = str(e).lower()
    transient_patterns = ["timeout", "connection", "unavailable", "temporary", "refused"]
    return any(p in error_str for p in transient_patterns)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/mcp/test_error_boundary.py::TestIsRetriable -v`
Expected: PASS

- [ ] **Step 9: Write failing test for MCPBackendError**

```python
# tests/mcp/test_error_boundary.py (append)
from context_service.mcp.error_boundary import MCPBackendError


class TestMCPBackendError:
    def test_error_attributes(self):
        exc = MCPBackendError(backend="qdrant", message="query failed", retriable=True)
        assert exc.backend == "qdrant"
        assert exc.message == "query failed"
        assert exc.retriable is True
        assert str(exc) == "query failed"

    def test_default_retriable(self):
        exc = MCPBackendError(backend="redis", message="timeout")
        assert exc.retriable is True
```

- [ ] **Step 10: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_error_boundary.py::TestMCPBackendError -v`
Expected: FAIL with "cannot import name 'MCPBackendError'"

- [ ] **Step 11: Implement MCPBackendError**

```python
# src/context_service/mcp/error_boundary.py (insert after imports, before _classify_backend)


class MCPBackendError(Exception):
    """Raised when a backend operation fails.

    Attributes:
        backend: Which backend caused the error (qdrant, redis, memgraph, postgres, unknown)
        message: Human-readable error message
        retriable: Whether client should retry after backoff
    """

    def __init__(self, backend: str, message: str, retriable: bool = True) -> None:
        self.backend = backend
        self.message = message
        self.retriable = retriable
        super().__init__(message)
```

- [ ] **Step 12: Run test to verify it passes**

Run: `uv run pytest tests/mcp/test_error_boundary.py::TestMCPBackendError -v`
Expected: PASS

- [ ] **Step 13: Write failing test for mcp_error_boundary decorator**

```python
# tests/mcp/test_error_boundary.py (append)
import pytest
from context_service.mcp.error_boundary import mcp_error_boundary, MCPBackendError


class TestMCPErrorBoundary:
    @pytest.mark.anyio
    async def test_passes_through_success(self):
        @mcp_error_boundary
        async def successful_tool():
            return {"result": "ok"}

        result = await successful_tool()
        assert result == {"result": "ok"}

    @pytest.mark.anyio
    async def test_wraps_backend_error(self):
        @mcp_error_boundary
        async def failing_tool():
            raise Exception("qdrant connection timeout")

        with pytest.raises(MCPBackendError) as exc_info:
            await failing_tool()

        assert exc_info.value.backend == "qdrant"
        assert exc_info.value.retriable is True
        assert "qdrant" in exc_info.value.message

    @pytest.mark.anyio
    async def test_preserves_already_wrapped_error(self):
        @mcp_error_boundary
        async def tool_with_wrapped_error():
            raise MCPBackendError(backend="redis", message="explicit error", retriable=False)

        with pytest.raises(MCPBackendError) as exc_info:
            await tool_with_wrapped_error()

        assert exc_info.value.backend == "redis"
        assert exc_info.value.retriable is False
```

- [ ] **Step 14: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_error_boundary.py::TestMCPErrorBoundary -v`
Expected: FAIL with "cannot import name 'mcp_error_boundary'"

- [ ] **Step 15: Implement mcp_error_boundary decorator**

```python
# src/context_service/mcp/error_boundary.py (append after MCPBackendError)
import functools
from typing import Callable, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


def mcp_error_boundary(func: Callable[..., T]) -> Callable[..., T]:
    """Wrap MCP tool handlers to catch backend errors cleanly.

    Returns structured MCPBackendError instead of letting exceptions propagate
    to FastMCP's session layer, which can corrupt session state.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs) -> T:  # type: ignore[return]
        try:
            return await func(*args, **kwargs)
        except MCPBackendError:
            raise  # Already wrapped
        except Exception as e:
            backend = _classify_backend(e)
            retriable = _is_retriable(e)
            logger.warning(
                "mcp_tool_error",
                tool=func.__name__,
                backend=backend,
                error=str(e),
                retriable=retriable,
            )
            raise MCPBackendError(
                backend=backend,
                message=f"{backend} error: {e}",
                retriable=retriable,
            ) from e

    return wrapper
```

- [ ] **Step 16: Run test to verify it passes**

Run: `uv run pytest tests/mcp/test_error_boundary.py::TestMCPErrorBoundary -v`
Expected: PASS

- [ ] **Step 17: Run all error_boundary tests**

Run: `uv run pytest tests/mcp/test_error_boundary.py -v`
Expected: All tests PASS

- [ ] **Step 18: Commit**

```bash
git add src/context_service/mcp/error_boundary.py tests/mcp/test_error_boundary.py
git commit -m "feat(mcp): add error boundary for backend error handling

- MCPBackendError wraps backend exceptions with classification
- _classify_backend identifies qdrant/redis/memgraph/postgres
- _is_retriable determines if error is transient
- @mcp_error_boundary decorator for tool handlers"
```

---

### Task 2: Session Recovery Middleware

**Files:**
- Create: `src/context_service/mcp/session_recovery.py`
- Create: `tests/mcp/test_session_recovery.py`

- [ ] **Step 1: Write failing test for middleware**

```python
# tests/mcp/test_session_recovery.py
import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse

from context_service.mcp.session_recovery import MCPSessionRecoveryMiddleware


def make_test_app(handler):
    """Create test Starlette app with the middleware."""
    app = Starlette(routes=[Route("/mcp/test", handler, methods=["POST"])])
    return MCPSessionRecoveryMiddleware(app)


class TestMCPSessionRecoveryMiddleware:
    def test_passes_through_success(self):
        async def handler(request):
            return JSONResponse({"status": "ok"})

        app = make_test_app(handler)
        client = TestClient(app)
        response = client.post("/mcp/test")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_returns_404_on_initialization_error(self):
        async def handler(request):
            raise Exception("Received request before initialization was complete")

        app = make_test_app(handler)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/mcp/test")
        assert response.status_code == 404
        assert "expired" in response.json()["error"].lower()

    def test_reraises_other_errors(self):
        async def handler(request):
            raise ValueError("Something else went wrong")

        app = make_test_app(handler)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/mcp/test")
        assert response.status_code == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_session_recovery.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'context_service.mcp.session_recovery'"

- [ ] **Step 3: Implement session recovery middleware**

```python
# src/context_service/mcp/session_recovery.py
"""ASGI middleware for MCP session recovery.

Catches FastMCP's "initialization was complete" errors and returns HTTP 404,
triggering spec-compliant client re-initialization per MCP spec 2025-11-25.
"""
from __future__ import annotations

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)


class MCPSessionRecoveryMiddleware:
    """Wrap MCP ASGI app to handle session corruption gracefully.

    When FastMCP marks a session as uninitialized (typically after a backend
    error propagates), this middleware catches the error and returns HTTP 404.
    Per MCP spec, clients MUST re-initialize when receiving 404.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            error_str = str(e).lower()
            if "initialization" in error_str and not response_started:
                logger.warning("mcp_session_corrupted", error=str(e))
                # Return 404 to trigger client re-initialization per MCP spec
                await send({
                    "type": "http.response.start",
                    "status": 404,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b'{"error": "Session expired or invalid"}',
                })
            else:
                raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/test_session_recovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/session_recovery.py tests/mcp/test_session_recovery.py
git commit -m "feat(mcp): add session recovery middleware

Returns HTTP 404 on session corruption, triggering MCP-compliant
client re-initialization per spec 2025-11-25"
```

---

### Task 3: Wire Middleware into App

**Files:**
- Modify: `src/context_service/api/app.py:304-328`

- [ ] **Step 1: Read current app.py MCP setup**

Run: `uv run grep -n "MCPDispatcher\|mcp_app\|create_mcp_server" src/context_service/api/app.py`

Understand the current wiring before modifying.

- [ ] **Step 2: Add middleware import and wiring**

Edit `src/context_service/api/app.py`:

```python
# After line ~303 (after "if settings.mcp_enabled:")
# Add import at top of the if block:
        from context_service.mcp.session_recovery import MCPSessionRecoveryMiddleware

# Change line ~328 from:
#     return _MCPDispatcher(app, mcp_app, prefix="/mcp")
# to:
        return _MCPDispatcher(app, MCPSessionRecoveryMiddleware(mcp_app), prefix="/mcp")
```

- [ ] **Step 3: Run existing MCP tests to verify no regression**

Run: `uv run pytest tests/mcp/ -v -k "not test_error_boundary and not test_session_recovery" --ignore=tests/mcp/test_error_boundary.py --ignore=tests/mcp/test_session_recovery.py`
Expected: Existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/api/app.py
git commit -m "feat(mcp): wire session recovery middleware into app

Wraps MCP ASGI app with MCPSessionRecoveryMiddleware for
spec-compliant 404 on session corruption"
```

---

### Task 4: Apply Error Boundary to MCP Tools

**Files:**
- Modify: `src/context_service/mcp/tools/remember.py`
- Modify: `src/context_service/mcp/tools/learn.py`
- Modify: `src/context_service/mcp/tools/recall.py`
- Modify: `src/context_service/mcp/tools/believe.py`
- Modify: `src/context_service/mcp/tools/trace.py`
- Modify: `src/context_service/mcp/tools/link.py`
- Modify: `src/context_service/mcp/tools/patterns.py`
- Modify: `src/context_service/mcp/tools/reason.py` (if exists)
- Modify: `src/context_service/mcp/tools/reflect.py` (if exists)

- [ ] **Step 1: List all MCP tool files**

Run: `ls src/context_service/mcp/tools/*.py | grep -v __init__ | grep -v context_`

Identify which tool files need the decorator.

- [ ] **Step 2: Apply decorator to remember.py**

Add import and decorator:
```python
# At top of file, add:
from context_service.mcp.error_boundary import mcp_error_boundary

# Find the main tool function (async def remember(...)) and add decorator:
@mcp_error_boundary
async def remember(...):
```

- [ ] **Step 3: Apply decorator to learn.py**

Same pattern as Step 2.

- [ ] **Step 4: Apply decorator to recall.py**

Same pattern as Step 2.

- [ ] **Step 5: Apply decorator to believe.py**

Same pattern as Step 2.

- [ ] **Step 6: Apply decorator to trace.py**

Same pattern as Step 2.

- [ ] **Step 7: Apply decorator to link.py**

Same pattern as Step 2.

- [ ] **Step 8: Apply decorator to patterns.py**

Same pattern as Step 2.

- [ ] **Step 9: Apply decorator to remaining tool files**

Check for reason.py, reflect.py, hypothesize.py, revise.py, commit.py and apply decorator if they exist.

- [ ] **Step 10: Run type check**

Run: `uv run mypy src/context_service/mcp/tools/`
Expected: No errors

- [ ] **Step 11: Run MCP tool tests**

Run: `uv run pytest tests/mcp/tools/ -v`
Expected: All tests PASS

- [ ] **Step 12: Commit**

```bash
git add src/context_service/mcp/tools/
git commit -m "feat(mcp): apply error boundary to all MCP tools

Wraps tool handlers with @mcp_error_boundary to prevent
backend errors from corrupting FastMCP session state"
```

---

## Phase 2: Direct VPC Egress

### Task 5: Update Cloud Run for Direct VPC Egress

**Files:**
- Modify: `infra/components/cloudrun.py`

- [ ] **Step 1: Read current cloudrun.py**

Run: `cat infra/components/cloudrun.py`

Understand current VPC connector setup.

- [ ] **Step 2: Remove VPC Connector, add Direct VPC Egress**

Edit `infra/components/cloudrun.py`:

```python
# Remove these lines (around line 29-39):
#         # VPC Access Connector
#         self.connector = vpcaccess.Connector(
#             f"{name}-connector",
#             ...
#         )

# Change vpc_access block (around line 74-77) from:
#                 vpc_access=cloudrunv2.ServiceTemplateVpcAccessArgs(
#                     connector=self.connector.id,
#                     egress="ALL_TRAFFIC",
#                 ),
# to:
                vpc_access=cloudrunv2.ServiceTemplateVpcAccessArgs(
                    network_interfaces=[
                        cloudrunv2.ServiceTemplateVpcAccessNetworkInterfaceArgs(
                            network=vpc_id,
                            subnetwork=connector_subnet_id,  # Reuse the subnet parameter
                        )
                    ],
                    egress="ALL_TRAFFIC",
                ),

# Remove the vpcaccess import if no longer needed:
# from pulumi_gcp import cloudrunv2, vpcaccess
# becomes:
# from pulumi_gcp import cloudrunv2

# Remove self.connector from register_outputs if present
```

- [ ] **Step 3: Update __init__.py constructor signature if needed**

The `connector_subnet_id` parameter is already passed but was used for the connector. Now it's the subnet for Direct VPC Egress. No signature change needed.

- [ ] **Step 4: Run Pulumi preview**

Run: `cd infra && pulumi preview`
Expected: Shows removal of VPC Connector, update to Cloud Run service

- [ ] **Step 5: Commit**

```bash
git add infra/components/cloudrun.py
git commit -m "infra: migrate Cloud Run to Direct VPC Egress

- Remove VPC Access Connector (cost savings, better reliability)
- Use network_interfaces for direct VPC connectivity
- 2x throughput, lower latency per Google best practices"
```

---

### Task 6: Update Firewall Rules

**Files:**
- Modify: `infra/components/network.py`

- [ ] **Step 1: Read current network.py firewall rules**

Run: `uv run grep -n "Firewall\|fw_" infra/components/network.py`

- [ ] **Step 2: Add firewall rule for Cloud Run Direct VPC Egress**

Edit `infra/components/network.py`, add after existing firewall rules:

```python
        # Firewall: allow Cloud Run Direct VPC Egress to StatefulHost
        # Cloud Run uses IPs from the private subnet, not network tags
        self.fw_cloudrun_egress = compute.Firewall(
            f"{name}-fw-cloudrun-egress",
            name=f"engrammic-{env}-allow-cloudrun-egress",
            network=self.vpc.id,
            allows=[
                compute.FirewallAllowArgs(protocol="tcp", ports=["6333", "6379", "7687"]),
            ],
            source_ranges=["10.0.2.0/24"],  # Private subnet CIDR
            target_tags=["engrammic-stateful"],
            opts=pulumi.ResourceOptions(parent=self),
        )
```

- [ ] **Step 3: Remove connector subnet if no longer needed**

Check if `self.vpc_connector` subnet is only used for the removed VPC connector. If so, it can be removed to clean up. If it's reused for Direct VPC Egress subnet, keep it.

- [ ] **Step 4: Run Pulumi preview**

Run: `cd infra && pulumi preview`
Expected: Shows new firewall rule, possibly removal of connector subnet

- [ ] **Step 5: Commit**

```bash
git add infra/components/network.py
git commit -m "infra: add firewall rule for Cloud Run Direct VPC Egress

Allows Cloud Run (10.0.2.0/24) to reach StatefulHost services:
- Qdrant :6333
- Redis :6379
- Memgraph :7687"
```

---

### Task 7: Deploy and Verify

- [ ] **Step 1: Deploy Phase 1 first (application code)**

```bash
just build-api
just deploy-api-beta
```

- [ ] **Step 2: Verify MCP still works**

Test MCP connection to beta.engrammic.ai, verify tools respond.

- [ ] **Step 3: Deploy Phase 2 (infrastructure)**

```bash
cd infra && pulumi up
```

- [ ] **Step 4: Verify connectivity after networking change**

Test MCP tools again, verify no connection errors.

- [ ] **Step 5: Monitor logs for session recovery**

```bash
just logs-api-beta-tail
```

Look for `mcp_session_corrupted` or `mcp_tool_error` log entries to verify error handling works.

- [ ] **Step 6: Final commit**

```bash
git add .
git commit -m "feat: MCP connection stability - Phase 1 + Phase 2 complete

- Error boundaries prevent session corruption
- HTTP 404 on corrupted sessions per MCP spec
- Direct VPC Egress replaces VPC Connector"
```

---

## Done Criteria

- [ ] Backend errors (Qdrant, Redis, Memgraph) return clean MCPBackendError, not -32602
- [ ] Session corruption returns HTTP 404, client re-initializes
- [ ] VPC Connector removed, Direct VPC Egress active
- [ ] All existing tests pass
- [ ] MCP tools work on beta.engrammic.ai after deploy
