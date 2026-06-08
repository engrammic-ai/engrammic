# A1 Enforcement Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Engrammic surface only memory it can stand behind: a trust gate on recall withholds unresolved-contradiction and below-floor-confidence nodes (returning an "N withheld" count), tool descriptions and server instructions are hardened to drive recall-first/persist-proactively behavior, and the write path warns instead of silently blocking when evidence is missing.

**Architecture:** A1 is the portable, server-side spine. It works in every MCP client with zero install because it lives in the FastMCP server: the trust gate is an in-memory post-filter on the unified recall response (no extra queries, no change to the core `query()`); the instruction hardening rides the existing `instructions` field and tool descriptions; the soft write gate adjusts the existing `evidence_enforcement` path. Hooks/plugin (A2) and the installer (C) are out of scope.

**Tech Stack:** Python 3.12, FastMCP, Pydantic v2 settings, pytest (asyncio_mode=auto), `uv run`. Run lint+types with `just check`, tests with `just test`.

**Source spec:** `context/plans/2026-06-04-enforcement-architecture-design.md` (A1 section).

**Key facts (verified against code):**
- `recall.py` is where all three retrieval paths converge into the final response dict. It promotes `conflict_status`, `credibility`, and `credibility_factors` to top-level on each item (recall.py:100-118). `confidence` is ALREADY top-level on each item (set upstream by `_project_node_without_content`), so do NOT add a confidence promotion. The gate goes at the END of `_recall_impl`, after the hard-mode block (recall.py:159-167) and immediately before the single `return result` (recall.py:195). Hard mode sets `result["results"] = []` at 159-167, so running the gate after it avoids a contradictory empty-results-plus-withheld-count response.
- The core `query()` (services/context.py:1506-1507) ALREADY drops superseded nodes (`if not include_superseded and props.get("superseded_by"): continue`). A1 adds the contradiction + confidence gate on top, plus the withheld accounting.
- A node's `confidence` and `conflict_status` live in `node.properties` and are surfaced onto each recall result item as `confidence` and `conflict_status` (values: `none`, `unresolved`, `resolved_supersede`).
- Settings sub-configs are frozen `BaseModel`s registered on `Settings` via `Field(default_factory=...)` (settings.py:117-124, 905-907).
- `evidence_enforcement` = `enabled=True, enforce=False`; soft mode currently returns `{"error": "missing_evidence"}` WITHOUT storing (learn.py:46-58). Task 5 changes soft mode to store-and-warn.
- Tests: `tests/mcp/tools/test_*.py`, fixtures `mock_mcp_context`, `mock_context_service`, `mock_evidence_validator` in `tests/mcp/tools/conftest.py`. Run one with `uv run pytest tests/mcp/tools/test_x.py::test_y -v`.

---

### Task 1: Harden tool descriptions and server instructions

**Files:**
- Modify: `src/context_service/config/mcp_tools.yaml` (descriptions at lines 44-117; `mcp_instructions` at 5-41)
- Test: `tests/mcp/tools/test_tool_descriptions.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/tools/test_tool_descriptions.py
"""Tool descriptions and server instructions must carry the forcing-function language."""

from context_service.mcp.tools.registry import (
    get_mcp_instructions,
    get_tool_description,
)


def test_recall_description_mentions_session_start_and_withholding():
    desc = get_tool_description("recall").lower()
    assert "session start" in desc or "start of" in desc
    assert "withheld" in desc or "include_withheld" in desc


def test_learn_description_drives_evidence_and_supersession():
    desc = get_tool_description("learn").lower()
    assert "evidence" in desc
    assert "supersedes" in desc


def test_instructions_lead_with_recall_first():
    instr = get_mcp_instructions().lower()
    assert "recall" in instr
    assert "before" in instr  # recall-before-store guidance present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_tool_descriptions.py -v`
Expected: FAIL on `test_recall_description_mentions_session_start_and_withholding` ("withheld" not yet in the recall description).

- [ ] **Step 3: Edit `mcp_tools.yaml`**

Update the `recall` description (lines ~66-72) to:

```yaml
  recall:
    description: |
      Search or fetch knowledge. Call this at the START of any task and
      before storing anything (to supersede, not duplicate). Use query for
      semantic search, node_ids for direct fetch, query="*" to list all.
      Low-confidence and unresolved-contradiction memories are withheld by
      default and reported as a withheld count; pass include_withheld=true
      to see them. min_threshold overrides the relevance cutoff (0.0-1.0).
    maps_to: retrieve
```

