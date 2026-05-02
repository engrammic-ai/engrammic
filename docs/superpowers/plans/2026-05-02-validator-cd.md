# Validator Phase C/D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete dead `output_recovery.py` code and introduce `run_validation()` + `PipelineResult` so `write_path.py` has a structured, testable validation entry point.

**Architecture:** Phase C deletes the monkey-patch dead code (already replaced by `model_validator(mode='before')` in `custodian/models.py`). Phase D extracts the inline citation + business rule calls in `write_path.py` into a `run_validation()` function in a new `pipeline.py`, returning a typed `PipelineResult`. No behavior change — pure structural refactor.

**Tech Stack:** Python 3.12, pydantic v2, pytest-asyncio. All commands via `uv run`. Quality gate: `just check` (ruff + mypy strict) must pass before each commit.

**Branch:** `phase-validator-cd` — do NOT commit to main.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| DELETE | `src/context_service/custodian/output_recovery.py` | Dead code — entire file |
| MODIFY | `src/context_service/custodian/agents.py` | Remove import + 3 no-op call sites |
| CREATE | `src/context_service/custodian/pipeline.py` | `PipelineResult`, `StageResult`, `run_validation()` |
| MODIFY | `src/context_service/custodian/write_path.py` | Delegate validation to `run_validation()` |
| CREATE | `tests/test_validation_pipeline.py` | Unit tests: pass / citation-fail / business-fail |

---

## Task 1: Cut the branch and delete dead code

**Files:**
- Delete: `src/context_service/custodian/output_recovery.py`
- Modify: `src/context_service/custodian/agents.py`

- [ ] **Step 1: Cut the branch**

```bash
git checkout -b phase-validator-cd
```

- [ ] **Step 2: Delete `output_recovery.py`**

```bash
rm src/context_service/custodian/output_recovery.py
```

- [ ] **Step 3: Remove the import and 3 call sites from `agents.py`**

Open `src/context_service/custodian/agents.py`. Remove these lines (they are near the top imports and near the bottom of the file):

```python
# REMOVE this import line:
from context_service.custodian.output_recovery import patch_agent_output_validators

# REMOVE these three call lines (at the end of the file, after agent definitions):
patch_agent_output_validators(fast_pass_agent, FastPassObservation, "fast_pass")
patch_agent_output_validators(plan_agent, VisitPlan, "plan")
patch_agent_output_validators(stitch_agent, StitchedSummary, "stitch")
```

- [ ] **Step 4: Verify no remaining references**

```bash
uv run grep -r "output_recovery" src/ tests/ --include="*.py"
```

Expected: no output.

- [ ] **Step 5: Run quality check**

```bash
just check
```

Expected: PASSED (0 errors).

- [ ] **Step 6: Run tests**

```bash
just test
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add -p
git commit -m "refactor: delete dead output_recovery.py (monkey-patch superseded by model_validator)"
```

---

## Task 2: Create `pipeline.py` with `PipelineResult` and `run_validation()`

**Files:**
- Create: `src/context_service/custodian/pipeline.py`

Before writing, read these files to match exact signatures:
- `src/context_service/custodian/validators.py` lines 163–220: `validate_finding(finding, seen_node_ids) -> tuple[list[ClaimValidationResult], list[EdgeValidationResult]]`
- `src/context_service/custodian/business_rules.py`: `BusinessRuleValidator.evaluate(finding, surviving_claims, surviving_edges, cluster_size) -> BusinessRuleResult`
- `src/context_service/custodian/write_path.py` lines 229–253: current inline validation block this replaces

- [ ] **Step 1: Write the failing test first**

Create `tests/test_validation_pipeline.py`:

