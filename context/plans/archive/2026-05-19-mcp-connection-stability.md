# MCP Connection Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MCP connections resilient to transient backend errors and fix root cause of VPC Connector instability.

**Architecture:** Error boundaries catch backend exceptions at tool level, converting them to JSON-RPC -32000 errors instead of letting them corrupt FastMCP session state. Session recovery middleware returns HTTP 404 on corrupted sessions, triggering spec-compliant client re-initialization. Direct VPC Egress replaces VPC Connector for reliable networking.

**Tech Stack:** FastMCP, Starlette ASGI, Pulumi GCP, Cloud Run v2

**Spec:** [docs/superpowers/specs/2026-05-19-mcp-connection-stability-design.md](../../docs/superpowers/specs/2026-05-19-mcp-connection-stability-design.md)

---

## File Structure

### Phase 1: Application Code
| File | Responsibility |
|------|----------------|
| `src/context_service/mcp/error_boundary.py` | Decorator to catch backend errors, classify, wrap as JSON-RPC -32000 |
| `src/context_service/mcp/session_recovery.py` | ASGI middleware to return 404 on session corruption |
| `src/context_service/api/app.py` | Wire middleware into MCP dispatcher |
| `tests/mcp/test_error_boundary.py` | Unit tests for error classification and boundary |
| `tests/mcp/test_session_recovery.py` | Tests for middleware 404 behavior |

### Phase 2: Infrastructure
| File | Responsibility |
|------|----------------|
| `infra/components/cloudrun.py` | Direct VPC Egress config, remove connector |
| `infra/components/network.py` | Firewall rule for Cloud Run subnet |
| `infra/__main__.py` | Update call site for renamed parameter |

---

## Phase 1: Error Boundaries + Session Recovery

### Task 1: Error Boundary Module

**Files:**
- Create: `src/context_service/mcp/error_boundary.py`
- Create: `tests/mcp/test_error_boundary.py`

- [ ] **Step 1: Write failing test for backend classification**

```python
# tests/mcp/test_error_boundary.py
"""Tests for MCP error boundary module."""
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

Catches backend exceptions and converts them to JSON-RPC -32000 errors,
preventing FastMCP session corruption. Backend errors are classified for
logging and retry decisions.
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

    def test_jsonrpc_error_code(self):
        exc = MCPBackendError(backend="qdrant", message="timeout", retriable=True)
        assert exc.jsonrpc_code == -32000  # Server error for retriable

    def test_jsonrpc_error_code_non_retriable(self):
        exc = MCPBackendError(backend="postgres", message="auth failed", retriable=False)
        assert exc.jsonrpc_code == -32000  # Still server error, but not retriable
```

- [ ] **Step 10: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_error_boundary.py::TestMCPBackendError -v`
Expected: FAIL with "cannot import name 'MCPBackendError'"

- [ ] **Step 11: Implement MCPBackendError with JSON-RPC code**

```python
# src/context_service/mcp/error_boundary.py (insert after imports, before _classify_backend)
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR


class MCPBackendError(McpError):
    """Backend error that maps to JSON-RPC -32000.

    Extends McpError so FastMCP serializes it properly as a JSON-RPC error
    response instead of letting it propagate and corrupt session state.

    Attributes:
        backend: Which backend caused the error (qdrant, redis, memgraph, postgres, unknown)
        message: Human-readable error message
        retriable: Whether client should retry after backoff
        jsonrpc_code: JSON-RPC error code (-32000 for server errors)
    """

    def __init__(self, backend: str, message: str, retriable: bool = True) -> None:
        self.backend = backend
        self.message = message
        self.retriable = retriable
        self.jsonrpc_code = INTERNAL_ERROR  # -32000
        # McpError expects (code, message, data)
        super().__init__(
            INTERNAL_ERROR,
            f"{backend} error: {message}",
            {"backend": backend, "retriable": retriable},
        )
