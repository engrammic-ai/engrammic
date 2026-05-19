# MCP Connection Stability Design

## Problem

MCP connections to beta.engrammic.ai become unstable after transient backend errors:

1. VPC Connector drops connections intermittently
2. Qdrant query fails (even briefly)
3. FastMCP marks session as "uninitialized"
4. All subsequent requests fail with cryptic -32602 error
5. Client has no signal to reconnect

## Solution

Two-part fix:

1. **Error Boundaries + Session Recovery** - Handle errors gracefully using MCP-standard mechanisms
2. **Direct VPC Egress** - Replace VPC Connector with direct networking (root cause fix)

## Component 1: Error Boundaries + MCP-Compliant Session Recovery

> **Deploy this BEFORE networking changes** to ensure the cutover itself is protected.

### MCP Session Management (per spec)

From [MCP Transports Spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports):

1. Server assigns `MCP-Session-Id` header during initialization
2. Client includes it in all subsequent requests
3. **Session invalid → HTTP 404 → Client re-initializes**

> "When a client receives HTTP 404 in response to a request containing an MCP-Session-Id, it MUST start a new session by sending a new InitializeRequest without a session ID attached."

This is the standard recovery path. No custom health endpoints or event replay needed.

### FastMCP Session Corruption

The "Received request before initialization was complete" error comes from FastMCP's internal session validation. Investigation needed:

1. **Check FastMCP source** - Determine if session state corruption happens inside FastMCP or if it's triggered by uncaught exceptions
2. **If FastMCP-internal** - May need to return HTTP 404 when session is corrupted (triggering client re-init per spec)
3. **If exception-triggered** - Error boundary decorator will prevent corruption

**Fallback approach**: If FastMCP doesn't expose hooks, wrap the entire MCP ASGI app with middleware that:
- Catches the "initialization was complete" error
- Returns HTTP 404 to trigger spec-compliant client re-initialization

### Changes

**New file: src/context_service/mcp/error_boundary.py**:

```python
import functools
from typing import Callable, TypeVar
import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class MCPBackendError(Exception):
    """Raised when a backend operation fails."""
    def __init__(self, backend: str, message: str, retriable: bool = True):
        self.backend = backend
        self.message = message
        self.retriable = retriable
        super().__init__(message)


def mcp_error_boundary(func: Callable[..., T]) -> Callable[..., T]:
    """Wrap MCP tool handlers to catch backend errors cleanly.
    
    Returns structured MCP error instead of letting exceptions propagate
    to FastMCP's session layer, which can corrupt session state.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs) -> T:
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
            )
    return wrapper


def _classify_backend(e: Exception) -> str:
    """Identify which backend caused the error."""
    error_str = str(type(e).__module__) + str(e)
    if "qdrant" in error_str.lower():
        return "qdrant"
    if "memgraph" in error_str.lower() or "neo4j" in error_str.lower():
        return "memgraph"
    if "redis" in error_str.lower():
        return "redis"
    if "postgres" in error_str.lower() or "asyncpg" in error_str.lower():
        return "postgres"
    return "unknown"


def _is_retriable(e: Exception) -> bool:
    """Determine if error is transient and retriable."""
    error_str = str(e).lower()
    transient_patterns = ["timeout", "connection", "unavailable", "temporary"]
    return any(p in error_str for p in transient_patterns)
```

**New file: src/context_service/mcp/session_recovery.py**:

```python
"""ASGI middleware for MCP session recovery.

Catches FastMCP's "initialization was complete" errors and returns HTTP 404,
triggering spec-compliant client re-initialization.
"""
from starlette.types import ASGIApp, Receive, Scope, Send
import structlog

logger = structlog.get_logger(__name__)


class MCPSessionRecoveryMiddleware:
    """Wrap MCP ASGI app to handle session corruption gracefully."""
    
    def __init__(self, app: ASGIApp):
        self.app = app
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        try:
            await self.app(scope, receive, send)
        except Exception as e:
            if "initialization" in str(e).lower():
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

**Update src/context_service/api/app.py**:

Wrap MCP app with session recovery middleware:

```python
from context_service.mcp.session_recovery import MCPSessionRecoveryMiddleware

