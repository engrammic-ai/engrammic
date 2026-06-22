# Brain Cutover and Quality Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire MCP tools to brain transactions (sage/transactions.py) instead of legacy ContextService, enable coverage reporting in CI.

**Architecture:** MCP handlers call brain transactions directly, which emit ReactionEvents to the Taskiq worker. Legacy ContextService methods remain but are no longer called from MCP surface.

**Tech Stack:** Python 3.12, FastMCP, sage/transactions.py, Taskiq reactions, pytest-cov

**Spec:** `docs/superpowers/specs/2026-06-03-brain-cutover-and-quality-fixes-design.md`

---

## File Structure

**Modify:**
- `pyproject.toml` — add coverage to pytest addopts
- `src/context_service/sage/transactions.py` — add `layer` param to `store_memory()`
- `src/context_service/mcp/tools/context_store.py` — rewire handlers to brain transactions
- `tests/e2e/test_mcp_tools.py` — update helpers and remove skip

**Create:**
- `.coveragerc` — coverage configuration
- `tests/integration/test_brain_cutover.py` — integration tests for cutover validation

---

## Phase 1: Coverage Wiring

### Task 1: Add coverage to pytest

**Files:**
- Modify: `pyproject.toml:140-145`
- Create: `.coveragerc`

- [ ] **Step 1: Update pyproject.toml addopts**

```toml
# In [tool.pytest.ini_options], change addopts to:
addopts = "--import-mode=importlib --cov=src --cov-report=term-missing --cov-report=html"
```

- [ ] **Step 2: Create .coveragerc**

```ini
[run]
source = src
omit =
    src/context_service/__main__.py
    src/context_service/entrypoint.py
    */__pycache__/*
    */tests/*

[report]
exclude_lines =
    pragma: no cover
    if TYPE_CHECKING:
    raise NotImplementedError
    @abstractmethod

[html]
directory = htmlcov
```

- [ ] **Step 3: Verify coverage runs**

Run: `uv run pytest tests/unit/test_config.py -v --no-cov`
Then: `uv run pytest tests/unit/test_config.py -v`
Expected: Coverage report appears in terminal output

- [ ] **Step 4: Add htmlcov to .gitignore if not present**

```bash
grep -q "htmlcov" .gitignore || echo "htmlcov/" >> .gitignore
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .coveragerc .gitignore
git commit -m "feat: wire coverage reporting into pytest"
```

---

## Phase 2: Brain Cutover

### Task 2: Add layer param to store_memory

**Files:**
- Modify: `src/context_service/sage/transactions.py:563-575`

- [ ] **Step 1: Update store_memory signature**

In `transactions.py`, add `layer` parameter:

```python
async def store_memory(
    store: HyperGraphStore,
    content: str,
    silo_id: str,
    agent_id: str,
    *,
    layer: str = "memory",  # ADD THIS LINE
    tags: list[str] | None = None,
    content_type: str = "text",
    decay_class: str = "standard",
    metadata: dict[str, Any] | None = None,
    emit: bool = True,
) -> tuple[StoreMemoryResult, list[ReactionEvent]]:
```

- [ ] **Step 2: Use layer param in props**

Update the props dict around line 599:

```python
    props: dict[str, Any] = {
        "layer": layer,  # CHANGE FROM "memory" to layer
        "state": NodeState.ACTIVE.value,
        "content_type": content_type,
        "decay_class": decay_class,
        "created_by": agent_id,
        **(metadata or {}),
    }
```

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/sage/test_transactions.py -v -k store_memory`
Expected: PASS (existing tests don't specify layer, use default)

- [ ] **Step 4: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): add layer param to store_memory for reflect support"
```

### Task 3: Wire remember to store_memory

**Files:**
- Modify: `src/context_service/mcp/tools/context_store.py:229-298`

- [ ] **Step 1: Add imports at top of file**

After existing imports, add:

```python
from context_service.sage.transactions import (
    store_memory,
    store_claim,
    link as brain_link,
    commit as brain_commit,
    crystallize,
    revise_belief,
    forget as brain_forget,
)
from context_service.reactions.events import emit_reaction
```

- [ ] **Step 2: Rewrite _context_remember to use brain transaction**

Replace lines 262-275 (the ctx_svc.remember call) with:

