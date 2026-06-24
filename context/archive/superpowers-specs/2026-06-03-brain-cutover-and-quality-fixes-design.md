# Brain Cutover and Quality Fixes

**Date:** 2026-06-03  
**Status:** Design revised after review

## Goal

Complete the brain architecture migration by wiring MCP tools to brain transactions, fix quality gaps identified during codebase exploration.

## Background

Codebase exploration revealed:
1. Brain architecture (sage/transactions.py + Taskiq reactions) is built and deployed but MCP tools still route through legacy ContextService
2. Coverage never measured in CI (pytest-cov installed but not wired)
3. Timeout guards exist but only on escape-hatch methods; typed queries bypass them
4. MCP e2e tests use old `context_*` names, not current verb surface

## Design Decisions

**Eventual consistency accepted:** Stored nodes become searchable within ~500ms best-case (async embedding via Taskiq reaction). Not an SLA; depends on worker load. Document this.

**MCP surface unchanged:** Tools remain `remember`, `learn`, `believe`, `recall`, etc. Only internal plumbing changes.

## Scope

### Phase 1: Quick Wins (1-2h)

#### 1.1 Wire coverage into CI

Add `--cov=src --cov-report=term-missing` to pytest:

```toml
# pyproject.toml [tool.pytest.ini_options]
addopts = "--import-mode=importlib --cov=src --cov-report=term-missing"
```

Add `.coveragerc` with source paths and omit patterns (tests, __pycache__).

#### 1.2 Timeout guards — SEPARATE PR

Move to separate PR to avoid bloating the cutover changeset. Track as follow-up.

### Phase 2: Brain Cutover (4-8h)

#### 2.1 MCP handlers → brain transactions

In `mcp/tools/context_store.py`, replace ContextService calls:

| MCP Tool | Current | Target | Notes |
|----------|---------|--------|-------|
| `remember` | `ctx_svc.remember()` | `store_memory()` | |
| `learn` | `ctx_svc.assert_claim()` | `store_claim()` | |
| `believe` | `ctx_svc.commit_belief()` | `commit()` | Direct belief commitment |
| `hypothesize` | `ctx_svc.hypothesize()` | `hypothesize()` | Creates WorkingHypothesis |
| `commit` (verb) | `ctx_svc.commit_hypotheses()` | `crystallize()` | WorkingHypothesis → Commitment |
| `link` | `ctx_svc.link()` | `link()` | |
| `forget` | `ctx_svc.forget()` | `forget()` | |
| `revise` | `ctx_svc.revise()` | `revise()` | Updates tentative belief |
| `reflect` | `ctx_svc.reflect()` | `store_memory()` | **Requires `layer` param addition** |
| `reason` | `ctx_svc.reason()` | Out of scope | Intelligence layer, separate flow |

**Note on `reflect`:** `store_memory()` currently has no `layer` or `is_meta` parameter. Add `layer: str = "memory"` param to support `layer="meta"` for reflections.

Each transaction returns `(result, events)`. After the transaction, emit events:

```python
result, events = await store_memory(...)
for event in events:
    await emit_reaction(event)
return {"node_id": result.node_id, ...}
```

#### 2.2 Document eventual consistency

Add to MCP tool descriptions and docs:

> Stored nodes become searchable within ~500ms under normal load (async embedding). This is best-effort, not guaranteed. If you need to recall a just-stored node immediately, use the `node_ids` parameter with the returned `node_id` rather than a query.

### Phase 3: Integration Validation (2-4h)

#### 3.1 Integration tests for cutover

Before touching E2E tests, verify cutover works:
- Write integration tests that call brain transactions directly
- Verify reaction events are emitted and processed
- Confirm nodes appear in Qdrant after worker processes

#### 3.2 Shadow comparison (optional)

If higher confidence needed: run both paths, compare results, log discrepancies. Adds complexity; skip if unit/integration coverage is sufficient.

### Phase 4: E2E Tests (2-4h)

#### 4.1 Update test helpers

In `tests/e2e/test_mcp_tools.py`, update ALL helper functions (lines 29-54):

```python
# OLD
async def store(client, layer, content, **kwargs):
    return await client.call_tool("context_store", {"content": content, "layer": layer, **kwargs})

# NEW  
async def remember(client, content, **kwargs):
    return await client.call_tool("remember", {"content": content, **kwargs})

async def learn(client, content, evidence, **kwargs):
    return await client.call_tool("learn", {"content": content, "evidence": evidence, **kwargs})
```

#### 4.2 Update test bodies

Map old patterns to new verbs in all test functions:
- `store(..., layer="memory")` → `remember(...)`
- `store(..., layer="knowledge")` → `learn(...)`
- `store(..., layer="wisdom")` → `believe(...)`
- `recall(...)` → `recall(...)`
- `link(...)` → `link(...)`

#### 4.3 Remove module skip

Delete `pytestmark = pytest.mark.skip(...)` line AFTER helpers and tests are updated.

#### 4.4 Handle eventual consistency in tests

For tests that store then immediately recall by query:
- Use `node_ids` parameter to fetch by ID (immediate)
- Or add `await asyncio.sleep(0.6)` before query-based recall

## Out of Scope

| Item | Reason |
|------|--------|
| `reason` tool cutover | Intelligence layer has separate flow, not store-based |
| context.py decomposition | Do after cutover when we see what's left |
| Raw-query refactor in transactions.py | Pattern tension, not a bug |
| Timeout guards | Separate PR to avoid bloating changeset |
| Feature flag / A-B routing | Adds complexity; rollback is straightforward |

## Success Criteria

1. `just ci` includes coverage report
2. MCP writes flow through brain transactions (verified via reaction queue activity)
3. Integration tests validate cutover before E2E changes
4. E2E tests pass without skip marker
5. Documentation notes eventual consistency

## Risks

| Risk | Mitigation |
|------|------------|
| Brain transactions have edge case bugs | Integration tests before E2E changes |
| Reaction worker can't keep up | Monitor queue depth; 2 replicas deployed |
| Tests flaky due to eventual consistency | Use node_id fetches, not queries |
| In-flight reactions during cutover | Worker handles both old and new events; no special drain needed |

## Rollback

If brain cutover causes issues:
1. Revert MCP handler changes (ContextService calls still work)
2. Brain transactions and reactions remain available for re-attempt
3. No database migration; both paths write same schema

## Follow-up PRs

1. **Timeout guards** — Wrap typed Memgraph query methods with `asyncio.wait_for`
2. **context.py decomposition** — After cutover, assess what's left in ContextService