# In create_app(), change:
# return _MCPDispatcher(app, mcp_app, prefix="/mcp")
# to:
return _MCPDispatcher(app, MCPSessionRecoveryMiddleware(mcp_app), prefix="/mcp")
```

**Update tool handlers**:

Apply `@mcp_error_boundary` decorator to all MCP tools in `src/context_service/mcp/tools/`.

### Error Classification

| Error Type | Response | Client Action |
|------------|----------|---------------|
| Transient backend failure | JSON-RPC -32000 + retriable | Retry after backoff |
| Auth failure | JSON-RPC -32001 | Re-authenticate |
| Session corrupted | HTTP 404 | Re-initialize (per MCP spec) |
| Invalid parameters | JSON-RPC -32602 | Fix request |

### Behavior

| Scenario | Server Response | Client Action |
|----------|-----------------|---------------|
| Transient error | -32000 + retriable | Retry with backoff |
| Session corrupted | HTTP 404 | Send new InitializeRequest |
| Connection drops | SSE closes | Reconnect, re-initialize if 404 |

## Component 2: Direct VPC Egress Migration

### Rationale

Google recommends Direct VPC Egress over VPC Connectors:
- 2x throughput (1 GB/s vs ~500 Mbps)
- Lower latency (no connector hop)
- No idle costs (scales to zero)
- More reliable (direct network path)

### Network Architecture

```
Cloud Run (Direct VPC Egress)
    |
    | (subnet: 10.0.2.0/24)
    v
+-------------------+
|   Private VPC     |
+-------------------+
    |           |
    |           +---> Cloud SQL (via Private Services Access)
    |                 (separate peering, unaffected by this change)
    v
StatefulHost (10.0.2.4)
  - Qdrant :6333
  - Redis :6379  
  - Memgraph :7687
```

### Changes

**infra/components/cloudrun.py**:

```python
template=cloudrunv2.ServiceTemplateArgs(
    # ... existing config ...
    vpc_access=cloudrunv2.ServiceTemplateVpcAccessArgs(
        network_interfaces=[
            cloudrunv2.ServiceTemplateVpcAccessNetworkInterfaceArgs(
                network=vpc_id,
                subnetwork=subnet_id,
            )
        ],
        egress="ALL_TRAFFIC",
    ),
    # Remove: connector=self.connector.id
)
```

- Remove `vpcaccess.Connector` resource entirely

**infra/components/network.py**:

```python
# Remove connector subnet (10.0.3.0/28)

# Add firewall rule using subnet CIDR as source
# (Cloud Run with Direct VPC Egress doesn't support network tags for firewall source)
self.fw_cloudrun = compute.Firewall(
    f"{name}-fw-cloudrun",
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

### Migration

1. Ensure Component 1 is deployed (protects cutover)
2. Deploy new Cloud Run revision with Direct VPC Egress
3. Cloud Run handles traffic shift (~30s)
4. Verify connectivity to StatefulHost
5. Delete VPC Connector

### Rollback

Revert Pulumi config, redeploy with connector.

## Implementation Order

1. **Phase 1: Error Boundaries + Session Recovery** (application)
   - Error boundary decorator
   - Session recovery middleware (HTTP 404 on corruption)
   - **Deploy first to protect Phase 2 cutover**

2. **Phase 2: Direct VPC Egress** (networking)
   - Pulumi changes
   - Protected by Phase 1 error handling

## Success Criteria

- No more -32602 errors from backend hiccups
- Session corruption returns HTTP 404 (spec-compliant)
- Clients re-initialize automatically after 404
- VPC Connector costs eliminated

## Files Changed

### Phase 1
- `src/context_service/mcp/error_boundary.py` - New file
- `src/context_service/mcp/session_recovery.py` - New file
- `src/context_service/mcp/tools/*.py` - Add error boundary decorator
- `src/context_service/api/app.py` - Wire session recovery middleware

### Phase 2
- `infra/components/cloudrun.py` - Direct VPC Egress config, remove connector
- `infra/components/network.py` - Remove connector subnet, add firewall rule

## Open Questions

1. **FastMCP internals** - Need to verify the exact exception type for "initialization was complete" to catch it precisely in middleware.

## References

- [MCP Transports Specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [Direct VPC Egress Documentation](https://cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [Cloud Run Networking Best Practices](https://docs.cloud.google.com/run/docs/configuring/networking-best-practices)