```python
    ctx_svc = get_context_service()
    scope = ScopeContext(org_id=auth.org_id, silo_id=validated_silo_id)
    _start = time.perf_counter()
    
    result, events = await store_memory(
        store=ctx_svc.graph_store,
        content=content,
        silo_id=str(validated_silo_id),
        agent_id=auth.agent_id,
        layer="memory",
        tags=tags,
        content_type=content_type,
        decay_class=decay_class,
        metadata=metadata,
    )
    
    for event in events:
        await emit_reaction(event)
    
    record_store_latency(time.perf_counter() - _start, silo_id=validated_silo_id, layer="memory")
    node_id = result.node_id
```

- [ ] **Step 3: Update the supersession block**

Change line 279 from `await create_supersession(node.id, ...)` to:

```python
    if supersedes is not None:
        try:
            await create_supersession(node_id, supersedes, str(validated_silo_id))
        except SupersessionCycleError as e:
            # ... rest unchanged, but use node_id instead of node.id
```

- [ ] **Step 4: Update return dict**

Change line 291 from `"node_id": str(node.id)` to:

```python
    result: dict[str, Any] = {
        "node_id": str(node_id),
        "layer": "memory",
        # ... rest unchanged
    }
```

- [ ] **Step 5: Run unit tests**

Run: `uv run pytest tests/mcp/ -v -k remember --no-cov`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/tools/context_store.py
git commit -m "feat(mcp): wire remember to brain store_memory transaction"
```

### Task 4: Wire learn to store_claim

**Files:**
- Modify: `src/context_service/mcp/tools/context_store.py:301-400` (approximate)

- [ ] **Step 1: Find _context_assert function**

Locate the `_context_assert` function (handles `learn` tool).

- [ ] **Step 2: Replace ctx_svc.assert_claim with store_claim**

Find the `await ctx_svc.assert_claim(...)` call and replace with:

```python
    result, events = await store_claim(
        store=ctx_svc.graph_store,
        content=claim_text,
        evidence_refs=evidence_list,  # NOTE: evidence_refs not evidence_uris
        silo_id=str(expected_silo_id),
        agent_id=auth.agent_id,
        source_tier=source_tier,  # NOTE: source_tier not source_type
        confidence=confidence,
        tags=tags,
        metadata=metadata,
    )
    
    for event in events:
        await emit_reaction(event)
    
    node_id = result.node_id
```

- [ ] **Step 3: Update return and supersession to use node_id**

Replace references to `node.id` with `node_id`.

- [ ] **Step 4: Run unit tests**

Run: `uv run pytest tests/mcp/ -v -k "learn or assert" --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/context_store.py
git commit -m "feat(mcp): wire learn to brain store_claim transaction"
```

### Task 5: Wire believe to commit

**Files:**
- Modify: `src/context_service/mcp/tools/context_store.py`

- [ ] **Step 1: Find the believe handler**

Locate `_context_commit` or the function handling `believe` tool.

- [ ] **Step 2: Replace with brain_commit**

Replace the ContextService call with:

```python
    result, events = await brain_commit(
        store=ctx_svc.graph_store,
        content=content,
        about_refs=about_nodes,  # NOTE: about_refs not about_node_ids
        silo_id=str(validated_silo_id),
        agent_id=auth.agent_id,
        confidence=confidence,
        metadata=metadata,
    )
    
    for event in events:
        await emit_reaction(event)
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/mcp/ -v -k believe --no-cov`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/context_store.py
git commit -m "feat(mcp): wire believe to brain commit transaction"
```

### Task 6: Wire reflect to store_memory with layer=meta

**Files:**
- Modify: `src/context_service/mcp/tools/context_store.py:618+`

- [ ] **Step 1: Find _context_reflect function**

Locate the reflect handler.

- [ ] **Step 2: Replace with store_memory using layer="meta"**

```python
    result, events = await store_memory(
        store=ctx_svc.graph_store,
        content=content,
        silo_id=str(validated_silo_id),
        agent_id=auth.agent_id,
        layer="meta",  # KEY DIFFERENCE
        tags=tags,
        metadata=metadata,
    )
    
    for event in events:
        await emit_reaction(event)
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/mcp/ -v -k reflect --no-cov`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/context_store.py
git commit -m "feat(mcp): wire reflect to brain store_memory with layer=meta"
```

### Task 7: Wire remaining verbs (link, forget, commit-verb, revise)

**Note:** `hypothesize` transaction does not exist in sage/transactions.py. Mark as out-of-scope (requires new transaction work).

**Files:**
- Modify: `src/context_service/mcp/tools/context_store.py`

- [ ] **Step 1: Wire link handler**

Find link handler, replace ContextService call with:

```python
    result, events = await brain_link(
        store=ctx_svc.graph_store,
        from_node_id=from_node,
        to_node_id=to_node,
        link_type=relationship,
        silo_id=str(validated_silo_id),
        weight=weight,
        metadata=metadata,
    )
    for event in events:
        await emit_reaction(event)
