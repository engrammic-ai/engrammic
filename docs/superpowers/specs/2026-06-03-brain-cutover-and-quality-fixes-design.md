# Brain Cutover and Quality Fixes

**Date:** 2026-06-03  
**Status:** Design approved

## Goal

Complete the brain architecture migration by wiring MCP tools to brain transactions, fix quality gaps identified during codebase exploration.

## Background

Codebase exploration revealed:
1. Brain architecture (sage/transactions.py + Taskiq reactions) is built and deployed but MCP tools still route through legacy ContextService
2. Coverage never measured in CI (pytest-cov installed but not wired)
3. Timeout guards exist but only on escape-hatch methods; typed queries bypass them
4. MCP e2e tests use old `context_*` names, not current verb surface

## Design Decisions

**Eventual consistency accepted:** Stored nodes become searchable within ~500ms (async embedding via Taskiq reaction). This is acceptable; document it.

**MCP surface unchanged:** Tools remain `remember`, `learn`, `believe`, `recall`, etc. Only internal plumbing changes.

## Scope

### Phase 1: Quick Wins (2-4h)

#### 1.1 Wire coverage into CI

Add `--cov=src --cov-report=term-missing` to pytest:

```toml
# pyproject.toml [tool.pytest.ini_options]
addopts = "--import-mode=importlib --cov=src --cov-report=term-missing"
```

Add `.coveragerc` with source paths and omit patterns (tests, __pycache__).

#### 1.2 Timeout guards on typed queries

In `engine/memgraph_store.py`, wrap typed query methods with `asyncio.wait_for`:

```python
async def get_node(self, node_id: str, ...) -> Node | None:
    return await asyncio.wait_for(
        self._get_node_impl(node_id, ...),
        timeout=self._query_timeout  # default 30s
    )
```

Apply to all typed query methods that call `self._client` directly (approximately 50 methods). Start with the hot path: `get_node`, `get_nodes`, `get_neighbors`, `search_nodes`, `get_cluster_nodes`, `get_edges`, `get_incoming_edges`.

### Phase 2: Brain Cutover (4-8h)

#### 2.1 MCP handlers → brain transactions

In `mcp/tools/context_store.py`, replace ContextService calls:

| MCP Tool | Current | Target |
|----------|---------|--------|
| `remember` | `ctx_svc.remember()` | `sage.transactions.store_memory()` |
| `learn` | `ctx_svc.assert_claim()` | `sage.transactions.store_claim()` |
| `believe` | `ctx_svc.commit_belief()` | `sage.transactions.crystallize()` |
| `hypothesize` | `ctx_svc.hypothesize()` | `sage.transactions.hypothesize()` |
| `commit` | `ctx_svc.commit_hypotheses()` | `sage.transactions.commit()` |
| `link` | `ctx_svc.link()` | `sage.transactions.link()` |
| `forget` | `ctx_svc.forget()` | `sage.transactions.forget()` |
| `reflect` | `ctx_svc.reflect()` | `sage.transactions.store_memory()` with `is_meta=True` |

Each transaction returns `(result, events)`. After the transaction, emit events:

```python
result, events = await store_memory(...)
for event in events:
    await emit_reaction(event)
return {"node_id": result.node_id, ...}
```

#### 2.2 Document eventual consistency

Add to MCP tool descriptions and docs:

> Stored nodes become searchable within ~500ms. If you need to recall a just-stored node, use `node_ids` parameter with the returned `node_id` rather than a query.

### Phase 3: E2E Tests (2-4h)

#### 3.1 Update test helpers

In `tests/e2e/test_mcp_tools.py`, change:

```python
# OLD
await client.call_tool("context_store", {"content": ..., "layer": "memory"})

# NEW  
await client.call_tool("remember", {"content": ...})
```

Map old patterns to new:
- `context_store` with `layer="memory"` → `remember`
- `context_store` with `layer="knowledge"` → `learn`
- `context_store` with `layer="wisdom"` → `believe`
- `context_recall` → `recall`
- `context_link` → `link`

#### 3.2 Remove module skip

Delete `pytestmark = pytest.mark.skip(...)` line.

#### 3.3 Add eventual consistency handling

For tests that store then immediately recall by query, either:
- Use `node_ids` parameter to fetch by ID (immediate)
- Add brief delay for query-based recall tests

## Out of Scope

| Item | Reason |
|------|--------|
| context.py decomposition | Do after cutover when we see what's left |
| Raw-query refactor in transactions.py | Pattern tension, not a bug; 61 raw queries are escape-hatch compliant |
| Removing legacy ContextService methods | Keep for backward compatibility initially |

## Success Criteria

1. `just ci` includes coverage report
2. Typed Memgraph queries have timeout guards
3. MCP writes flow through brain transactions (verified via reaction queue activity)
4. E2E tests pass without skip marker
5. Documentation notes eventual consistency

## Risks

| Risk | Mitigation |
|------|------------|
| Brain transactions have edge case bugs | Existing unit tests cover most paths; integration tests validate |
| Reaction worker can't keep up | Monitor queue depth; worker is already deployed with 2 replicas |
| Tests flaky due to eventual consistency | Use node_id fetches, not queries, for immediate recall |

## Rollback

If brain cutover causes issues:
1. Revert MCP handler changes (ContextService calls still work)
2. Brain transactions and reactions remain available for re-attempt
