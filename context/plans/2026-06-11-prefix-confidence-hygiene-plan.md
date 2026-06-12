# Confidence Hygiene Pre-Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the falsy-zero confidence bug on the live read paths (confidence 0.0 is currently read as 1.0) and stamp a formula version on confidence writes, so the read-path epistemic fusion work that follows is fed correct values.

**Architecture:** One new pure module (`engine/epistemics.py`) becomes the single source of truth for interpreting absent-vs-present confidence. Five call sites in `services/context.py` switch to it. One write-path line stamps `confidence_formula_version`. No behavior changes for genuinely-missing confidence (still treated as 1.0, the trust-gate convention); the ONLY behavior change is that a stored confidence of exactly 0.0 is now respected as 0.0 instead of being silently promoted to 1.0.

**Tech Stack:** Python 3.12, pytest, mypy strict + ruff. All commands via `uv run` / `just`. Repo: `/home/novusedge/Projects/delta-prime/context-service`.

**Context for an agent with zero history:** This repo is the Engrammic backend (epistemic memory for AI agents; MCP server + FastAPI). Nodes carry epistemic metadata (confidence, credibility, conflict_status) in a schemaless `properties` dict. An architecture critique (2026-06-11, `context/review/2026-06-11-architecture-epistemics-critique.md`, finding E2) found that the live read paths use `props.get("confidence") or 1.0` - the `or` makes a stored `0.0` (assessed, zero confidence) indistinguishable from missing (never assessed), both becoming full trust. A follow-up plan (`context/plans/2026-06-11-step1-read-path-epistemic-fusion.md`) will multiply confidence into ranking; without this fix it would be fed corrupted values. This plan is hard-capped at half a day - do NOT expand scope into the items listed under "Out of scope" below.

**Out of scope (do not touch, even if you notice problems):**
- `sage/recall.py` confidence defaults (lines 132/345/412 disagree with each other) - that is the non-live brain path, fixed at brain cutover, not now.
- Making `QueryResult.confidence` optional / preserving None end-to-end - that is a type-ripple change scheduled for the post-benchmark convergence plan (Tier 3 of `context/plans/2026-06-11-epistemic-hygiene-prefix.md`). This plan keeps all existing types; `effective_confidence` returns a plain float.
- Any file under `mcp/tools/`, `reranking/`, `sage/`, or `config/settings.py` - the step-1 plan owns those next; touching them here creates merge conflicts.

**Repo rules that apply (from CLAUDE.md):** all Python via `uv run`; `just check` (mypy strict + ruff) must pass; never commit to main; no emojis in code or docs.

---

## File Structure

- Create: `src/context_service/engine/epistemics.py` - pure interpretation helpers (no I/O, no settings)
- Create: `tests/engine/test_epistemics.py`
- Modify: `src/context_service/services/context.py` - five read sites (lines ~655, 806, 816, 854, 1491) + one write-path line (~1021)

Note: `tests/engine/` already exists as a directory. `src/context_service/engine/` already exists (it holds `protocols.py`, `queries.py`, `reflection_triggers.py`).

---

### Task 0: Branch

- [ ] **Step 1: Create or reuse the feature branch** (repo rule: never commit to main)

```bash
cd /home/novusedge/Projects/delta-prime/context-service
git checkout -b feat/read-path-epistemic-fusion 2>/dev/null || git checkout feat/read-path-epistemic-fusion
```

This plan is the prerequisite commit-set for the step-1 fusion plan, which uses the same branch. If the branch already exists with fusion work on it, stack these commits on top - the files do not overlap.

---

### Task 1: The epistemics interpretation module

**Files:**
- Create: `src/context_service/engine/epistemics.py`
- Test: `tests/engine/test_epistemics.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_epistemics.py` with exactly:

```python
"""Tests for canonical confidence interpretation (epistemic hygiene pre-fix)."""

from __future__ import annotations

from context_service.engine.epistemics import effective_confidence, read_confidence


class TestReadConfidence:
    def test_missing_key_is_none(self) -> None:
        assert read_confidence({}) is None

    def test_none_value_is_none(self) -> None:
        assert read_confidence({"confidence": None}) is None

    def test_zero_is_zero_not_default(self) -> None:
        # The falsy bug this module exists to kill:
        # `props.get("confidence") or 1.0` maps 0.0 -> 1.0.
        assert read_confidence({"confidence": 0.0}) == 0.0

    def test_present_value_passes_through(self) -> None:
        assert read_confidence({"confidence": 0.42}) == 0.42

    def test_clamped_above(self) -> None:
        assert read_confidence({"confidence": 1.7}) == 1.0

    def test_clamped_below(self) -> None:
        assert read_confidence({"confidence": -0.3}) == 0.0

    def test_string_number_coerced(self) -> None:
        # Graph rows sometimes deserialize numerics as strings.
        assert read_confidence({"confidence": "0.5"}) == 0.5


class TestEffectiveConfidence:
    def test_missing_uses_when_missing_default(self) -> None:
        assert effective_confidence({}) == 1.0

    def test_none_value_uses_when_missing_default(self) -> None:
        assert effective_confidence({"confidence": None}) == 1.0

    def test_zero_respected(self) -> None:
        assert effective_confidence({"confidence": 0.0}) == 0.0

    def test_custom_when_missing(self) -> None:
        assert effective_confidence({}, when_missing=0.5) == 0.5

    def test_present_value_ignores_when_missing(self) -> None:
        assert effective_confidence({"confidence": 0.3}, when_missing=0.9) == 0.3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_epistemics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'context_service.engine.epistemics'`