Tighten `learn` (keep existing, ensure it says evidence + supersedes), and prepend one line to `mcp_instructions` (after the "Quick start" block) reinforcing: `Always recall before you store, and at the start of a task.` Do not remove existing guidance. No em-dashes anywhere.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_tool_descriptions.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/context_service/config/mcp_tools.yaml tests/mcp/tools/test_tool_descriptions.py
git commit -m "feat(mcp): harden tool descriptions and instructions for recall-first behavior"
```

---

### Task 2: Add TrustGateConfig settings

**Files:**
- Modify: `src/context_service/config/settings.py` (add config after EvidenceEnforcementConfig ~line 124; register on Settings ~line 907)
- Test: `tests/config/test_trust_gate_settings.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/config/test_trust_gate_settings.py
from context_service.config.settings import Settings


def test_trust_gate_defaults():
    s = Settings()
    assert s.trust_gate.enabled is True
    assert s.trust_gate.withhold_unresolved_conflicts is True
    # Floor defaults OFF (0.0): conflict-withholding is the safe v1 demo;
    # raise per deployment to also withhold low-confidence memory.
    assert s.trust_gate.confidence_floor == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/config/test_trust_gate_settings.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'trust_gate'`.

- [ ] **Step 3: Add the config**

After `EvidenceEnforcementConfig` (settings.py:124) add:

```python
class TrustGateConfig(BaseModel):
    """Settings for the recall trust gate (A1).

    Withholds memory the system cannot stand behind from recall results.
    Superseded nodes are already dropped upstream by query(); this gate adds
    unresolved-contradiction and below-floor-confidence withholding.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable the recall trust gate")
    confidence_floor: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Withhold results with confidence below this floor. "
        "Default 0.0 (off) to avoid hiding low-confidence-but-useful knowledge; "
        "calibrate per deployment. OPEN QUESTION in the spec.",
    )
    withhold_unresolved_conflicts: bool = Field(
        default=True,
        description="Withhold results whose conflict_status is 'unresolved'",
    )
```

Register it on `Settings` next to `evidence_enforcement` (settings.py:905-907):

```python
    trust_gate: TrustGateConfig = Field(default_factory=TrustGateConfig)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/config/test_trust_gate_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/config/settings.py tests/config/test_trust_gate_settings.py
git commit -m "feat(config): add TrustGateConfig for recall trust gate"
```

---

### Task 3: Implement the apply_trust_gate helper (pure function)

**Files:**
- Create: `src/context_service/mcp/tools/trust_gate.py`
- Test: `tests/mcp/tools/test_trust_gate.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/mcp/tools/test_trust_gate.py
from context_service.mcp.tools.trust_gate import apply_trust_gate


def _node(node_id, confidence=1.0, conflict_status="none"):
    return {"node_id": node_id, "confidence": confidence, "conflict_status": conflict_status}


def test_passes_warranted_nodes():
    items = [_node("a"), _node("b")]
    surfaced, withheld = apply_trust_gate(
        items, confidence_floor=0.0, withhold_conflicts=True, include_withheld=False
    )
    assert [n["node_id"] for n in surfaced] == ["a", "b"]
    assert withheld["count"] == 0


def test_withholds_unresolved_conflict():
    items = [_node("a"), _node("bad", conflict_status="unresolved")]
    surfaced, withheld = apply_trust_gate(
        items, confidence_floor=0.0, withhold_conflicts=True, include_withheld=False
    )
    assert [n["node_id"] for n in surfaced] == ["a"]
    assert withheld["count"] == 1
    assert withheld["by_reason"]["unresolved_conflict"] == 1


def test_withholds_below_floor():
    items = [_node("a", confidence=0.9), _node("low", confidence=0.1)]
    surfaced, withheld = apply_trust_gate(
        items, confidence_floor=0.3, withhold_conflicts=True, include_withheld=False
    )
    assert [n["node_id"] for n in surfaced] == ["a"]
    assert withheld["by_reason"]["low_confidence"] == 1


def test_include_withheld_bypasses():
    items = [_node("a"), _node("bad", conflict_status="unresolved")]
    surfaced, withheld = apply_trust_gate(
        items, confidence_floor=0.5, withhold_conflicts=True, include_withheld=True
    )
    assert len(surfaced) == 2
    assert withheld["count"] == 0


def test_missing_confidence_is_not_withheld():
    items = [{"node_id": "a", "conflict_status": "none"}]  # no confidence key
    surfaced, withheld = apply_trust_gate(
        items, confidence_floor=0.5, withhold_conflicts=True, include_withheld=False
    )
    assert len(surfaced) == 1


def test_empty_input():
    surfaced, withheld = apply_trust_gate(
        [], confidence_floor=0.5, withhold_conflicts=True, include_withheld=False
    )
    assert surfaced == []
    assert withheld["count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mcp/tools/test_trust_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: ...trust_gate`.

- [ ] **Step 3: Implement the helper**

```python
# src/context_service/mcp/tools/trust_gate.py
"""Recall trust gate (A1): withhold memory the system cannot stand behind."""

from __future__ import annotations

from typing import Any


def apply_trust_gate(
    results: list[dict[str, Any]],
    *,
    confidence_floor: float,
    withhold_conflicts: bool,
    include_withheld: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Partition recall results into surfaced vs withheld.

    Withholds items with conflict_status == "unresolved" (if withhold_conflicts)
    or confidence below confidence_floor. Missing confidence is treated as 1.0
    (do not penalize absent data); missing conflict_status as "none".

    Returns (surfaced_results, withheld_summary). withheld_summary is
    {"count": int, "by_reason": {"unresolved_conflict": int, "low_confidence": int}}.
    """
    by_reason: dict[str, int] = {"unresolved_conflict": 0, "low_confidence": 0}
    if include_withheld:
        return list(results), {"count": 0, "by_reason": by_reason}

    surfaced: list[dict[str, Any]] = []
    count = 0
    for item in results:
        status = item.get("conflict_status") or "none"
        raw_conf = item.get("confidence")
        confidence = 1.0 if raw_conf is None else float(raw_conf)

        reason: str | None = None
        if withhold_conflicts and status == "unresolved":
            reason = "unresolved_conflict"
        elif confidence < confidence_floor:
            reason = "low_confidence"

        if reason is None:
            surfaced.append(item)
        else:
            count += 1
            by_reason[reason] += 1

    summary: dict[str, Any] = {"count": count, "by_reason": by_reason}
    return surfaced, summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcp/tools/test_trust_gate.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/trust_gate.py tests/mcp/tools/test_trust_gate.py
