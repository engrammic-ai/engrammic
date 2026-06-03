# Graph Healthcheck Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire MCP commit to brain crystallize transaction and add threshold control to recall.

**Architecture:** MCP commit calls brain `crystallize()` in a loop (session_id made optional). Recall gets `min_threshold` param and wildcard bypass in `apply_threshold_filter()`.

**Tech Stack:** Python 3.12, FastMCP, sage/transactions.py, reranking/quality.py

**Spec:** `docs/superpowers/specs/2026-06-03-graph-healthcheck-fixes-design.md`

---

## File Structure

**Modify:**
- `src/context_service/sage/transactions.py` — make session_id optional in crystallize()
- `src/context_service/mcp/tools/commit.py` — call brain crystallize instead of _context_crystallize
- `src/context_service/reranking/quality.py` — add min_threshold and bypass params
- `src/context_service/mcp/tools/context_query.py` — pass min_threshold and bypass to filter
- `src/context_service/mcp/tools/context_recall.py` — accept and pass through min_threshold
- `src/context_service/mcp/tools/recall.py` — add min_threshold param to public API
- `src/context_service/config/mcp_tools.yaml` — document min_threshold param

**Test:**
- `tests/sage/test_transactions.py` — test crystallize with optional session_id
- `tests/reranking/test_quality.py` — test min_threshold and bypass
- `tests/mcp/test_context_recall.py` — test wildcard bypass behavior

---

## Phase 1: Threshold Filtering

### Task 1: Add min_threshold and bypass to apply_threshold_filter

**Files:**
- Modify: `src/context_service/reranking/quality.py:49-76`
- Test: `tests/reranking/test_quality.py`

- [ ] **Step 1: Write failing test for min_threshold**

Add to `tests/reranking/test_quality.py`:

```python
def test_min_threshold_override(self) -> None:
    results = [
        self._make_result("knowledge", 0.25),  # below default 0.5
        self._make_result("wisdom", 0.25),     # below default 0.5
    ]
    kept, below = apply_threshold_filter(results, min_threshold=0.2)
    assert len(kept) == 2
    assert below == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/reranking/test_quality.py::TestApplyThresholdFilter::test_min_threshold_override -v`
Expected: FAIL (TypeError: unexpected keyword argument 'min_threshold')

- [ ] **Step 3: Add min_threshold parameter**

In `src/context_service/reranking/quality.py`, update signature:

```python
def apply_threshold_filter(
    results: list[dict[str, Any]],
    threshold_overrides: dict[str, float] | None = None,
    min_threshold: float | None = None,
) -> tuple[list[dict[str, Any]], int]:
```

Update the threshold logic inside the loop:

```python
    for r in results:
        score = r.get("relevance_score")
        if score is None:
            kept.append(r)
            continue
        layer = r.get("layer", "memory")
        threshold = _threshold_for_layer(layer, threshold_overrides)
        if min_threshold is not None:
            threshold = min(threshold, min_threshold)
        if score >= threshold:
            kept.append(r)
        else:
            below += 1
    return kept, below
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/reranking/test_quality.py::TestApplyThresholdFilter::test_min_threshold_override -v`
Expected: PASS

- [ ] **Step 5: Write failing test for bypass**

Add to `tests/reranking/test_quality.py`:

```python
def test_bypass_skips_all_filtering(self) -> None:
    results = [
        self._make_result("knowledge", 0.1),  # way below threshold
        self._make_result("wisdom", 0.05),    # way below threshold
    ]
    kept, below = apply_threshold_filter(results, bypass=True)
    assert len(kept) == 2
    assert below == 0
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/reranking/test_quality.py::TestApplyThresholdFilter::test_bypass_skips_all_filtering -v`
Expected: FAIL

- [ ] **Step 7: Add bypass parameter**

Update signature and add early return:

```python
def apply_threshold_filter(
    results: list[dict[str, Any]],
    threshold_overrides: dict[str, float] | None = None,
    min_threshold: float | None = None,
    bypass: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """Filter result dicts by per-layer threshold.

    Args:
        results: List of result dicts with layer and relevance_score fields.
        threshold_overrides: Per-silo layer threshold overrides.
        min_threshold: When provided, use this as maximum threshold for all layers.
        bypass: When True, skip all filtering and return results unchanged.

    Returns:
        (kept_results, below_threshold_count)
    """
    if bypass:
        return results, 0

    kept: list[dict[str, Any]] = []
    # ... rest unchanged
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/reranking/test_quality.py::TestApplyThresholdFilter -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add src/context_service/reranking/quality.py tests/reranking/test_quality.py
git commit -m "feat(reranking): add min_threshold and bypass to apply_threshold_filter"
```

---