- [ ] **Step 3: Write the module**

Create `src/context_service/engine/epistemics.py` with exactly:

```python
"""Canonical interpretation of epistemic node properties.

Single source of truth for what ABSENT epistemic state means on read
paths. Convention (matching mcp/tools/trust_gate.py): missing confidence
means "never assessed" and is never penalized, never boosted. A present
confidence - INCLUDING 0.0 - is respected as-is.

Why this module exists: read sites used `props.get("confidence") or 1.0`,
whose falsy `or` maps a stored 0.0 (assessed, zero confidence) to 1.0
(full trust). See context/review/2026-06-11-architecture-epistemics-critique.md
finding E2.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def read_confidence(props: Mapping[str, Any]) -> float | None:
    """Return the node's confidence clamped to [0, 1], or None when never assessed.

    Never use ``props.get("confidence") or default``: the falsy ``or``
    maps a stored 0.0 to the default.
    """
    raw = props.get("confidence")
    if raw is None:
        return None
    return max(0.0, min(1.0, float(raw)))


def effective_confidence(props: Mapping[str, Any], *, when_missing: float = 1.0) -> float:
    """Confidence for contexts that need a scalar. Missing -> ``when_missing``.

    ``when_missing=1.0`` is the trust-gate convention (do not penalize
    absent data). Callers must not pass ``when_missing=0.0`` on read
    paths: treating unassessed as worthless is a ranking decision, not
    a data default.
    """
    conf = read_confidence(props)
    return when_missing if conf is None else conf
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_epistemics.py -v`
Expected: 12 PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/epistemics.py tests/engine/test_epistemics.py
git commit -m "feat(engine): canonical confidence interpretation helpers"
```

---

### Task 2: Switch the five read sites in services/context.py

**Files:**
- Modify: `src/context_service/services/context.py`

All five edits are in this one file. Line numbers are as of 2026-06-11; if they have drifted, locate by the quoted code, which is unique at each site.

- [ ] **Step 1: Add the import**

Near the top of `src/context_service/services/context.py`, with the other `context_service` imports, add:

```python
from context_service.engine.epistemics import effective_confidence
```

- [ ] **Step 2: Fix the query read path (line ~1491, inside `query()`)**

This is the site that matters most - it feeds ranking and the upcoming fusion work.

Old:

```python
            node_confidence = float(props.get("confidence") or 1.0)
```

New:

```python
            node_confidence = effective_confidence(props)
```

- [ ] **Step 3: Fix the provenance chain (line ~806, inside `get_provenance()`)**

Old:

```python
                confidence=float(r.get("confidence") or 1.0),
                stub=bool(r.get("stub") or False),
```

New:

```python
                confidence=effective_confidence(r),
                stub=bool(r.get("stub") or False),
```

- [ ] **Step 4: Fix the provenance root sources (line ~816, same method)**

Old:

```python
                "confidence": float(r.get("confidence") or 1.0),
```

New:

```python
                "confidence": effective_confidence(r),
```

- [ ] **Step 5: Fix the history timeline (line ~854, inside `history()`)**

Old:

```python
                confidence=float(r.get("confidence") or 1.0),
                supersession_reason=r.get("supersession_reason"),
```

New:

```python
                confidence=effective_confidence(r),
                supersession_reason=r.get("supersession_reason"),
```

- [ ] **Step 6: Fix the cache-miss node hydration (line ~655)**

This site uses a dict default, which does NOT have the falsy bug (a stored 0.0 passes through correctly) - but a NULL column value would put `None` into props and trip downstream readers. Use the helper for uniformity and None-robustness.

Old:

```python
                    "confidence": row.get("confidence", 1.0),
```

New:

```python
                    "confidence": effective_confidence(row),
```

- [ ] **Step 7: Add a regression test for the query-path fix**

Append to `tests/engine/test_epistemics.py`:

```python
class TestQueryPathRegression:
    """The falsy bug as it manifested: services/context.py query() promoted
    stored 0.0 confidence to 1.0 via `or 1.0`. These pin the helper's
    behavior at the exact values that path consumes."""

    def test_assessed_zero_stays_zero(self) -> None:
        props = {"layer": "knowledge", "confidence": 0.0}
        assert effective_confidence(props) == 0.0

    def test_unassessed_is_full_trust(self) -> None:
        props = {"layer": "knowledge"}
        assert effective_confidence(props) == 1.0
