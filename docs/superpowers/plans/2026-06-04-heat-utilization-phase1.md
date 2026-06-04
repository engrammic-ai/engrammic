# Heat Utilization Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix long-horizon memory recall and reduce token usage for the Somnus benchmark.

**Architecture:** Two changes: (1) Brain path decay floor - reuse `compute_freshness` from `signals/freshness.py` in `sage/recall.py` to apply floor + weighted blend. (2) Tier-driven summary default - COLD nodes return summary instead of full content unless explicitly requested.

**Tech Stack:** Python 3.12, pytest, existing `compute_freshness` function, existing `_project_node_without_content` helper.

---

## File Structure

**Modified files:**
- `src/context_service/sage/recall.py` - Add decay floor to `compute_recall_score`
- `src/context_service/mcp/tools/context_recall.py` - Add tier-driven content logic
- `tests/sage/test_recall.py` - Add decay floor tests
- `tests/integration/test_context_recall_content.py` - Add tier-driven tests

**No new files needed** - all changes extend existing modules.

---

## Task 1: Brain Path Decay Floor Tests

**Files:**
- Modify: `tests/sage/test_recall.py`

- [ ] **Step 1: Add test for year-old memory retaining score**

```python
# Add to TestComputeRecallScore class in tests/sage/test_recall.py

def test_memory_layer_old_node_retains_floor_score(self) -> None:
    """A 365-day-old memory should retain ~77% of similarity, not ~0%."""
    old_node = {
        "layer": Layer.MEMORY,
        "confidence": 1.0,
        "created_at": datetime.now(UTC) - timedelta(days=365),
    }
    score = compute_recall_score(old_node, similarity=1.0)
    # With floor=0.25 and weight=0.3: score = 1.0 * (0.7 + 0.3 * 0.25) = 0.775
    assert score >= 0.70, f"365-day memory should retain >=70% score, got {score}"
    assert score <= 0.85, f"365-day memory should not exceed 85%, got {score}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sage/test_recall.py::TestComputeRecallScore::test_memory_layer_old_node_retains_floor_score -v`

Expected: FAIL - score will be ~0.0003 (no floor currently)

- [ ] **Step 3: Add test for fresh memory scoring unchanged**

```python
def test_memory_layer_fresh_node_scores_full(self) -> None:
    """A fresh memory should score close to full similarity."""
    fresh_node = {
        "layer": Layer.MEMORY,
        "confidence": 1.0,
        "created_at": datetime.now(UTC) - timedelta(hours=1),
    }
    score = compute_recall_score(fresh_node, similarity=0.9)
    # Fresh node: freshness ~1.0, score = 0.9 * (0.7 + 0.3 * 1.0) = 0.9
    assert score >= 0.85, f"Fresh memory should retain >=85% of similarity, got {score}"
```

- [ ] **Step 4: Run test to verify baseline**

Run: `uv run pytest tests/sage/test_recall.py::TestComputeRecallScore::test_memory_layer_fresh_node_scores_full -v`

Expected: PASS (fresh nodes already work, this confirms baseline)

- [ ] **Step 5: Commit test file**

```bash
git add tests/sage/test_recall.py
git commit -m "test: add decay floor tests for long-horizon memory"
```

---

## Task 2: Implement Brain Path Decay Floor

**Files:**
- Modify: `src/context_service/sage/recall.py:123-142`

- [ ] **Step 1: Add import for compute_freshness**

At the top of `src/context_service/sage/recall.py`, add to imports:

```python
from context_service.signals.freshness import compute_freshness
```

- [ ] **Step 2: Add settings import for freshness_weight**

Add to imports section:

```python
from context_service.config.settings import get_settings
```

- [ ] **Step 3: Modify compute_recall_score MEMORY branch**

Replace lines 141-142 in `compute_recall_score`:

```python
    if layer == Layer.MEMORY:
        layer_score = similarity * gaussian_decay(age_days)
```

With:

