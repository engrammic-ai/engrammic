# Graph Healthcheck Fixes Design

**Date:** 2026-06-03  
**Status:** Draft  
**Goal:** Fix confirmed issues from graph healthcheck: crystallize brain cutover and recall threshold filtering.

## Background

A graph healthcheck identified several issues. After false-positive analysis:

| Issue | Verdict |
|-------|---------|
| LinkType enum mismatch | False positive (intentional design) |
| Reflect schema drift | False positive (no validation, any type accepted) |
| Revise semantic gap | False positive (different operations) |
| Crystallize signature mismatch | **True issue** |
| Threshold filtering | **True issue** |

## Scope

1. Wire MCP `commit` tool to brain `crystallize()` transaction
2. Add threshold control to recall (min_threshold param + wildcard bypass)

---

## 1. Wire commit to brain crystallize

### Current State

- Brain `crystallize()` takes `hypothesis_id: str` (singular) and requires `session_id`
- MCP `_context_crystallize()` takes `belief_ids: list[str]` (plural), no session_id
- MCP uses `CRYSTALLIZE_TO_COMMITMENT` query directly, bypassing brain transaction

### Design

Make `session_id` optional in brain transaction with fallback to `agent_id`. MCP `commit` calls brain `crystallize()` in a loop for each belief_id.

### Changes

**src/context_service/sage/transactions.py**

Update signature:
```python
async def crystallize(
    store: HyperGraphStore,
    hypothesis_id: str,
    silo_id: str,
    agent_id: str,
    session_id: str | None = None,  # Make optional
    *,
    emit: bool = True,
) -> tuple[CrystallizeResult, list[ReactionEvent]]:
```

Use `session_id or agent_id` where session_id is referenced.

**src/context_service/mcp/tools/commit.py**

Replace call to `_context_crystallize` with:
```python
from context_service.sage.transactions import crystallize

results = []
events = []
for belief_id in belief_ids_list:
    result, evts = await crystallize(
        store=ctx_svc.graph_store,
        hypothesis_id=belief_id,
        silo_id=silo_id,
        agent_id=auth.agent_id,
        session_id=auth.session_id,  # May be None
    )
    results.append(result)
    events.extend(evts)

for event in events:
    await emit_reaction(event)
```

**src/context_service/mcp/tools/context_crystallize.py**

Deprecate or delete. If other code depends on it, add deprecation warning.

---

## 2. Threshold filtering improvements

### Current State

- Knowledge/Wisdom threshold: 0.5
- Memory threshold: 0.3
- Wildcard queries get low semantic scores, causing K/W nodes to be filtered out

### Design

1. Add optional `min_threshold` parameter to recall
2. Bypass filtering entirely for wildcard queries (`query="*"` or empty with no node_ids)

### Changes

**src/context_service/mcp/tools/recall.py**

Add parameter:
```python
async def recall(
    query: str | None = None,
    node_ids: list[str] | str | None = None,
    # ... existing params ...
    min_threshold: float | None = None,  # NEW
) -> dict[str, Any]:
```

**src/context_service/mcp/tools/context_recall.py**

Pass `min_threshold` through to the quality filter. Detect wildcard mode:
```python
is_wildcard = (query in (None, "", "*")) and not node_ids
```

**src/context_service/reranking/quality.py**

Update `apply_threshold_filter()`:
```python
def apply_threshold_filter(
    results: list[dict[str, Any]],
    threshold_overrides: dict[str, float] | None = None,
    min_threshold: float | None = None,  # NEW
    bypass: bool = False,  # NEW - for wildcard mode
) -> tuple[list[dict[str, Any]], int]:
    if bypass:
        return results, 0
    # ... rest of logic, use min_threshold if provided
```

**src/context_service/config/mcp_tools.yaml**

Update recall description to document new parameter.

### Behavior Matrix

| Query | node_ids | min_threshold | Behavior |
|-------|----------|---------------|----------|
| "API auth" | None | None | Normal (0.5 K/W, 0.3 M) |
| "API auth" | None | 0.2 | Use 0.2 for all |
| "*" | None | None | No filtering |
| None | [ids] | None | No filtering (direct lookup) |

---

## Testing

1. Unit tests for `crystallize()` with optional session_id
2. Unit tests for `apply_threshold_filter()` with min_threshold and bypass
3. E2E test: commit via MCP, verify brain transaction called
4. E2E test: recall with `query="*"` returns K/W nodes

## Success Criteria

1. `just check` passes
2. MCP `commit` emits ReactionEvents from brain transaction
3. `recall(query="*")` returns nodes from all layers
4. `recall(query="foo", min_threshold=0.1)` uses override