```python
"""Unit tests for run_validation() pipeline function."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.custodian.pipeline import PipelineResult, run_validation


# ---------------------------------------------------------------------------
# Minimal stubs — no live Memgraph needed
# ---------------------------------------------------------------------------


def _mock_citation_validator(*, all_pass: bool = True) -> Any:
    """Return a CitationValidator mock whose validate_finding returns all-pass or all-fail."""
    from context_service.custodian.validators import ClaimValidationResult, EdgeValidationResult

    mock = AsyncMock()
    claim_result = MagicMock(spec=ClaimValidationResult)
    claim_result.accepted = all_pass
    edge_result = MagicMock(spec=EdgeValidationResult)
    edge_result.accepted = all_pass
    mock.validate_finding = AsyncMock(return_value=([claim_result], [edge_result]))
    return mock


def _mock_business_validator(*, accepted: bool = True) -> Any:
    from context_service.custodian.business_rules import BusinessRuleResult

    mock = MagicMock()
    result = BusinessRuleResult(accepted=accepted, computed_quality=0.75)
    mock.evaluate = MagicMock(return_value=result)
    return mock


def _make_finding() -> Any:
    """Minimal FindingOutput stub."""
    from unittest.mock import MagicMock
    from context_service.custodian.models import FindingOutput

    finding = MagicMock(spec=FindingOutput)
    finding.silo_id = "test-silo"
    finding.scope = "cluster"
    finding.claims = [MagicMock()]
    finding.inferred_relations = [MagicMock()]
    finding.model_copy = MagicMock(return_value=finding)
    return finding


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_validation_pass() -> None:
    """Both stages pass -> PipelineResult.passed is True."""
    result = await run_validation(
        finding=_make_finding(),
        seen_node_ids={"node-1"},
        citation_validator=_mock_citation_validator(all_pass=True),
        business_validator=_mock_business_validator(accepted=True),
        cluster_size=5,
    )
    assert isinstance(result, PipelineResult)
    assert result.passed is True
    assert result.failed_at is None
    assert result.citation is not None
    assert result.business is not None


@pytest.mark.asyncio
async def test_run_validation_business_rejects_when_all_claims_fail_citation() -> None:
    """All claims rejected by citation -> business sees empty survivors -> rejects with failed_at='business'."""
    # When all claims fail citation, surviving_claims=[] -> BusinessRuleValidator.evaluate()
    # returns accepted=False with ALL_CLAIMS_REJECTED (its internal logic, not pipeline's).
    biz = _mock_business_validator(accepted=False)
    result = await run_validation(
        finding=_make_finding(),
        seen_node_ids=set(),
        citation_validator=_mock_citation_validator(all_pass=False),
        business_validator=biz,
        cluster_size=5,
    )
    assert result.passed is False
    assert result.failed_at == "business"
    assert result.citation is not None
    assert result.citation.claims_rejected >= 0
    # Business stage always runs — citation stage filters, business gate decides
    biz.evaluate.assert_called_once()


@pytest.mark.asyncio
async def test_run_validation_business_fail() -> None:
    """Citation passes, business fails -> failed_at='business', citation result present."""
    result = await run_validation(
        finding=_make_finding(),
        seen_node_ids={"node-1"},
        citation_validator=_mock_citation_validator(all_pass=True),
        business_validator=_mock_business_validator(accepted=False),
        cluster_size=5,
    )
    assert result.passed is False
    assert result.failed_at == "business"
    assert result.citation is not None
    assert result.business is not None
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_validation_pipeline.py -v
```