```python
    if layer == Layer.MEMORY:
        settings = get_settings()
        # Parse created_at to datetime for compute_freshness
        if isinstance(created_at, datetime):
            created_at_dt = created_at
        elif isinstance(created_at, str):
            try:
                created_at_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_at_dt = datetime.now(UTC)
        else:
            created_at_dt = datetime.now(UTC)
        
        now = datetime.now(UTC)
        freshness = compute_freshness(created_at_dt, now, sigma_days=MEMORY_DECAY_SIGMA)
        weight = settings.freshness_weight
        layer_score = similarity * ((1.0 - weight) + weight * freshness)
```

- [ ] **Step 4: Run decay floor tests**

Run: `uv run pytest tests/sage/test_recall.py::TestComputeRecallScore::test_memory_layer_old_node_retains_floor_score tests/sage/test_recall.py::TestComputeRecallScore::test_memory_layer_fresh_node_scores_full -v`

Expected: PASS for both tests

- [ ] **Step 5: Run full sage recall test suite**

Run: `uv run pytest tests/sage/test_recall.py -v`

Expected: All tests pass (existing tests should still work)

- [ ] **Step 6: Run type check**

Run: `uv run mypy src/context_service/sage/recall.py`

Expected: No errors

- [ ] **Step 7: Commit implementation**

```bash
git add src/context_service/sage/recall.py
git commit -m "feat: add decay floor to brain path memory scoring

Reuse compute_freshness from signals/freshness.py to apply floor (0.25)
and weighted blend (settings.freshness_weight) to MEMORY layer scoring.

365-day-old memories now retain ~77% of similarity instead of ~0%.
Fixes long-horizon recall for Somnus benchmark."
```

---

## Task 3: Tier-Driven Summary Tests

**Files:**
- Modify: `tests/integration/test_context_recall_content.py`

- [ ] **Step 1: Add test for COLD node returning summary by default**

```python
@pytest.mark.asyncio
async def test_cold_node_returns_summary_by_default() -> None:
    """COLD tier nodes should return summary instead of content when include_content=None."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid, content="x" * 500)
    full["tier"] = "COLD"
    full["summary"] = "pre-computed summary"

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full]}

        # Default include_content=True currently, but we want tier-based
        # For now this test documents expected behavior after implementation
        result = await _context_recall(silo_id=silo_id, node_ids=[nid], include_content=None)

        node = result["nodes"][0]
        assert "summary" in node
        assert "expandable" in node
        assert node["expandable"] is True
        assert "content" not in node
```

- [ ] **Step 2: Add test for HOT node returning content by default**

```python
@pytest.mark.asyncio
async def test_hot_node_returns_content_by_default() -> None:
    """HOT tier nodes should return full content when include_content=None."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid, content="full content here")
    full["tier"] = "HOT"

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full]}

        result = await _context_recall(silo_id=silo_id, node_ids=[nid], include_content=None)

        node = result["nodes"][0]
        assert "content" in node
        assert node["content"] == "full content here"
```

- [ ] **Step 3: Add test for explicit include_content=True overriding tier**

```python
@pytest.mark.asyncio
async def test_include_content_true_overrides_cold_tier() -> None:
    """Explicit include_content=True should return full content even for COLD nodes."""
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid4())
    silo_id = str(uuid4())
    full = _full_node(nid, content="full content")
    full["tier"] = "COLD"

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {"nodes": [full]}

        result = await _context_recall(silo_id=silo_id, node_ids=[nid], include_content=True)

        node = result["nodes"][0]
        assert "content" in node
        assert node["content"] == "full content"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_context_recall_content.py::test_cold_node_returns_summary_by_default tests/integration/test_context_recall_content.py::test_hot_node_returns_content_by_default -v`

Expected: FAIL (tier-based logic not implemented yet)

- [ ] **Step 5: Commit test file**

```bash
git add tests/integration/test_context_recall_content.py
git commit -m "test: add tier-driven summary tests"
```

---

## Task 4: Implement Tier-Driven Summary Logic

**Files:**
- Modify: `src/context_service/mcp/tools/context_recall.py:46-72, 109-125`

- [ ] **Step 1: Update _project_node_without_content to include tier fields**

Replace `_project_node_without_content` function (lines 46-72):

