# test_advance_time MCP Tool

**Created**: 2026-05-28
**Status**: Draft
**Purpose**: Enable Somnus to test time-based decay in cross-session coherence scenarios

## Problem

Somnus needs to test whether Engrammic's freshness decay affects cross-session coherence. Currently there's no way to simulate time passing without actually waiting.

Freshness is calculated in `signals/freshness.py`:
```python
days = (now - created_at).total_seconds() / 86400.0
score = exp(-0.5 * (days / sigma_days) ** 2)  # sigma_days=30 by default
```

Nodes older than ~90 days (3*sigma) hit the floor (0.25).

## Proposed Solution

Add `test_advance_time` MCP tool that backdates all timestamps in a silo.

### Tool Signature

```python
@mcp.tool(name="test_advance_time")
async def test_advance_time(
    silo_id: str,
    seconds: int,
    node_ids: list[str] | None = None,  # Optional: only age specific nodes
) -> dict[str, Any]:
    """Backdate timestamps to simulate time passing.
    
    TEST ONLY - not for production use. Should be gated by environment
    or a test-mode flag.
    
    Args:
        silo_id: Target silo UUID
        seconds: Seconds to subtract from timestamps (positive = age forward)
        node_ids: If provided, only backdate these nodes. Otherwise all nodes in silo.
    
    Returns:
        {"status": "ok", "nodes_updated": N}
    """
```

### Implementation

```python
# In mcp/tools/test_advance_time.py

TEST_ADVANCE_TIME_NODES = """
MATCH (n) 
WHERE n.silo_id = $silo_id
  AND ($node_ids IS NULL OR n.id IN $node_ids)
SET 
  n.created_at = n.created_at - duration({seconds: $seconds}),
  n.updated_at = n.updated_at - duration({seconds: $seconds}),
  n.last_accessed_at = CASE 
    WHEN n.last_accessed_at IS NOT NULL 
    THEN n.last_accessed_at - duration({seconds: $seconds})
    ELSE null 
  END,
  n.valid_from = CASE
    WHEN n.valid_from IS NOT NULL
    THEN n.valid_from - duration({seconds: $seconds})
    ELSE null
  END,
  n.valid_to = CASE
    WHEN n.valid_to IS NOT NULL
    THEN n.valid_to - duration({seconds: $seconds})
    ELSE null
  END
RETURN count(n) AS updated
"""

TEST_ADVANCE_TIME_EDGES = """
MATCH (a)-[r]->(b)
WHERE a.silo_id = $silo_id
  AND r.created_at IS NOT NULL
SET r.created_at = r.created_at - duration({seconds: $seconds})
RETURN count(r) AS updated
"""

async def _test_advance_time(
    silo_id: str,
    seconds: int,
    node_ids: list[str] | None = None,
) -> dict[str, Any]:
    from context_service.config.settings import get_settings
    from context_service.mcp.server import get_context_service
    
    settings = get_settings()
    if not settings.test_tools_enabled:
        return {"status": "error", "error": "disabled", "message": "Test tools not enabled"}
    
    ctx = get_context_service()
    store = ctx.graph_store
    
    node_result = await store.execute_write(
        TEST_ADVANCE_TIME_NODES,
        {"silo_id": silo_id, "seconds": seconds, "node_ids": node_ids},
    )
    
    edge_result = await store.execute_write(
        TEST_ADVANCE_TIME_EDGES,
        {"silo_id": silo_id, "seconds": seconds},
    )
    
    return {
        "status": "ok",
        "nodes_updated": node_result[0]["updated"],
        "edges_updated": edge_result[0]["updated"],
        "seconds_advanced": seconds,
    }
```

### Safety Gates

Option A: Environment check
```python
if not settings.test_mode_enabled:
    return {"status": "error", "message": "test_advance_time only available in test mode"}
```

Option B: Silo name pattern
```python
if not silo_id.startswith("somnus-") and not silo_id.startswith("test-"):
    return {"status": "error", "message": "test_advance_time only works on test silos"}
```

Option C: Separate test MCP server (overkill)

**Recommendation:** Option B — pattern-based, simple, no config change needed.

## Usage in Somnus

```yaml
# coherence scenario with decay
name: decay-coherence
steps:
  - session: 1
    prompt: "Learn: The API uses OAuth2"
    
  - action: advance_time
    seconds: 7776000  # 90 days (3*sigma)
    
  - session: 2
    prompt: "What authentication does the API use?"
    assert:
      # Either correct recall OR appropriate uncertainty
      - response_contains: ["OAuth2"]
      # OR if decayed past threshold:
      - response_indicates_low_confidence: true
```

## Files to Create/Modify

1. **Create:** `src/context_service/mcp/tools/test_advance_time.py`
2. **Modify:** `src/context_service/mcp/tools/__init__.py` — register tool
3. **Modify:** `src/context_service/mcp/tools/registry.py` — add description
4. **Create:** `tests/mcp/tools/test_advance_time_test.py`

## Test Cases

1. Advance all nodes by 30 days, verify freshness drops
2. Advance specific node_ids only
3. Reject non-test silos (if Option B)
4. Verify timestamps are correctly backdated

## Decisions

1. **Edges:** Yes, backdate `created_at` on edges where present (e.g., SUPERSEDES)
2. **Max limit:** No — it's a test tool
3. **valid_from/valid_to:** Yes, backdate on supersession chains for accurate chain traversal
4. **Gating:** Must NOT be exposed in beta/prod (see below)

## Production Gating (CRITICAL)

This tool must never be callable in beta or production. Options:

### Option A: Environment gate (Recommended)
```python
# settings.py
test_tools_enabled: bool = Field(
    default=False,
    description="Enable test-only MCP tools. MUST be False in beta/prod."
)

# test_advance_time.py
if not settings.test_tools_enabled:
    return {"status": "error", "error": "disabled", "message": "Test tools not enabled"}
```

Set `TEST_TOOLS_ENABLED=true` only in:
- Local dev (`.env`)
- CI/CD test runs
- Somnus test environments

### Option B: Conditional registration
```python
# mcp/tools/__init__.py
def register_all(mcp: FastMCP) -> None:
    # ... normal tools ...
    
    if settings.test_tools_enabled:
        from context_service.mcp.tools.test_advance_time import register as register_test_advance_time
        register_test_advance_time(mcp)
```

This way the tool doesn't even appear in the schema for beta/prod.

**Recommendation:** Both A + B. Don't register in prod, AND check at runtime as defense in depth.