git commit -m "feat(mcp): add apply_trust_gate helper"
```

---

### Task 4: Wire the trust gate into recall

**Files:**
- Modify: `src/context_service/mcp/tools/recall.py` (add `include_withheld` to `_recall_impl` 35-45, the registered `recall` wrapper 243-253, and thread it through the POSITIONAL `_recall_impl(...)` call at 277-287; apply the gate at the END of `_recall_impl`, after the hard-mode block 159-167, immediately before `return result` at 195)
- Test: `tests/mcp/tools/test_recall_trust_gate.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/tools/test_recall_trust_gate.py
from unittest.mock import AsyncMock

import pytest

from context_service.mcp.tools import recall as recall_mod

# CRITICAL: _recall_impl has several dependencies that must be patched on the
# recall_mod namespace (get_mcp_auth_context, derive_silo_id, get_preset_resolver,
# track_tool_usage, get_redis, ...). Do NOT rely on conftest's mock_mcp_context: it
# does not patch recall. Copy the proven helper
# tests/mcp/tools/test_recall_engagement.py::_patch_recall_base VERBATIM as the
# `patched_recall` fixture below, then set _context_recall's return value to FAKE.

FAKE = {
    "results": [
        {"node_id": "ok", "confidence": 0.9, "conflict_status": "none"},
        {"node_id": "contested", "confidence": 0.9, "conflict_status": "unresolved"},
    ],
    "total_candidates": 2,
}


@pytest.mark.asyncio
async def test_recall_withholds_unresolved_conflict(patched_recall):
    # patched_recall: the _patch_recall_base fixture with _context_recall -> FAKE
    out = await recall_mod._recall_impl(query="anything")
    assert [n["node_id"] for n in out["results"]] == ["ok"]
    assert out["withheld"]["count"] == 1
    assert "include_withheld" in out["withheld"]["message"]


@pytest.mark.asyncio
async def test_recall_include_withheld_returns_all(patched_recall):
    out = await recall_mod._recall_impl(query="anything", include_withheld=True)
    assert len(out["results"]) == 2
    assert out["withheld"]["count"] == 0