Expected: `ImportError: cannot import name 'run_validation' from 'context_service.custodian.pipeline'` (module doesn't exist yet).

- [ ] **Step 3: Create `pipeline.py`**

Create `src/context_service/custodian/pipeline.py`:

```python
"""Validation pipeline for Custodian write path.

Extracts the citation + business rule validation sequence from write_path.py
into a typed function that returns a structured PipelineResult.

Design note: Two named stages, not a generic list, because ordering is enforced
by call sequence (visible in code) and the validator signatures differ. Migrate
to a Protocol-based injectable list only when a third stage is needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from context_service.custodian.business_rules import BusinessRuleResult, BusinessRuleValidator
    from context_service.custodian.models import Claim, FindingOutput, ProposedEdge
    from context_service.custodian.validators import (
        CitationValidator,
        ClaimValidationResult,
        EdgeValidationResult,
    )


@dataclass
class CitationStageResult:
    """Outcome of the citation validation stage."""

    passed: bool
    surviving_claims: list[Any] = field(default_factory=list)
    surviving_edges: list[Any] = field(default_factory=list)
    claims_rejected: int = 0
    edges_rejected: int = 0


@dataclass
class PipelineResult:
    """Structured outcome of the full validation pipeline.

    ``failed_at`` is ``None`` on success, ``"citation"`` or ``"business"`` on failure.
    ``citation`` is always populated after the citation stage runs.
    ``business`` is ``None`` when the citation stage short-circuited.
    """

    passed: bool
    failed_at: str | None = None
    citation: CitationStageResult | None = None
    business: Any | None = None  # BusinessRuleResult when populated


async def run_validation(
    finding: FindingOutput,
    seen_node_ids: set[str],
    citation_validator: CitationValidator,
    business_validator: BusinessRuleValidator,
    cluster_size: int,
) -> PipelineResult:
    """Run citation then business rule validation, short-circuiting on citation failure.

    Args:
        finding: The FindingOutput to validate.
        seen_node_ids: Node IDs seen by the visit (used for citation existence check).
        citation_validator: CitationValidator instance.
        business_validator: BusinessRuleValidator instance.
        cluster_size: Passed to BusinessRuleValidator.evaluate().

    Returns:
        PipelineResult with structured pass/fail and per-stage results.
    """
    # Stage 1: citation validation
    claim_results, edge_results = await citation_validator.validate_finding(finding, seen_node_ids)

    surviving_claims: list[Any] = []
    claims_rejected = 0
    for claim, result in zip(finding.claims, claim_results, strict=True):
        if result.accepted:
            surviving_claims.append(claim)
        else:
            claims_rejected += 1

    surviving_edges: list[Any] = []
    edges_rejected = 0
    for edge, result in zip(finding.inferred_relations, edge_results, strict=True):
        if result.accepted:
            surviving_edges.append(edge)
        else:
            edges_rejected += 1

    citation_stage = CitationStageResult(
        passed=True,
        surviving_claims=surviving_claims,
        surviving_edges=surviving_edges,
        claims_rejected=claims_rejected,
        edges_rejected=edges_rejected,
    )

    # Stage 2: business rule gate — always runs, rejects when no claims survived
    biz = business_validator.evaluate(finding, surviving_claims, surviving_edges, cluster_size)
    if not biz.accepted:
        return PipelineResult(passed=False, failed_at="business", citation=citation_stage, business=biz)

    return PipelineResult(passed=True, citation=citation_stage, business=biz)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_validation_pipeline.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 5: Quality check**

```bash
just check
```

Expected: PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/context_service/custodian/pipeline.py tests/test_validation_pipeline.py
git commit -m "feat: add run_validation() pipeline function with PipelineResult (Phase D)"
```

---

## Task 3: Wire `run_validation()` into `write_path.py`

**Files:**
- Modify: `src/context_service/custodian/write_path.py`

Read `write_path.py` lines 229–260 before editing — the inline validation block is what you're replacing.

- [ ] **Step 1: Add the import to `write_path.py`**

At the top of `src/context_service/custodian/write_path.py`, add alongside the other custodian imports:

```python
from context_service.custodian.pipeline import run_validation
```

- [ ] **Step 2: Replace the inline validation block**

In `write_path.py`, the `write_visit` method currently has this validation block (lines ~229–253):

```python
# Step 1: validate claims and edges; drop rejected items.
claim_results, edge_results = await self._validator.validate_finding(finding, seen_node_ids)

surviving_claims: list[Claim] = []
claims_rejected = 0
for claim, claim_result in zip(finding.claims, claim_results, strict=True):
    if claim_result.accepted:
        surviving_claims.append(claim)
    else:
        claims_rejected += 1

surviving_edges: list[ProposedEdge] = []
edges_rejected = 0
for edge, edge_result in zip(finding.inferred_relations, edge_results, strict=True):
    if edge_result.accepted:
        surviving_edges.append(edge)
    else:
        edges_rejected += 1

# Step 2: business rule gate (all-claims-rejected skip + quality score).
biz = self._business.evaluate(finding, surviving_claims, surviving_edges, cluster_size)
```

Replace with:

```python
# Steps 1+2: citation validation then business rule gate via pipeline.
pipeline_result = await run_validation(
    finding=finding,
    seen_node_ids=seen_node_ids,
    citation_validator=self._validator,
    business_validator=self._business,
    cluster_size=cluster_size,
)
assert pipeline_result.citation is not None
surviving_claims = pipeline_result.citation.surviving_claims
surviving_edges = pipeline_result.citation.surviving_edges
claims_rejected = pipeline_result.citation.claims_rejected
edges_rejected = pipeline_result.citation.edges_rejected
biz = pipeline_result.business
```

- [ ] **Step 3: Handle the skip-write case**

Find the block immediately after the old `biz = ...` line that checks `biz.accepted`:

```python
if not biz.accepted:
    return WritePathResult(
        finding_id="",
        version=0,
        ...
        skipped=True,
    )
```

This block still works because `biz` is now `pipeline_result.business`. If `run_validation` short-circuited on citation failure, `biz` will be `None`. Add a guard:

```python
if pipeline_result.failed_at is not None:
    return WritePathResult(
        finding_id="",
        version=0,
        claims_committed=0,
        claims_rejected=claims_rejected,
        edges_committed=0,
        edges_rejected=edges_rejected,
        references_upserted=0,
        history_snapshot_created=False,
        skipped=True,
    )
```

Place this immediately after the `pipeline_result = await run_validation(...)` block, before accessing `biz`.

- [ ] **Step 4: Run the full test suite**

```bash
just test
```

Expected: all passing (no behavior change, just structural).

- [ ] **Step 5: Quality check**

```bash
just check
```

Expected: PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/context_service/custodian/write_path.py
git commit -m "refactor: delegate write_path validation to run_validation() pipeline"
```

---

## Task 4: Final verification

- [ ] **Step 1: Run the full suite one more time**

```bash
just test && just check
```

Expected: all green.

- [ ] **Step 2: Confirm no dead references**

```bash
uv run grep -r "output_recovery\|patch_agent_output_validators" src/ tests/ --include="*.py"
```

Expected: no output.

- [ ] **Step 3: Confirm pipeline is the only validation entry in write_path**

```bash
uv run grep -n "validate_finding\|business.evaluate" src/context_service/custodian/write_path.py
```

Expected: no matches (all validation now goes through `run_validation`).