```

- [ ] **Step 2: Wire forget handler**

```python
    result, events = await brain_forget(
        store=ctx_svc.graph_store,
        node_id=node_id,
        silo_id=str(validated_silo_id),
        reason=reason,
    )
    for event in events:
        await emit_reaction(event)
```

- [ ] **Step 3: Wire commit (verb) to crystallize**

The `commit` MCP verb (crystallizes hypotheses) maps to `crystallize()`:

```python
    result, events = await crystallize(
        store=ctx_svc.graph_store,
        hypothesis_id=hypothesis_id,
        silo_id=str(validated_silo_id),
        agent_id=auth.agent_id,
    )
    for event in events:
        await emit_reaction(event)
```

- [ ] **Step 4: Wire revise if exists**

```python
    result, events = await revise_belief(
        store=ctx_svc.graph_store,
        belief_id=belief_id,
        new_content=content,
        silo_id=str(validated_silo_id),
        agent_id=auth.agent_id,
        reason=reason,
    )
    for event in events:
        await emit_reaction(event)
```

- [ ] **Step 5: Run full MCP test suite**

Run: `uv run pytest tests/mcp/ -v --no-cov`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/tools/context_store.py
git commit -m "feat(mcp): wire link, forget, commit, revise to brain transactions"
```

---

## Phase 3: Integration Validation

### Task 8: Write integration test for cutover

**Files:**
- Create: `tests/integration/test_brain_cutover.py`

- [ ] **Step 1: Create test file**

```python
"""Integration tests validating MCP → brain transaction cutover."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from context_service.sage.transactions import store_memory, store_claim
from context_service.reactions.events import ReactionEventType


class TestBrainCutover:
    """Verify brain transactions emit correct events."""

    @pytest.mark.integration
    async def test_store_memory_emits_embedding_event(
        self, fake_graph_store, test_silo_id: str
    ) -> None:
        """store_memory should emit COMPUTE_EMBEDDING reaction."""
        result, events = await store_memory(
            store=fake_graph_store,
            content="Test observation",
            silo_id=test_silo_id,
            agent_id="test-agent",
        )

        assert result.node_id is not None
        event_types = [e.event_type for e in events]
        assert ReactionEventType.COMPUTE_EMBEDDING in event_types

    @pytest.mark.integration
    async def test_store_memory_with_meta_layer(
        self, fake_graph_store, test_silo_id: str
    ) -> None:
        """store_memory with layer=meta should work for reflect."""
        result, events = await store_memory(
            store=fake_graph_store,
            content="I was wrong about X",
            silo_id=test_silo_id,
            agent_id="test-agent",
            layer="meta",
        )

        assert result.node_id is not None

    @pytest.mark.integration
    async def test_store_claim_emits_events(
        self, fake_graph_store, test_silo_id: str
    ) -> None:
        """store_claim should emit embedding and corroboration events."""
        result, events = await store_claim(
            store=fake_graph_store,
            content="The API uses OAuth2",  # NOTE: content not claim
            evidence_refs=["file://docs/api.md"],  # NOTE: evidence_refs not evidence_uris
            silo_id=test_silo_id,
            agent_id="test-agent",
            source_tier="documentation",  # NOTE: source_tier not source_type
        )

        assert result.node_id is not None
        event_types = [e.event_type for e in events]
        assert ReactionEventType.COMPUTE_EMBEDDING in event_types
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/integration/test_brain_cutover.py -v --no-cov`
Expected: PASS (may need fixtures)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_brain_cutover.py
git commit -m "test: add integration tests for brain cutover validation"
```

---

## Phase 4: E2E Test Updates

### Task 9: Update E2E test helpers

**Files:**
- Modify: `tests/e2e/test_mcp_tools.py:1-60`

- [ ] **Step 1: Update module docstring**

```python
"""E2E tests for MCP verb surface.

All tests exercise the registered MCP tools via fastmcp Client.

Tool surface:
  remember  -- store observation (memory layer)
  learn     -- store claim with evidence (knowledge layer)
  believe   -- store commitment (wisdom layer)
  recall    -- retrieve nodes
  link      -- create relationships
  forget    -- request deletion
"""
```

- [ ] **Step 2: Remove the skip marker**

Delete this line:
```python
pytestmark = pytest.mark.skip(reason="Uses internal tool names; pending verb promotion refactor")
```

- [ ] **Step 3: Replace helper functions**

```python
async def remember(client: Any, content: str, **kwargs: Any) -> dict[str, Any]:
    raw = await client.call_tool("remember", {"content": content, **kwargs})
    return call_result(raw)


