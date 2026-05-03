# Phase 2: LLM Summarization for Chains

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace truncation with LLM summarization for reasoning chains > 5 steps, preserving semantic meaning.

**Architecture:** Call Haiku for chains > 5 steps during compaction. On LLM failure, mark `summarization_pending: true` on the Event node; Dagster sensor retries pending nodes with exponential backoff. Summary nodes track source chain IDs for retention pruning.

**Tech Stack:** Anthropic SDK (Haiku), existing compaction module, Dagster sensor

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/engine/summarization.py` | LLM summarization logic |
| `src/context_service/engine/compaction.py` | Modify to use LLM summarizer |
| `src/context_service/pipelines/sensors/summarization_retry.py` | Retry pending summarizations |
| `tests/test_summarization.py` | Unit tests |

---

## Task 1: Summarization Service

**Files:**
- Create: `src/context_service/engine/summarization.py`
- Test: `tests/test_summarization.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_summarization.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from context_service.engine.summarization import summarize_reasoning_steps

@pytest.fixture
def mock_llm_client():
    client = AsyncMock()
    client.complete = AsyncMock(return_value="Summary of reasoning chain.")
    return client

@pytest.mark.asyncio
async def test_summarize_reasoning_steps_calls_llm(mock_llm_client):
    steps = [
        {"step_index": i, "operation": "analyze", "conclusion": f"Step {i} conclusion"}
        for i in range(10)
    ]
    
    result = await summarize_reasoning_steps(steps, llm_client=mock_llm_client)
    
    assert result == "Summary of reasoning chain."
    mock_llm_client.complete.assert_called_once()

@pytest.mark.asyncio
async def test_summarize_short_chain_returns_inline():
    steps = [
        {"step_index": 0, "operation": "analyze", "conclusion": "Only conclusion"}
    ]
    
    result = await summarize_reasoning_steps(steps, llm_client=None)
    
    assert "Only conclusion" in result
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement summarization service**

```python
# src/context_service/engine/summarization.py
"""LLM-based summarization for reasoning chains."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from context_service.llm.base import LLMClient

logger = structlog.get_logger(__name__)

_INLINE_THRESHOLD = 5

_SUMMARIZATION_PROMPT = """Summarize this reasoning chain concisely. Capture the key steps, conclusions, and final outcome. Be brief but preserve important details.

Reasoning steps:
{steps_text}

Summary:"""


def _format_steps_for_prompt(steps: list[dict[str, Any]]) -> str:
    """Format steps for LLM prompt."""
    sorted_steps = sorted(steps, key=lambda s: s.get("step_index", 0))
    lines = []
    for s in sorted_steps:
        idx = s.get("step_index", "?")
        op = s.get("operation", "step")
        conclusion = s.get("conclusion", "")
        lines.append(f"[{idx}] {op}: {conclusion}")
    return "\n".join(lines)


def _inline_summary(steps: list[dict[str, Any]]) -> str:
    """Inline all steps for short chains."""
    sorted_steps = sorted(steps, key=lambda s: s.get("step_index", 0))
    lines = [
        f"[{s.get('step_index', i)}] {s.get('operation', 'step')}: {s.get('conclusion', '')}"
        for i, s in enumerate(sorted_steps)
    ]
    return "; ".join(lines)


async def summarize_reasoning_steps(
    steps: list[dict[str, Any]],
    llm_client: "LLMClient | None" = None,
) -> str:
    """Summarize reasoning steps, using LLM for long chains.
    
    For chains <= _INLINE_THRESHOLD steps, returns inline summary.
    For longer chains, calls LLM for semantic summarization.
    
    Args:
        steps: List of step dicts with step_index, operation, conclusion.
        llm_client: LLM client for summarization. If None and chain is long,
            raises ValueError.
    
    Returns:
        Summary string.
    
    Raises:
        ValueError: If chain is long but no LLM client provided.
        LLMError: If LLM call fails.
    """
    if not steps:
        return "(no steps)"
    
    if len(steps) <= _INLINE_THRESHOLD:
        return _inline_summary(steps)
    
    if llm_client is None:
        raise ValueError("LLM client required for chains > 5 steps")
    
    steps_text = _format_steps_for_prompt(steps)
    prompt = _SUMMARIZATION_PROMPT.format(steps_text=steps_text)
    
    logger.info("summarizing_chain", step_count=len(steps))
    summary = await llm_client.complete(prompt)
    
    return summary
```

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(compaction): add LLM summarization service"
```

---

## Task 2: Integrate Summarization into Compaction

**Files:**
- Modify: `src/context_service/engine/compaction.py`
- Test: `tests/test_compaction_summarization.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_compaction_summarization.py
import pytest
from unittest.mock import AsyncMock, patch

from context_service.engine.compaction import compact_reasoning_chain

@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.execute_query = AsyncMock()
    store.execute_write = AsyncMock()
    store.transaction = AsyncMock()
    store.transaction.return_value.__aenter__ = AsyncMock()
    store.transaction.return_value.__aexit__ = AsyncMock()
    return store