```

- [ ] **Step 8: Run the module tests plus the service suites that exercise these paths**

Run: `uv run pytest tests/engine/test_epistemics.py tests/services/ tests/mcp/tools/test_trace.py tests/mcp/tools/test_history.py -v`
Expected: all PASS. If any existing test asserted the old behavior (a 0.0-confidence fixture being read as 1.0), the TEST is wrong - update the assertion and note it in the commit message.

- [ ] **Step 9: Commit**

```bash
git add src/context_service/services/context.py tests/engine/test_epistemics.py
git commit -m "fix(services): respect stored zero confidence on read paths

A stored confidence of exactly 0.0 was promoted to 1.0 by falsy
\`or 1.0\` defaults at five read sites. All sites now use the canonical
effective_confidence helper (missing -> 1.0, present -> respected)."
```

---

### Task 3: formula_version stamping at claim write

**Files:**
- Modify: `src/context_service/services/context.py` (the `assert_claim` props block, line ~1018-1026)

- [ ] **Step 1: Add the constant and the stamp**

In `src/context_service/engine/epistemics.py`, add at module level (below the imports):

```python
# Bump when the confidence/credibility formula changes (see primitives
# combined_confidence and compute_credibility). Stored on every claim
# write so recalibration can distinguish formula generations.
CONFIDENCE_FORMULA_VERSION = 1
```

In `src/context_service/services/context.py`, locate the props block in the claim write path (the lines are unique):

```python
        props["confidence"] = discounted_confidence
        props["raw_confidence"] = confidence
        props["evidence"] = evidence
        props["credibility"] = credibility_breakdown.credibility
        props["credibility_factors"] = credibility_breakdown.to_dict()
        props["conflict_status"] = "none"
```

and add one line after `props["raw_confidence"] = confidence`:

```python
        props["confidence_formula_version"] = CONFIDENCE_FORMULA_VERSION
```

Extend the existing import to:

```python
from context_service.engine.epistemics import CONFIDENCE_FORMULA_VERSION, effective_confidence
```

- [ ] **Step 2: Add the test**

Append to `tests/engine/test_epistemics.py`:

```python
def test_formula_version_is_stamped_constant() -> None:
    from context_service.engine.epistemics import CONFIDENCE_FORMULA_VERSION

    assert CONFIDENCE_FORMULA_VERSION == 1
```

Then verify the write path stamps it: find the existing claim-write test (`uv run pytest tests/ -k "assert_claim" --collect-only -q` lists candidates, e.g. `tests/services/test_assert_claim_dedup.py`). Add ONE assertion to an existing happy-path claim-write test checking the stored props include `confidence_formula_version == 1`. If no existing test inspects stored props directly, skip the write-path assertion (the constant test plus the one-line diff are sufficient for this change's risk level) and note that in the commit message.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/engine/test_epistemics.py tests/services/test_assert_claim_dedup.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/engine/epistemics.py src/context_service/services/context.py tests/
git commit -m "feat(services): stamp confidence_formula_version on claim writes"
```

---

### Task 4: Full verification

- [ ] **Step 1: Lint + typecheck**

Run: `just check`
Expected: PASS (mypy strict + ruff). Fix any findings in the files this plan touched; do not "fix" pre-existing findings in other files.

- [ ] **Step 2: Full test suite**

Run: `just test`
Expected: no NEW failures relative to the branch state before this plan. Known pre-existing debt: ~31 tests failing from outdated signatures/mocks (project memory "Test debt") - do not chase those.

- [ ] **Step 3: Mark the prerequisite done**

Edit `context/plans/2026-06-11-epistemic-hygiene-prefix.md`: in the Tier 1 section, annotate H1 and H2 with `(DONE - see 2026-06-11-prefix-confidence-hygiene-plan.md)`.

```bash
git add context/plans/2026-06-11-epistemic-hygiene-prefix.md
git commit -m "docs(plans): mark confidence hygiene pre-fix complete"
```

Do NOT push or open a PR - this branch continues with the step-1 fusion plan (`context/plans/2026-06-11-step1-read-path-epistemic-fusion.md`); the PR ships both together.

---

## Self-review notes

- Behavior change surface: exactly one - stored confidence 0.0 is now read as 0.0 at five sites. Missing/None confidence behavior is unchanged (1.0). No types change, no signatures change, no config changes.
- The `Mapping[str, Any]` parameter type accepts both props dicts and row dicts (all five call sites pass plain dicts).
- mypy strict: `read_confidence` returns `float | None`, `effective_confidence` returns `float`; `float(raw)` on `Any` is accepted; `Mapping` imported from `collections.abc`.
- Deliberately NOT fixed here (scope cap): sage/recall.py internal inconsistency (dead path), QueryResult None-propagation, typed EpistemicState prop - all in Tier 3 of the hygiene umbrella plan.
- Interaction with the step-1 fusion plan: fusion treats `confidence=None` as no-penalty, same convention; with this fix a stored 0.0 reaches fusion as 0.0 and is demoted correctly. The two plans share a branch and do not touch the same lines (fusion touches `query()`'s rerank/dict-building region, this plan touches the confidence read at ~1491 just above it - if both are applied, the merge is textually clean; apply this plan FIRST).