async def learn(
    client: Any, content: str, evidence: list[str], **kwargs: Any
) -> dict[str, Any]:
    raw = await client.call_tool(
        "learn", {"content": content, "evidence": evidence, **kwargs}
    )
    return call_result(raw)


async def believe(
    client: Any, content: str, about: list[str], **kwargs: Any
) -> dict[str, Any]:
    raw = await client.call_tool(
        "believe", {"content": content, "about": about, **kwargs}
    )
    return call_result(raw)


async def recall(client: Any, **kwargs: Any) -> dict[str, Any]:
    raw = await client.call_tool("recall", kwargs)
    return call_result(raw)


async def link(
    client: Any, from_node: str, to_node: str, relationship: str, **kwargs: Any
) -> dict[str, Any]:
    raw = await client.call_tool(
        "link",
        {"from_node": from_node, "to_node": to_node, "relationship": relationship, **kwargs},
    )
    return call_result(raw)
```

- [ ] **Step 4: Commit helpers update**

```bash
git add tests/e2e/test_mcp_tools.py
git commit -m "test(e2e): update helpers to use verb surface"
```

### Task 10: Update E2E test bodies

**Files:**
- Modify: `tests/e2e/test_mcp_tools.py:60+`

- [ ] **Step 1: Update TestStoreAllLayers**

Replace `store(client, "memory", ...)` calls with `remember(client, ...)`:

```python
class TestStoreAllLayers:
    async def test_store_memory(self, mcp_client: Any) -> None:
        result = await remember(mcp_client, "Agent booted at t=0")
        assert result.get("layer") == "memory"
        assert "node_id" in result

    async def test_store_knowledge(self, mcp_client: Any) -> None:
        result = await learn(
            mcp_client,
            "API rate limit is 1000/min",
            evidence=["file://docs/api.md"],
        )
        assert result.get("layer") == "knowledge"
        assert "node_id" in result
```

- [ ] **Step 2: Update recall tests for eventual consistency**

For tests that store then immediately query, use node_ids:

```python
    async def test_recall_by_id(self, mcp_client: Any) -> None:
        stored = await remember(mcp_client, "Test content")
        node_id = stored["node_id"]
        
        # Use node_ids for immediate recall (eventual consistency)
        result = await recall(mcp_client, node_ids=[node_id])
        assert len(result["results"]) == 1
```

- [ ] **Step 3: Update all remaining test classes**

Go through each test class and update:
- `store(..., layer="memory")` → `remember(...)`
- `store(..., layer="knowledge")` → `learn(..., evidence=[...])`
- `store(..., layer="wisdom")` → `believe(..., about=[...])`

- [ ] **Step 4: Run E2E tests**

Run: `uv run pytest tests/e2e/test_mcp_tools.py -v --no-cov`
Expected: PASS (or identify remaining fixes)

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_mcp_tools.py
git commit -m "test(e2e): update test bodies to use verb surface"
```

---

## Phase 5: Documentation

### Task 11: Document eventual consistency

**Files:**
- Modify: `src/context_service/config/mcp_tools.yaml` (tool descriptions)

- [ ] **Step 1: Update remember tool description**

Add to the description:

```yaml
remember:
  description: |
    Store an observation to memory. Returns immediately; node becomes 
    searchable within ~500ms (async embedding). For immediate recall, 
    use the returned node_id with recall(node_ids=[...]).
```

- [ ] **Step 2: Update learn tool description similarly**

- [ ] **Step 3: Commit**

```bash
git add src/context_service/config/mcp_tools.yaml
git commit -m "docs: add eventual consistency note to MCP tool descriptions"
```

---

## Final Validation

### Task 12: Run full test suite

- [ ] **Step 1: Run just ci**

Run: `just ci`
Expected: All checks pass, coverage report shows

- [ ] **Step 2: Verify reaction queue activity**

Start local stack and verify reactions are being emitted:
```bash
just up
# In another terminal, watch reaction queue
docker logs -f context-service-reaction-worker-1
```

Call remember via MCP, verify COMPUTE_EMBEDDING event appears in logs.

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address test suite issues from cutover"
```

---

## Success Criteria

1. `just ci` passes with coverage report
2. MCP writes emit ReactionEvents (visible in worker logs)
3. E2E tests pass without skip marker
4. No regressions in existing unit tests
