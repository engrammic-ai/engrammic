# MCP Connection Stability Design

## Problem

MCP connections to beta.engrammic.ai become unstable after transient backend errors:

1. VPC Connector drops connections intermittently
2. Qdrant query fails (even briefly)
3. FastMCP marks session as "uninitialized"
4. All subsequent requests fail with cryptic -32602 error
5. Client has no signal to reconnect

## Solution

Three-part fix, implemented in order:

1. **Direct VPC Egress** - Replace VPC Connector with direct networking (root cause)
2. **Error Boundaries** - Prevent backend errors from corrupting session state
3. **MCP-Compliant Recovery** - Use standard MCP mechanisms for session recovery

## Component 1: Direct VPC Egress Migration

### Rationale

Google recommends Direct VPC Egress over VPC Connectors:
- 2x throughput (1 GB/s vs ~500 Mbps)
- Lower latency (no connector hop)
- No idle costs (scales to zero)
- More reliable (direct network path)

### Changes

**infra/components/cloudrun.py**:
- Remove `vpcaccess.Connector` resource
- Add `network_interfaces` block with Direct VPC Egress:

```python
template=cloudrunv2.ServiceTemplateArgs(
    # ... existing config ...
    vpc_access=cloudrunv2.ServiceTemplateVpcAccessArgs(
        network_interfaces=[
            cloudrunv2.ServiceTemplateVpcAccessNetworkInterfaceArgs(
                network=vpc_id,
                subnetwork=subnet_id,
                tags=["engrammic-api"],
            )
        ],
        egress="ALL_TRAFFIC",
    ),
    # Remove: connector=self.connector.id
)
```

**infra/components/network.py**:
- Remove connector subnet (10.0.3.0/28)
- Add firewall rule for `engrammic-api` network tag:

```python
self.fw_cloudrun = compute.Firewall(
    f"{name}-fw-cloudrun",
    name=f"engrammic-{env}-allow-cloudrun",
    network=self.vpc.id,
    allows=[
        compute.FirewallAllowArgs(protocol="tcp", ports=["6333", "6379", "7687"]),
    ],
    source_tags=["engrammic-api"],
    target_tags=["engrammic-stateful"],
    opts=pulumi.ResourceOptions(parent=self),
)
```

### Migration

1. Deploy new Cloud Run revision with Direct VPC Egress
2. Cloud Run handles traffic shift automatically
3. Delete VPC Connector after verification
4. Expected interruption: ~30s during revision switch

### Rollback

Revert Pulumi config, redeploy with connector.

## Component 2: Error Boundaries

### Rationale

Backend errors should not corrupt MCP session state. Tools should catch and return clean errors.

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
    """Wrap MCP tool handlers to catch backend errors cleanly."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs) -> T:
        try:
            return await func(*args, **kwargs)
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

**Update tool handlers**:

Apply `@mcp_error_boundary` decorator to all MCP tools in `src/context_service/mcp/tools/`.

### Error Classification

| Error Type | Code | Retriable | Client Action |
|------------|------|-----------|---------------|
| Transient backend failure | -32000 | Yes | Retry after backoff |
| Auth failure | -32001 | No | Re-authenticate |
| Session corrupted | -32600 | No | Reconnect |
| Invalid parameters | -32602 | No | Fix request |

## Component 3: MCP-Compliant Session Recovery

### Rationale

MCP spec has built-in mechanisms for session recovery. Use them instead of custom endpoints.

### Changes

**SSE Event IDs** in `src/context_service/mcp/sse_events.py`:

```python
import uuid
from datetime import datetime, timedelta
from context_service.stores import RedisClient

EVENT_TTL = timedelta(minutes=5)

async def attach_event_id(event: dict, redis: RedisClient) -> dict:
    """Attach unique ID to SSE event and store for replay."""
    event_id = str(uuid.uuid4())
    event["id"] = event_id
    
    # Store for potential replay
    await redis.setex(
        f"sse:event:{event_id}",
        int(EVENT_TTL.total_seconds()),
        json.dumps(event),
    )
    return event


async def get_events_since(last_event_id: str, redis: RedisClient) -> list[dict] | None:
    """Get events after last_event_id for replay. Returns None if not found."""
    # Implementation: scan Redis for events newer than last_event_id
    # Return None if last_event_id not found (expired) to signal full reconnect
    pass
```

**Stream Resumption** in FastMCP config:

- On GET with `Last-Event-ID` header, replay missed events
- If event expired, return `-32600` to signal full reconnect needed

**Error Response Format**:

```python
# Transient error (retriable)
{
    "jsonrpc": "2.0",
    "id": request_id,
    "error": {
        "code": -32000,
        "message": "Backend temporarily unavailable",
        "data": {"backend": "qdrant", "retriable": True}
    }
}

# Session terminated (reconnect required)
{
    "jsonrpc": "2.0", 
    "id": request_id,
    "error": {
        "code": -32600,
        "message": "Session terminated by server",
        "data": {"reconnect_required": True}
    }
}
```

### Behavior

| Scenario | Server Response | Client Action |
|----------|-----------------|---------------|
| Transient error | -32000 + retriable | Retry with backoff |
| Session corrupted | -32600 | Reconnect (new session) |
| Disconnect | SSE closes | Reconnect with Last-Event-ID |
| Event replay fails | -32600 | Full reconnect |

## Implementation Order

1. **Phase 1: Direct VPC Egress** (networking)
   - Fixes root cause of connection drops
   - Pulumi changes only
   - Brief maintenance window

2. **Phase 2: Error Boundaries + MCP Recovery** (application)
   - Error boundary decorator
   - SSE event IDs
   - Proper error codes
   - Can deploy independently

## Success Criteria

- No more -32602 errors from backend hiccups
- MCP sessions survive transient Qdrant/Memgraph/Redis failures
- Clients can resume after disconnect using Last-Event-ID
- VPC Connector costs eliminated

## Files Changed

### Phase 1
- `infra/components/cloudrun.py` - Direct VPC Egress config
- `infra/components/network.py` - Remove connector subnet, add firewall rule

### Phase 2
- `src/context_service/mcp/error_boundary.py` - New file
- `src/context_service/mcp/sse_events.py` - New file
- `src/context_service/mcp/tools/*.py` - Add error boundary decorator
- `src/context_service/mcp/server.py` - Wire SSE event IDs

## References

- [Direct VPC Egress Documentation](https://cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [MCP Transports Specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [Cloud Run Networking Best Practices](https://docs.cloud.google.com/run/docs/configuring/networking-best-practices)