```

Note: Build the `patched_recall` fixture by reading `tests/mcp/tools/test_recall_engagement.py` and copying `_patch_recall_base` exactly (it monkeypatches `recall_mod._context_recall`, `get_mcp_auth_context`, `derive_silo_id`, `get_preset_resolver`, `track_tool_usage`, and per-test `recall.get_redis` and `engine.engagement.get_engagement_for_about_set`). Override `_context_recall`'s return with `FAKE`. The `@rate_limited` wrapper does not interfere: in tests `_rate_limiter is None`, so calling `_recall_impl` directly is fine.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_recall_trust_gate.py -v`
Expected: FAIL (`_recall_impl` has no `include_withheld` kwarg / no `withheld` key in output).

- [ ] **Step 3: Wire the gate**

In `recall.py`, add the import near the top:

```python
from context_service.config.settings import get_settings
from context_service.mcp.tools.trust_gate import apply_trust_gate
```

Add `include_withheld: bool = False` to BOTH the `recall(...)` register function signature (recall.py:235-292) and `_recall_impl(...)` (recall.py:34-45), and pass it through from `recall` to `_recall_impl`.

At the END of `_recall_impl`, after the hard-mode block (recall.py:159-167) and immediately before the final `return result` (recall.py:195), insert:

```python
        tg = get_settings().trust_gate
        if tg.enabled:
            list_key = "results" if "results" in result else (
                "nodes" if "nodes" in result else None
            )
            if list_key is not None and isinstance(result[list_key], list):
                surfaced, withheld = apply_trust_gate(
                    result[list_key],
                    confidence_floor=tg.confidence_floor,
                    withhold_conflicts=tg.withhold_unresolved_conflicts,
                    include_withheld=include_withheld,
                )
                result[list_key] = surfaced
                if withheld["count"] > 0:
                    withheld["message"] = (
                        f"{withheld['count']} memories withheld (low confidence or "
                        "unresolved contradiction). Pass include_withheld=true to see them."
                    )
                result["withheld"] = withheld
```

Hard mode (recall.py:159-167) sets `result["results"] = []` and falls through to the same `return result`, so placing the gate just before that return means hard mode reports `count: 0` instead of a contradictory empty-results-plus-withheld-count response. Also add `include_withheld: bool = False` to the registered `recall` wrapper (243-253) and pass it through the positional `_recall_impl(...)` call at 277-287 by keyword: `include_withheld=include_withheld`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_recall_trust_gate.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/recall.py tests/mcp/tools/test_recall_trust_gate.py
git commit -m "feat(mcp): apply trust gate to recall with include_withheld override"
```

---

### Task 5: Soft write gate (store-and-warn on missing evidence)

**Files:**
- Modify: `src/context_service/mcp/tools/learn.py` (`_learn_impl` evidence block ~44-58)
- Test: `tests/mcp/tools/test_learn_soft_gate.py` (create)

**Behavior change:** today, soft mode (`evidence_enforcement.enforce=False`) returns `{"error": "missing_evidence"}` and does NOT store. Per the spec's soft-default posture, soft mode should STORE and attach a non-blocking `warning`. Hard mode (`enforce=True`) still raises `MissingEvidenceError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/tools/test_learn_soft_gate.py
from dataclasses import dataclass

import pytest

from context_service.mcp.tools.learn import _learn_impl


@dataclass(frozen=True)
class _Cfg:
    enabled: bool
    enforce: bool


@pytest.mark.asyncio
async def test_soft_mode_stores_and_warns_without_evidence(
    mock_mcp_context, mock_context_service, mock_evidence_validator, monkeypatch
):
    import context_service.mcp.tools.learn as learn_mod

    fake_settings = type("S", (), {"evidence_enforcement": _Cfg(enabled=True, enforce=False)})()
    monkeypatch.setattr(learn_mod, "get_settings", lambda: fake_settings)

    result = await _learn_impl(claim="Sky is blue", evidence=[], source="observation")

    assert "error" not in result
    assert "node_id" in result
    assert "warning" in result