@pytest.mark.asyncio
async def test_compact_long_chain_uses_llm(mock_store):
    # Chain with 10 steps
    mock_store.execute_query.return_value = [{
        "compacted": False,
        "agent_id": "agent-1",
        "steps": [{"step_index": i, "operation": "analyze", "conclusion": f"Step {i}"} for i in range(10)],
        "compact_summary": None,
    }]
    
    with patch("context_service.engine.compaction.summarize_reasoning_steps") as mock_summarize:
        mock_summarize.return_value = "LLM summary"
        
        await compact_reasoning_chain(mock_store, "chain-1", "silo-1", "committed")
        
        mock_summarize.assert_called_once()
```

- [ ] **Step 2: Modify compaction to use summarization**

In `compaction.py`:
1. Import `summarize_reasoning_steps`
2. Replace `_summarise_steps` call with `summarize_reasoning_steps`
3. Pass LLM client (get from settings/factory)
4. Handle `summarization_pending` on failure

```python
# In compact_reasoning_chain, replace:
#   content = _summarise_steps(steps)
# With:
try:
    llm_client = get_llm_client()  # from factory
    content = await summarize_reasoning_steps(steps, llm_client=llm_client)
    summarization_pending = False
except Exception as exc:
    logger.warning("summarization_failed", chain_id=chain_id, error=str(exc))
    content = _inline_summary(steps)  # fallback to inline, not truncation
    summarization_pending = True
```

- [ ] **Step 3: Add summarization_pending to Event node**

Modify `CREATE_REASONING_TRACE_EVENT` query to include `summarization_pending` property.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(compaction): integrate LLM summarization for long chains"
```

---

## Task 3: Retry Sensor for Pending Summarizations

**Files:**
- Create: `src/context_service/pipelines/sensors/summarization_retry.py`
- Modify: `src/context_service/pipelines/definitions.py`

- [ ] **Step 1: Create retry sensor**

```python
# src/context_service/pipelines/sensors/summarization_retry.py
"""Sensor to retry failed summarizations with exponential backoff."""

from __future__ import annotations

import dagster as dg

FIND_PENDING_SUMMARIZATIONS = """
MATCH (e:Event {event_type: 'reasoning_trace'})
WHERE e.summarization_pending = true
  AND (e.summarization_retry_at IS NULL OR e.summarization_retry_at < $now)
RETURN e.id AS id, e.silo_id AS silo_id, e.source_chain_id AS chain_id,
       coalesce(e.summarization_retry_count, 0) AS retry_count
LIMIT 10
"""

@dg.sensor(
    name="summarization_retry_sensor",
    minimum_interval_seconds=300,  # Check every 5 minutes
)
def summarization_retry_sensor(context: dg.SensorEvaluationContext):
    """Find Events with pending summarization and trigger retry."""
    # Implementation: query for pending, yield RunRequest per event
    pass
```

- [ ] **Step 2: Add to definitions**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(compaction): add summarization retry sensor"
```

---

## Task 4: Weak References for Summary Retention

**Files:**
- Modify: `src/context_service/retention/queries.py`
- Modify: `src/context_service/retention/service.py`

- [ ] **Step 1: Add query to find orphaned summaries**

```python
# In queries.py
FIND_ORPHANED_SUMMARIES = """
MATCH (e:Event {event_type: 'reasoning_trace'})
WHERE e.source_chain_id IS NOT NULL
  AND NOT exists((:ReasoningChain {id: e.source_chain_id}))
RETURN e.id AS id
"""
```

- [ ] **Step 2: Add method to RetentionService**

```python
async def tombstone_orphaned_summaries(self, silo_id: str, run_id: str) -> int:
    """Tombstone Event summaries whose source chains are gone."""
    rows = await self._store.execute_query(FIND_ORPHANED_SUMMARIES, {"silo_id": silo_id})
    orphan_ids = [row["id"] for row in rows]
    if orphan_ids:
        return await self.tombstone_nodes(orphan_ids, silo_id, run_id)
    return 0
```

- [ ] **Step 3: Call from run_sweep**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(retention): add weak reference pruning for summary nodes"
```

---

## Task 5: Settings and LLM Client Wiring

**Files:**
- Modify: `src/context_service/config/settings.py`
- Modify: `src/context_service/engine/summarization.py`

- [ ] **Step 1: Add settings**

```python
# In Settings class
summarization_model: str = Field(default="claude-3-haiku-20240307")
summarization_max_tokens: int = Field(default=500)
```

- [ ] **Step 2: Add factory function**

```python
# In summarization.py
def get_summarization_client(settings: Settings) -> LLMClient:
    """Get LLM client configured for summarization."""
    from context_service.llm.anthropic import AnthropicClient
    return AnthropicClient(
        model=settings.summarization_model,
        max_tokens=settings.summarization_max_tokens,
    )
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(compaction): wire summarization to settings"
```

---

## Summary

5 tasks:
1. Summarization service with LLM call
2. Integrate into compaction, handle failures
3. Retry sensor for pending summarizations
4. Weak reference pruning for orphaned summaries
5. Settings and LLM client wiring

Estimated time: 2-3 hours.