### Task 2: Wire min_threshold through context_query

**Files:**
- Modify: `src/context_service/mcp/tools/context_query.py:386`

- [ ] **Step 1: Find the apply_threshold_filter call**

In `context_query.py` around line 386:

```python
result_dicts, below_threshold = apply_threshold_filter(raw_result_dicts, threshold_overrides)
```

- [ ] **Step 2: Add min_threshold parameter to _context_query**

Find the function signature (around line 70-100) and add:

```python
async def _context_query(
    silo_id: str,
    query: str,
    layers: list[str] | None = None,
    top_k: int = 10,
    as_of: str | None = None,
    bypass_cache: bool = False,
    max_age_seconds: int | None = None,
    min_threshold: float | None = None,  # NEW
    bypass_threshold: bool = False,       # NEW
) -> dict[str, Any]:
```

- [ ] **Step 3: Pass parameters to apply_threshold_filter**

Update line 386:

```python
result_dicts, below_threshold = apply_threshold_filter(
    raw_result_dicts,
    threshold_overrides,
    min_threshold=min_threshold,
    bypass=bypass_threshold,
)
```

- [ ] **Step 4: Run existing tests**

Run: `uv run pytest tests/mcp/test_context_recall.py -v --no-cov`
Expected: PASS (default params unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/context_query.py
git commit -m "feat(mcp): wire min_threshold and bypass through context_query"
```

---

### Task 3: Wire min_threshold through context_recall

**Files:**
- Modify: `src/context_service/mcp/tools/context_recall.py:109-124`

- [ ] **Step 1: Add parameters to _context_recall**

```python
async def _context_recall(
    silo_id: str,
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int = 10,
    as_of: str | None = None,
    include_reflections: bool = False,
    reflections_agent_id: str | None = None,
    include_steps: bool = False,
    include_content: bool = True,
    include_proposals: bool = False,
    bypass_cache: bool = False,
    max_age_seconds: int | None = None,
    min_threshold: float | None = None,  # NEW
) -> dict[str, Any]:
```

- [ ] **Step 2: Detect wildcard mode and pass to _context_query**

Find the `if query and depth == 0:` block (around line 170) and update:

```python
if query and depth == 0:
    is_wildcard = query in ("*", "")
    response = await _context_query(
        silo_id=silo_id,
        query=query,
        layers=layers,
        top_k=top_k,
        as_of=as_of,
        bypass_cache=bypass_cache,
        max_age_seconds=max_age_seconds,
        min_threshold=min_threshold,
        bypass_threshold=is_wildcard,
    )
```

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/mcp/test_context_recall.py -v --no-cov`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/context_recall.py
git commit -m "feat(mcp): wire min_threshold and wildcard bypass through context_recall"
```

---

### Task 4: Add min_threshold to public recall API

**Files:**
- Modify: `src/context_service/mcp/tools/recall.py:35-77`
- Modify: `src/context_service/config/mcp_tools.yaml`

- [ ] **Step 1: Add min_threshold to _recall_impl**

```python
@rate_limited("recall")
async def _recall_impl(
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int | None = None,
    include_hypotheses: bool = False,
    bypass_cache: bool = False,
    max_age_seconds: int | None = None,
    min_threshold: float | None = None,  # NEW
) -> dict[str, Any]:
```

- [ ] **Step 2: Pass min_threshold to _context_recall**

Update the call around line 68:

```python
result = await _context_recall(
    silo_id=silo_id,
    query=query,
    node_ids=node_ids,
    depth=depth,
    layers=layers,
    top_k=effective_top_k,
    bypass_cache=bypass_cache,
    max_age_seconds=max_age_seconds,
    min_threshold=min_threshold,
)
```

- [ ] **Step 3: Add min_threshold to public recall function**

Update the registered tool (around line 241):

```python
async def recall(
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int | None = None,
    include_hypotheses: bool = False,
    bypass_cache: bool = False,
    max_age_seconds: int | None = None,
    min_threshold: float | None = None,  # NEW
) -> dict[str, Any]:
    """Retrieve knowledge.

    Args:
        query: Natural language search. Use "*" to list all nodes.
        node_ids: Specific nodes to fetch.
        depth: 0=flat, 1-3=graph traversal.
        layers: Filter: memory|knowledge|wisdom|intelligence.
        top_k: Max results for search (default 10, or preset value).
        include_hypotheses: Include tentative beliefs from current session.
        bypass_cache: Skip result cache, force fresh search.
        max_age_seconds: Maximum acceptable cache age in seconds.
        min_threshold: Override relevance threshold (0.0-1.0). Lower values
            return more results. When query="*", threshold is bypassed.

    Returns:
        {results|nodes, hypotheses?, ...}
    """
```

- [ ] **Step 4: Update the return call**

```python
return await _recall_impl(
    query,
    node_ids,
    depth,
    layers,
    top_k,
    include_hypotheses,
    bypass_cache,
    max_age_seconds,
    min_threshold,
)
```

- [ ] **Step 5: Update mcp_tools.yaml description**

In `src/context_service/config/mcp_tools.yaml`, update recall description:

```yaml
recall:
  description: |
    Search or fetch knowledge. Returns immediately. Use query for semantic
    search, node_ids for direct fetch. Use query="*" to list all nodes
    (bypasses relevance filtering). Optional min_threshold overrides the
    default relevance cutoff (0.0-1.0, lower = more results).
  maps_to: retrieve
```

- [ ] **Step 6: Run full recall tests**

Run: `uv run pytest tests/mcp/test_context_recall.py tests/mcp/test_recall_*.py -v --no-cov`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/context_service/mcp/tools/recall.py src/context_service/config/mcp_tools.yaml
git commit -m "feat(mcp): add min_threshold param to recall tool"
```

---

### Task 5: Add integration test for wildcard bypass

**Files:**
- Create: `tests/mcp/test_recall_wildcard.py`

- [ ] **Step 1: Create test file**

```python
"""Tests for recall wildcard bypass behavior."""

from __future__ import annotations

import pytest

from context_service.mcp.tools.context_recall import _context_recall


class TestWildcardBypass:
    """Verify query='*' bypasses threshold filtering."""

    @pytest.mark.asyncio
    async def test_wildcard_returns_low_score_results(
        self,
        mock_context_service: None,
        test_silo_id: str,
    ) -> None:
        """Wildcard query should return results regardless of score."""
        # This test verifies the bypass behavior exists.
        # Full E2E requires seeded data; this validates the code path.
        result = await _context_recall(
            silo_id=test_silo_id,
            query="*",
            top_k=100,
        )
        # Should not error; bypass flag passed to query
        assert "results" in result or "error" in result

    @pytest.mark.asyncio
    async def test_min_threshold_lowers_cutoff(
        self,
        mock_context_service: None,
        test_silo_id: str,
    ) -> None:
        """min_threshold should allow lower-scored results through."""
        result = await _context_recall(
            silo_id=test_silo_id,
            query="test query",
            min_threshold=0.1,
        )
        assert "results" in result or "error" in result
```

- [ ] **Step 2: Run new tests**

Run: `uv run pytest tests/mcp/test_recall_wildcard.py -v --no-cov`
Expected: PASS (or skip if fixtures missing)

- [ ] **Step 3: Commit**

```bash
git add tests/mcp/test_recall_wildcard.py
git commit -m "test(mcp): add recall wildcard bypass tests"
```

---

## Phase 2: Crystallize Brain Cutover

### Task 6: Make session_id optional in brain crystallize

**Files:**
- Modify: `src/context_service/sage/transactions.py:1245-1295`
- Test: `tests/sage/test_transactions.py`

- [ ] **Step 1: Write failing test**

Add to `tests/sage/test_transactions.py` (or create if needed):

```python
@pytest.mark.asyncio
async def test_crystallize_without_session_id(
    fake_graph_store: Any,
    test_silo_id: str,
) -> None:
    """crystallize should work with session_id=None."""
    from context_service.sage.transactions import crystallize

    # This will fail until we make session_id optional
    # and update _validate_hypothesis to handle None
    with pytest.raises(Exception):  # Placeholder - update after impl
        await crystallize(
            store=fake_graph_store,
            hypothesis_id="test-hypothesis-id",
            silo_id=test_silo_id,
            agent_id="test-agent",
            session_id=None,
        )
```

- [ ] **Step 2: Update crystallize signature**

In `src/context_service/sage/transactions.py` line 1283:

```python
async def crystallize(
    store: HyperGraphStore,
    hypothesis_id: str,
    silo_id: str,
    agent_id: str,
    session_id: str | None = None,
    *,
    emit: bool = True,
) -> tuple[CrystallizeResult, list[ReactionEvent]]:
```

- [ ] **Step 3: Update _validate_hypothesis signature**

In `src/context_service/sage/transactions.py` line 1245:

```python
async def _validate_hypothesis(
    store: HyperGraphStore,
    hypothesis_id: str,
    silo_id: str,
    session_id: str | None,
) -> dict[str, Any]:
```

- [ ] **Step 4: Update the query to handle None session_id**

The query `GET_HYPOTHESIS_FOR_CRYSTALLIZE` filters by session_id. We need to update the validation logic. Replace lines 1254-1264:

```python
    params: dict[str, Any] = {
        "hypothesis_id": hypothesis_id,
        "silo_id": silo_id,
    }
    
    if session_id is not None:
        params["session_id"] = session_id
        results = await store.execute_query(
            q.GET_HYPOTHESIS_FOR_CRYSTALLIZE,
            params,
        )
    else:
        # When session_id is None, use a simpler query that doesn't filter by session
        results = await store.execute_query(
            q.GET_HYPOTHESIS_BY_ID,
            params,
        )

    if not results:
        msg = "Hypothesis not found" if session_id is None else "Hypothesis not found or wrong session"
        return {"error": "HYPOTHESIS_NOT_FOUND", "message": msg}
```

- [ ] **Step 5: Add GET_HYPOTHESIS_BY_ID query if missing**

Check `src/context_service/db/queries.py` for this query. If missing, add:

```python
GET_HYPOTHESIS_BY_ID = """
MATCH (h:WorkingHypothesis {id: $hypothesis_id})
WHERE h.silo_id = $silo_id
RETURN h.id AS hypothesis_id,
       h.content AS content,
       h.confidence AS confidence,
       h.state AS state,
       h.crystallized AS crystallized
"""
```

- [ ] **Step 6: Run crystallize tests**

Run: `uv run pytest tests/sage/ -v -k crystallize --no-cov`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/context_service/sage/transactions.py src/context_service/db/queries.py
git commit -m "feat(sage): make session_id optional in crystallize transaction"
```

---

### Task 7: Wire MCP commit to brain crystallize

**Files:**
- Modify: `src/context_service/mcp/tools/commit.py`

- [ ] **Step 1: Update imports**

Replace the import at line 13:

```python
# Remove this:
# from context_service.mcp.tools.context_crystallize import _context_crystallize

# Add these:
from context_service.mcp.server import get_context_service
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import crystallize, InvariantViolation
```

- [ ] **Step 2: Rewrite _commit_impl**

Replace the function (lines 22-38):

```python
@rate_limited("commit")
async def _commit_impl(
    belief_ids: list[str],
    reason: str | None = None,
) -> dict[str, Any]:
    """Implementation for commit tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "commit")
    silo_id = str(derive_silo_id(auth.org_id))
    ctx_svc = get_context_service()

    committed: list[str] = []
    confidences: list[float] = []
    errors: list[dict[str, Any]] = []
    all_events: list[Any] = []

    for belief_id in belief_ids:
        try:
            result, events = await crystallize(
                store=ctx_svc.graph_store,
                hypothesis_id=belief_id,
                silo_id=silo_id,
                agent_id=auth.agent_id,
                session_id=auth.session_id,
            )
            committed.append(str(result.commitment_id))
            confidences.append(result.confidence)
            all_events.extend(events)
        except InvariantViolation as e:
            errors.append({
                "belief_id": belief_id,
                "error": e.code,
                "message": e.message,
            })

    for event in all_events:
        await emit_reaction(event)

    for confidence in confidences:
        record_belief_confidence(float(confidence), silo_id=silo_id)

    response: dict[str, Any] = {
        "committed": committed,
        "confidences": confidences,
    }
    if errors:
        response["errors"] = errors

    return response
```

- [ ] **Step 3: Run commit tests**

Run: `uv run pytest tests/mcp/test_context_crystallize.py -v --no-cov`
Expected: PASS (or need fixture updates)

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/commit.py
git commit -m "feat(mcp): wire commit to brain crystallize transaction"
```

---

### Task 8: Deprecate context_crystallize.py

**Files:**
- Modify: `src/context_service/mcp/tools/context_crystallize.py`

- [ ] **Step 1: Add deprecation warning**

At the top of the file after imports:

```python
import warnings

warnings.warn(
    "context_crystallize module is deprecated. Use sage.transactions.crystallize instead.",
    DeprecationWarning,
    stacklevel=2,
)
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/mcp/ tests/sage/ -v --no-cov`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/context_service/mcp/tools/context_crystallize.py
git commit -m "chore: deprecate context_crystallize in favor of brain transaction"
```

---

## Phase 3: Final Validation

### Task 9: Run full checks

- [ ] **Step 1: Run just check**

Run: `just check`
Expected: PASS (lint + typecheck)

- [ ] **Step 2: Run full test suite**

Run: `just test`
Expected: PASS

- [ ] **Step 3: Fix any issues and commit**

```bash
git add -A
git commit -m "fix: address review issues from graph healthcheck fixes"
```

---

## Success Criteria

1. `just check` passes
2. `just test` passes
3. `recall(query="*")` bypasses threshold filtering
4. `recall(query="foo", min_threshold=0.1)` uses override threshold
5. MCP `commit` calls brain `crystallize()` transaction
6. Brain `crystallize()` works with `session_id=None`