@pytest.mark.asyncio
async def test_hard_mode_rejects_without_evidence(
    mock_mcp_context, mock_context_service, monkeypatch
):
    import context_service.mcp.tools.learn as learn_mod
    from primitives.eag.transitions import MissingEvidenceError

    fake_settings = type("S", (), {"evidence_enforcement": _Cfg(enabled=True, enforce=True)})()
    monkeypatch.setattr(learn_mod, "get_settings", lambda: fake_settings)

    with pytest.raises(MissingEvidenceError):
        await _learn_impl(claim="Sky is blue", evidence=[], source="observation")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_learn_soft_gate.py -v`
Expected: FAIL: soft test gets `{"error": "missing_evidence"}` (no node_id/warning).

- [ ] **Step 3: Change the soft path**

In `learn.py`, replace the evidence block (currently lines ~46-58):

```python
    if cfg.enabled and not validate_evidence_non_empty(evidence):
        log.warning(
            "evidence_violation",
            claim_preview=claim[:100] if claim else "",
            evidence_count=len(evidence) if evidence else 0,
            enforce_mode=cfg.enforce,
        )
        if cfg.enforce:
            raise MissingEvidenceError()
        return {
            "error": "missing_evidence",
            "message": "evidence must reference at least one node or URI",
        }
```

with:

```python
    evidence_warning: str | None = None
    if cfg.enabled and not validate_evidence_non_empty(evidence):
        log.warning(
            "evidence_violation",
            claim_preview=claim[:100] if claim else "",
            evidence_count=len(evidence) if evidence else 0,
            enforce_mode=cfg.enforce,
        )
        if cfg.enforce:
            raise MissingEvidenceError()
        evidence_warning = (
            "stored without evidence; add a source node or URI so this "
            "claim can be trusted and surfaced later"
        )
```

Then after the `_context_assert(...)` call returns `result`, before returning it, attach the warning:

```python
    if evidence_warning and isinstance(result, dict) and "error" not in result:
        result["warning"] = evidence_warning
```

learn.py imports `MissingEvidenceError` from `primitives.eag.transitions` (learn.py:10); the test imports it from the same place.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_learn_soft_gate.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/learn.py tests/mcp/tools/test_learn_soft_gate.py
git commit -m "feat(mcp): soft evidence gate stores and warns instead of blocking"
```

---

### Task 6: Full verification

- [ ] **Step 1: Run the A1 tests together**

Run:
```bash
uv run pytest tests/mcp/tools/test_tool_descriptions.py tests/config/test_trust_gate_settings.py tests/mcp/tools/test_trust_gate.py tests/mcp/tools/test_recall_trust_gate.py tests/mcp/tools/test_learn_soft_gate.py -v
```
Expected: all PASS.

- [ ] **Step 2: Lint + types**

Run: `just check`
Expected: ruff + mypy strict clean. Fix any issues (common: add return-type/param annotations; `withheld` dict typing).

- [ ] **Step 3: Full suite (no regressions)**

Run: `just test`
Expected: no new failures versus baseline. The trust gate changes recall output (adds `withheld`, may shrink `results` when fixtures contain `conflict_status="unresolved"`); update any existing recall test that asserts exact result counts.

- [ ] **Step 4: Commit any fixups**

```bash
git add -A
git commit -m "test(a1): fix up recall assertions for trust gate and pass just check"
```

---

## Self-review

- **Spec coverage:** tool-description hardening (Task 1) + server instructions (Task 1, rides existing `instructions` field set at server.py:387); trust-gated recall with withheld count (Tasks 2-4); soft write gate (Task 5). The portable tool-response primer is delivered as the `withheld` message on recall plus the hardened `instructions` field, rather than a separate session-first primer (which would couple to engagement session state; deferred to A2 where the hook can do it richly). Note this scoping in the PR description.
- **Superseded filtering** is pre-existing (query():1506); A1 deliberately does not duplicate it. The gate adds contradiction + confidence + accounting.
- **Type consistency:** `apply_trust_gate(results, *, confidence_floor, withhold_conflicts, include_withheld)` and its `(surfaced, summary)` return are used identically in Task 3 and Task 4. `withheld["count"]`/`withheld["by_reason"]` keys match across tests and impl.
- **Open question carried from spec:** `confidence_floor` default is 0.0 (off) for safety; calibrate before claiming low-confidence withholding in the demo. The contradiction gate is the safe v1 demo mechanic.
- **Risk:** existing recall tests may assert exact `results` length; Task 6 Step 3 catches and fixes these.

## Execution handoff

Plan complete and saved to `context/plans/2026-06-04-a1-enforcement-spine-plan.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration. Note: subagents need writes, so this runs under `acceptEdits` (already on).
2. **Inline Execution** - I execute the tasks in this session with checkpoints for your review.

Which approach?