```python
def _project_node_without_content(node: dict[str, Any], include_expandable: bool = False) -> dict[str, Any]:
    """Project a node dict to {node_id, layer, summary, created_at, confidence, tier}.

    `summary` falls back to the first 200 chars of `content` when no
    pre-computed summary is present. Error/sentinel entries are passed
    through unchanged so callers still see them.
    """
    if "node_id" not in node or "error" in node:
        return node

    summary = node.get("summary")
    if not summary:
        content = node.get("content") or ""
        summary = content[:_SUMMARY_MAX_CHARS] if content else None

    projected = {
        "node_id": node["node_id"],
        "layer": node.get("layer"),
        "summary": summary,
        "created_at": node.get("created_at"),
        "confidence": node.get("confidence"),
        "tier": node.get("tier", "COLD"),
        "relevance_score": node.get("relevance_score"),
    }
    if include_expandable:
        projected["expandable"] = True
    if "steps" in node:
        projected["steps"] = node["steps"]
    if "reflections" in node:
        projected["reflections"] = node["reflections"]
    return projected
```

- [ ] **Step 2: Add tier-based content stripping helper**

Add after `_strip_content` function (around line 82):

```python
def _apply_tier_content_policy(
    response: dict[str, Any],
    include_content: bool | None,
) -> dict[str, Any]:
    """Apply tier-based content policy to response nodes.
    
    - include_content=True: return full content for all nodes
    - include_content=False: return summary for all nodes
    - include_content=None: HOT/WARM get content, COLD gets summary
    """
    if include_content is True:
        return response
    if include_content is False:
        return _strip_content(response)
    
    # Tier-based logic for include_content=None
    def process_node(node: dict[str, Any]) -> dict[str, Any]:
        if "node_id" not in node or "error" in node:
            return node
        tier = node.get("tier", "COLD")
        if tier in ("HOT", "WARM"):
            return node
        return _project_node_without_content(node, include_expandable=True)
    
    if isinstance(response.get("nodes"), list):
        response["nodes"] = [process_node(n) for n in response["nodes"]]
    if isinstance(response.get("results"), list):
        response["results"] = [process_node(r) for r in response["results"]]
    return response
```

- [ ] **Step 3: Update _context_recall to use tier-based policy**

In `_context_recall` function, replace each occurrence of:

```python
        if not include_content:
            response = _strip_content(response)
```

With:

```python
        response = _apply_tier_content_policy(response, include_content)
```

There are 4 occurrences at approximately lines 152-153, 165-166, 184-185, and 197-198.

- [ ] **Step 4: Update function signature default**

Change the `_context_recall` function signature (line 109):

From:
```python
    include_content: bool = True,
```

To:
```python
    include_content: bool | None = None,
```

Also update the MCP tool signature (line 230) the same way.

- [ ] **Step 5: Run tier-driven tests**

Run: `uv run pytest tests/integration/test_context_recall_content.py -v`

Expected: All tests pass including new tier-driven tests

- [ ] **Step 6: Run type check**

Run: `uv run mypy src/context_service/mcp/tools/context_recall.py`

Expected: No errors

- [ ] **Step 7: Commit implementation**

```bash
git add src/context_service/mcp/tools/context_recall.py
git commit -m "feat: tier-driven summary default for COLD nodes

COLD nodes now return summary instead of full content by default.
HOT/WARM nodes return full content.
Explicit include_content=True/False overrides tier-based behavior.

Reduces token usage for recall results containing mostly COLD nodes."
```

---

## Task 5: Integration Verification

**Files:**
- None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `uv run just check`

Expected: lint + typecheck pass

- [ ] **Step 2: Run all related tests**

Run: `uv run pytest tests/sage/test_recall.py tests/integration/test_context_recall_content.py tests/mcp/test_context_recall.py -v`

Expected: All tests pass

- [ ] **Step 3: Verify no regressions in context_query**

Run: `uv run pytest tests/ -k "context" -v --tb=short`

Expected: All context-related tests pass

- [ ] **Step 4: Final commit if any fixes needed**

Only if fixes were made in previous steps:

```bash
git add -A
git commit -m "fix: address test failures from phase 1 implementation"
```

---

## Summary

After completing all tasks:

1. **Brain path decay floor** - 365-day memories score ~77% instead of ~0%
2. **Tier-driven summaries** - COLD nodes return summary by default, saving tokens
3. **Full backward compatibility** - `include_content=True` works as before
4. **All tests passing** - existing behavior preserved, new behavior tested