```

- [ ] **Step 12: Run test to verify it passes**

Run: `uv run pytest tests/mcp/test_error_boundary.py::TestMCPBackendError -v`
Expected: PASS

- [ ] **Step 13: Write failing test for mcp_error_boundary decorator**

Note: The repo uses `asyncio_mode = "auto"` in pytest config, so async tests run automatically without markers.

```python
# tests/mcp/test_error_boundary.py (append)
from context_service.mcp.error_boundary import mcp_error_boundary, MCPBackendError


class TestMCPErrorBoundary:
    async def test_passes_through_success(self):
        @mcp_error_boundary
        async def successful_tool():
            return {"result": "ok"}

        result = await successful_tool()
        assert result == {"result": "ok"}

    async def test_wraps_backend_error_as_mcp_error(self):
        @mcp_error_boundary
        async def failing_tool():
            raise Exception("qdrant connection timeout")

        with pytest.raises(MCPBackendError) as exc_info:
            await failing_tool()

        assert exc_info.value.backend == "qdrant"
        assert exc_info.value.retriable is True
        assert exc_info.value.jsonrpc_code == -32000

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
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

import structlog

logger = structlog.get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def mcp_error_boundary(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Wrap MCP tool handlers to catch backend errors cleanly.

    Converts backend exceptions to MCPBackendError (which extends McpError),
    so FastMCP serializes them as JSON-RPC -32000 errors instead of letting
    them propagate and corrupt session state.
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
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
                message=str(e),
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
git commit -m "feat(mcp): add error boundary with JSON-RPC -32000 mapping

- MCPBackendError extends McpError for proper JSON-RPC serialization
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
"""Tests for MCP session recovery middleware."""
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
        with pytest.raises(ValueError, match="Something else went wrong"):
            client = TestClient(app, raise_server_exceptions=True)
            client.post("/mcp/test")
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

Run: `grep -n "MCPDispatcher\|mcp_app\|create_mcp_server" src/context_service/api/app.py`

Understand the current wiring before modifying.

- [ ] **Step 2: Add middleware import at top of file**

Edit `src/context_service/api/app.py`, add import near other imports (around line 20):

```python
from context_service.mcp.session_recovery import MCPSessionRecoveryMiddleware
```

- [ ] **Step 3: Wire middleware into MCP dispatcher**

Find the line (around 328):
```python
return _MCPDispatcher(app, mcp_app, prefix="/mcp")
```

Change it to:
```python
return _MCPDispatcher(app, MCPSessionRecoveryMiddleware(mcp_app), prefix="/mcp")
```

- [ ] **Step 4: Run existing MCP tests to verify no regression**

Run: `uv run pytest tests/mcp/ -v --ignore=tests/mcp/test_error_boundary.py --ignore=tests/mcp/test_session_recovery.py`
Expected: Existing tests PASS

- [ ] **Step 5: Commit**

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

**Important:** Decorator stacking order matters. The `@mcp_error_boundary` decorator must be **INSIDE** (below) the `@mcp.tool()` decorator:

```python
@mcp.tool()  # OUTER - registers the tool with FastMCP
@mcp_error_boundary  # INNER - wraps the actual function
async def my_tool(...):
    ...
```

This ensures the error boundary catches exceptions from the tool implementation before FastMCP sees them.

- [ ] **Step 1: List all MCP tool files**

Run: `ls src/context_service/mcp/tools/*.py | grep -v __init__ | grep -v context_`

Identify which tool files need the decorator.

- [ ] **Step 2: Apply decorator to remember.py**

Add import at top:
```python
from context_service.mcp.error_boundary import mcp_error_boundary
```

Find the tool function and add decorator **below** `@mcp.tool()`:
```python
@mcp.tool()
@mcp_error_boundary  # Add this line
async def remember(...):
```

- [ ] **Step 3: Apply decorator to learn.py**

Same pattern: import at top, `@mcp_error_boundary` below `@mcp.tool()`.

- [ ] **Step 4: Apply decorator to recall.py**

Same pattern.

- [ ] **Step 5: Apply decorator to believe.py**

Same pattern.

- [ ] **Step 6: Apply decorator to trace.py**

Same pattern.

- [ ] **Step 7: Apply decorator to link.py**

Same pattern.

- [ ] **Step 8: Apply decorator to patterns.py**

Same pattern.

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

Wraps tool handlers with @mcp_error_boundary (below @mcp.tool())
to convert backend errors to JSON-RPC -32000 responses"
```

---

## Phase 2: Direct VPC Egress

### Task 5: Update Cloud Run for Direct VPC Egress

**Files:**
- Modify: `infra/components/cloudrun.py`

- [ ] **Step 1: Read current cloudrun.py**

Run: `cat infra/components/cloudrun.py`

Understand current VPC connector setup.

- [ ] **Step 2: Remove VPC Connector resource**

Delete the VPC Access Connector block (around lines 29-39):
```python
# DELETE THIS BLOCK:
# self.connector = vpcaccess.Connector(
#     f"{name}-connector",
#     ...
# )
```

- [ ] **Step 3: Update vpc_access to use Direct VPC Egress**

Change the vpc_access block (around line 74-77) from:
```python
vpc_access=cloudrunv2.ServiceTemplateVpcAccessArgs(
    connector=self.connector.id,
    egress="ALL_TRAFFIC",
),
```

To:
```python
vpc_access=cloudrunv2.ServiceTemplateVpcAccessArgs(
    network_interfaces=[
        cloudrunv2.ServiceTemplateVpcAccessNetworkInterfaceArgs(
            network=vpc_id,
            subnetwork=connector_subnet_id,
        )
    ],
    egress="ALL_TRAFFIC",
),
```

- [ ] **Step 4: Remove vpcaccess import**

Change:
```python
from pulumi_gcp import cloudrunv2, vpcaccess
```

To:
```python
from pulumi_gcp import cloudrunv2
```

- [ ] **Step 5: Remove self.connector from register_outputs if present**

Check `register_outputs` block and remove any connector reference.

- [ ] **Step 6: Run Pulumi preview**

Run: `cd infra && pulumi preview`
Expected: Shows removal of VPC Connector, update to Cloud Run service

- [ ] **Step 7: Commit**

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

Run: `grep -n "Firewall\|fw_" infra/components/network.py`

- [ ] **Step 2: Add firewall rule for Cloud Run Direct VPC Egress**

Edit `infra/components/network.py`, add after existing firewall rules (around line 87):

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

- [ ] **Step 3: Keep connector subnet for Direct VPC Egress**

The `self.vpc_connector` subnet (10.0.3.0/28) was for the VPC Connector. Direct VPC Egress uses the private subnet (10.0.2.0/24) directly. The connector subnet can be removed, but verify it's not referenced elsewhere first.

Run: `grep -r "connector_subnet\|vpc_connector" infra/`

If only used in cloudrun.py for the old connector, it can be removed. If referenced in `__main__.py` or elsewhere, update those references.

- [ ] **Step 4: Run Pulumi preview**

Run: `cd infra && pulumi preview`
Expected: Shows new firewall rule

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
git add infra/components/cloudrun.py infra/components/network.py
git commit -m "feat: MCP connection stability - Phase 1 + Phase 2 complete

- Error boundaries convert backend errors to JSON-RPC -32000
- HTTP 404 on corrupted sessions per MCP spec
- Direct VPC Egress replaces VPC Connector"
```

---

## Done Criteria

- [ ] Backend errors (Qdrant, Redis, Memgraph) return JSON-RPC -32000, not -32602
- [ ] Session corruption returns HTTP 404, client re-initializes
- [ ] VPC Connector removed, Direct VPC Egress active
- [ ] All existing tests pass
- [ ] MCP tools work on beta.engrammic.ai after deploy
