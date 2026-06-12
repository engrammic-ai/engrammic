# Read-Path Epistemic Fusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make epistemic state (confidence, conflict status, supersession) load-bearing in recall ranking instead of being overwritten by reranker scores.

**Architecture:** A new pure-function fusion module multiplies post-rerank relevance scores by an epistemic adjustment derived from node confidence and conflict status, then re-sorts. The pre-fusion rerank score is preserved per-result so the abstention floor (RERANK_SCORE_FLOOR) still operates on calibrated reranker output. The fusion breakdown is surfaced in every result for transparency, and superseded_by is exposed so supersession state is visible at read time.

**Tech Stack:** Python 3.12, pydantic settings, pytest (`just test`), mypy strict + ruff (`just check`). All commands via `uv run` / `just`.

**Parent:** Step 1 of `context/plans/2026-06-11-defensibility-sprint.md`. Code findings from the 2026-06-11 moat audit (see `context/brainstorm/2026-06-11-defensibility-and-avenues.md` section 1).

**Why this design:**
- The bug: `_apply_reranking` writes reranker scores into `relevance_score` (`context_query.py:210-221`), discarding the freshness/heat-adjusted relevance from `ContextService.query`, and confidence never enters the MCP-path ranking at all (the confidence multiplier in `sage/recall.py:compute_recall_score` is the brain-architecture path, which is not the live MCP path - see brain-cutover-blockers).
- What already exists and must NOT be duplicated: the trust gate (`mcp/tools/trust_gate.py`, applied in the `recall` verb) already WITHHOLDS unresolved-conflict and below-floor-confidence results. This plan adds ranking DEMOTION inside `context_query` so contested/low-evidence results sink even when the gate is off or `include_withheld=true`; withholding stays the gate's job.
- Multiplicative fusion `rerank * ((1-w) + w*confidence)` keeps rerank dominant (w=0.3 means a confidence-0 claim loses at most 30% of its score) while making evidence break ties. A research pass on fusion methods is running; its findings may amend default weights in the Calibration note below before execution, but the structure is parameterized so only config defaults would change.
- Missing data is never penalized (confidence absent = 1.0), mirroring `apply_trust_gate`.

**Out of scope (explicitly):** sage/recall.py brain path (gated by brain-cutover blockers), corroboration_count fusion (not present on QueryResult; needs a store-layer change - defer), populating the sage `ConfidenceBreakdown` dataclass (the fusion breakdown dict serves the transparency goal on the live path), changing trust-gate or evidence-enforcement defaults (hard-enforce mode already exists and is tested in `test_learn_soft_gate.py:38-44`), and - per Opus review - the `fusion_mode=True` (RRF) and graph-depth recall paths in `_context_recall` (context_recall.py:184-319): those fetch via `_context_get`/`_context_graph`/`FusionRetriever` and never pass through `_context_query`, so they get no epistemic fusion from this change. The primary semantic-query path (query + depth=0, which is the benchmark path and the default agent path) is covered; RRF/graph fusion is a fast-follow once this lands and is validated.

---

## File Structure

- Create: `src/context_service/reranking/epistemic_fusion.py` - pure fusion functions (no I/O, no settings import)
- Create: `tests/reranking/test_epistemic_fusion.py`
- Create: `tests/config/test_epistemic_fusion_settings.py`
- Create: `tests/mcp/tools/test_context_query_fusion.py`
- Modify: `src/context_service/config/settings.py` - add `EpistemicFusionConfig` (after `TrustGateConfig`, ~line 140) and attach to Settings (after `trust_gate`, line 991)
- Modify: `src/context_service/reranking/quality.py:86-131` - floor basis change in `apply_threshold_filter`
- Modify: `src/context_service/reranking/__init__.py` - export new functions
- Modify: `src/context_service/mcp/tools/context_query.py` - wire fusion after `_apply_reranking` (line 433-440), extend `raw_result_dicts` (line 454-470)
- Modify: `src/context_service/services/models.py:70-84` - add `superseded_by` to `QueryResult`
- Modify: `src/context_service/services/context.py:1541-1556` - populate `superseded_by`
- Modify: `tests/reranking/test_quality.py` - floor-basis tests
- Modify: `.env.example` - document the three new env vars

---

### Task 0: Branch

- [ ] **Step 1: Create the feature branch** (never commit to main - repo rule 6)

```bash
git checkout -b feat/read-path-epistemic-fusion
```

---

### Task 1: EpistemicFusionConfig settings

**Files:**
- Modify: `src/context_service/config/settings.py`
- Test: `tests/config/test_epistemic_fusion_settings.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for EpistemicFusionConfig (read-path epistemic fusion, sprint step 1)."""

from __future__ import annotations

from context_service.config.settings import EpistemicFusionConfig


class TestEpistemicFusionConfig:
    def test_defaults(self) -> None:
        cfg = EpistemicFusionConfig()
        assert cfg.enabled is True
        assert cfg.confidence_weight == 0.3
        assert cfg.conflict_penalty == 0.5

    def test_frozen(self) -> None:
        cfg = EpistemicFusionConfig()
        try:
            cfg.enabled = False  # type: ignore[misc]
            raised = False
        except Exception:
            raised = True
        assert raised

    def test_attached_to_settings(self) -> None:
        from context_service.config.settings import Settings

        assert "epistemic_fusion" in Settings.model_fields
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/config/test_epistemic_fusion_settings.py -v`
Expected: FAIL with `ImportError: cannot import name 'EpistemicFusionConfig'`

- [ ] **Step 3: Add the config class**

In `src/context_service/config/settings.py`, directly after the `TrustGateConfig` class (it starts at line 126; insert after its closing field, before `DecayClassConfig`):

```python
class EpistemicFusionConfig(BaseModel):
    """Settings for post-rerank epistemic score fusion.

    Reranker scores previously overwrote confidence/conflict signal in
    recall ranking; fusion multiplies the final relevance score by an
    epistemic adjustment so evidence state is load-bearing at read time.
    Withholding (trust gate) is separate and unaffected.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable epistemic score fusion")
    confidence_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description=(
            "Weight of node confidence in the fused score for knowledge/wisdom "
            "layers: factor = (1 - w) + w * confidence"
        ),
    )
    conflict_penalty: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Score multiplier applied to unresolved-contradiction nodes",
    )
```

Then attach to the Settings class after the `trust_gate` field (line 991):

```python
    epistemic_fusion: EpistemicFusionConfig = Field(default_factory=EpistemicFusionConfig)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/config/test_epistemic_fusion_settings.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/config/settings.py tests/config/test_epistemic_fusion_settings.py
git commit -m "feat(config): add EpistemicFusionConfig for read-path score fusion"
```

---

### Task 2: Pure fusion module

**Files:**
- Create: `src/context_service/reranking/epistemic_fusion.py`
- Modify: `src/context_service/reranking/__init__.py`
- Test: `tests/reranking/test_epistemic_fusion.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for epistemic score fusion (sprint step 1: read-path fix)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from context_service.reranking.epistemic_fusion import (
    apply_epistemic_fusion,
    compute_epistemic_adjustment,
)


@dataclass
class _FakeResult:
    node_id: str
    layer: str
    confidence: float | None
    relevance_score: float | None
    conflict_status: str = "none"
    created_at: datetime | None = None
    extras: dict = field(default_factory=dict)


class TestComputeEpistemicAdjustment:
    def test_knowledge_low_confidence_demoted(self) -> None:
        adj = compute_epistemic_adjustment(
            "knowledge", 0.2, "none", confidence_weight=0.3, conflict_penalty=0.5
        )
        # (1 - 0.3) + 0.3 * 0.2 = 0.76
        assert abs(adj.confidence_factor - 0.76) < 1e-9
        assert adj.conflict_factor == 1.0
        assert abs(adj.multiplier - 0.76) < 1e-9

    def test_memory_layer_ignores_confidence(self) -> None:
        adj = compute_epistemic_adjustment(
            "memory", 0.1, "none", confidence_weight=0.3, conflict_penalty=0.5
        )
        assert adj.confidence_factor == 1.0
        assert adj.multiplier == 1.0

    def test_intelligence_layer_ignores_confidence(self) -> None:
        adj = compute_epistemic_adjustment(
            "intelligence", 0.1, "none", confidence_weight=0.3, conflict_penalty=0.5
        )
        assert adj.multiplier == 1.0

    def test_unresolved_conflict_penalized_on_any_layer(self) -> None:
        adj = compute_epistemic_adjustment(
            "memory", None, "unresolved", confidence_weight=0.3, conflict_penalty=0.5
        )
        assert adj.conflict_factor == 0.5
        assert adj.multiplier == 0.5

    def test_missing_confidence_not_penalized(self) -> None:
        adj = compute_epistemic_adjustment(
            "knowledge", None, "none", confidence_weight=0.3, conflict_penalty=0.5
        )
        assert adj.confidence_factor == 1.0

    def test_uppercase_layer_normalized(self) -> None:
        adj = compute_epistemic_adjustment(
            "KNOWLEDGE", 0.0, "none", confidence_weight=0.3, conflict_penalty=0.5
        )
        # (1 - 0.3) + 0.3 * 0.0 = 0.7
        assert abs(adj.confidence_factor - 0.7) < 1e-9

    def test_confidence_clamped(self) -> None:
        adj = compute_epistemic_adjustment(
            "knowledge", 1.7, "none", confidence_weight=0.3, conflict_penalty=0.5
        )
        assert adj.confidence_factor == 1.0

    def test_to_dict_shape(self) -> None:
        adj = compute_epistemic_adjustment(
            "wisdom", 0.5, "unresolved", confidence_weight=0.4, conflict_penalty=0.6
        )
        d = adj.to_dict()
        assert set(d) == {"multiplier", "confidence_factor", "conflict_factor"}


class TestApplyEpistemicFusion:
    def test_high_evidence_claim_overtakes_low_evidence(self) -> None:
        # Low-confidence claim reranked higher than high-confidence claim.
        low = _FakeResult("low", "knowledge", 0.1, 0.80)
        high = _FakeResult("high", "knowledge", 1.0, 0.70)
        results = [low, high]
        adjustments = apply_epistemic_fusion(
            results, confidence_weight=0.5, conflict_penalty=0.5
        )
        # low: 0.80 * (0.5 + 0.5*0.1) = 0.44; high: 0.70 * 1.0 = 0.70
        assert [r.node_id for r in results] == ["high", "low"]
        assert abs(results[1].relevance_score - 0.44) < 1e-9
        assert set(adjustments) == {"low", "high"}

    def test_none_score_left_untouched(self) -> None:
        r = _FakeResult("a", "knowledge", 0.1, None)
        apply_epistemic_fusion([r], confidence_weight=0.5, conflict_penalty=0.5)
        assert r.relevance_score is None

    def test_unresolved_conflict_sinks(self) -> None:
        contested = _FakeResult("c", "memory", None, 0.9, conflict_status="unresolved")
        clean = _FakeResult("k", "memory", None, 0.6)
        results = [contested, clean]
        apply_epistemic_fusion(results, confidence_weight=0.3, conflict_penalty=0.5)
        # contested: 0.9 * 0.5 = 0.45 < clean 0.6
        assert [r.node_id for r in results] == ["k", "c"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/reranking/test_epistemic_fusion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'context_service.reranking.epistemic_fusion'`

- [ ] **Step 3: Write the module**

Create `src/context_service/reranking/epistemic_fusion.py`:

```python
"""Epistemic score fusion: make evidence state survive reranking.

Reranker scores overwrite relevance_score wholesale (context_query
_apply_reranking), which made confidence and conflict state invisible to
final ranking. This module multiplies post-rerank scores by a deterministic
epistemic adjustment and re-sorts. Pure functions only: no I/O, no settings
access, callers pass weights explicitly.

Demotion only. Withholding unresolved conflicts / low confidence remains
the trust gate's job (mcp/tools/trust_gate.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Layers whose nodes carry evidence-derived confidence. Memory freshness and
# heat are already fused upstream in ContextService.query; intelligence has
# no decay semantics by design.
_EVIDENCE_LAYERS = frozenset({"knowledge", "wisdom"})


@dataclass(frozen=True)
class EpistemicAdjustment:
    """Per-result fusion breakdown, surfaced in recall output for transparency."""

    multiplier: float
    confidence_factor: float
    conflict_factor: float

    def to_dict(self) -> dict[str, float]:
        return {
            "multiplier": self.multiplier,
            "confidence_factor": self.confidence_factor,
            "conflict_factor": self.conflict_factor,
        }


def compute_epistemic_adjustment(
    layer: str,
    confidence: float | None,
    conflict_status: str | None,
    *,
    confidence_weight: float,
    conflict_penalty: float,
) -> EpistemicAdjustment:
    """Compute the score multiplier for one result.

    confidence_factor = (1 - w) + w * confidence for knowledge/wisdom layers,
    1.0 otherwise. Missing confidence is treated as 1.0 (never penalize
    absent data, mirroring apply_trust_gate). conflict_factor applies the
    penalty to unresolved contradictions on any layer.
    """
    confidence_factor = 1.0
    if (layer or "").lower() in _EVIDENCE_LAYERS and confidence is not None:
        conf = max(0.0, min(1.0, float(confidence)))
        confidence_factor = (1.0 - confidence_weight) + confidence_weight * conf

    conflict_factor = (
        conflict_penalty if (conflict_status or "none") == "unresolved" else 1.0
    )
    return EpistemicAdjustment(
        multiplier=confidence_factor * conflict_factor,
        confidence_factor=confidence_factor,
        conflict_factor=conflict_factor,
    )


def apply_epistemic_fusion(
    results: list[Any],
    *,
    confidence_weight: float,
    conflict_penalty: float,
) -> dict[str, EpistemicAdjustment]:
    """Scale each result's relevance_score in place and re-sort descending.

    Results are any objects with node_id, layer, confidence, conflict_status,
    and relevance_score attributes (QueryResult in production). Results with
    relevance_score None are left unscored but still sorted (None sorts last).

    Returns adjustments keyed by str(node_id) for breakdown surfacing.
    """
    adjustments: dict[str, EpistemicAdjustment] = {}
    for r in results:
        adj = compute_epistemic_adjustment(
            getattr(r, "layer", "") or "",
            getattr(r, "confidence", None),
            getattr(r, "conflict_status", None),
            confidence_weight=confidence_weight,
            conflict_penalty=conflict_penalty,
        )
        adjustments[str(r.node_id)] = adj
        score = getattr(r, "relevance_score", None)
        if score is not None:
            r.relevance_score = float(score) * adj.multiplier
    results.sort(
        key=lambda r: r.relevance_score if r.relevance_score is not None else -1.0,
        reverse=True,
    )
    return adjustments
```

Add exports to `src/context_service/reranking/__init__.py` (keep `__all__` sorted):

```python
from context_service.reranking.epistemic_fusion import (
    EpistemicAdjustment,
    apply_epistemic_fusion,
    compute_epistemic_adjustment,
)
```

and add `"EpistemicAdjustment"`, `"apply_epistemic_fusion"`, `"compute_epistemic_adjustment"` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/reranking/test_epistemic_fusion.py -v`
Expected: 12 PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/reranking/epistemic_fusion.py src/context_service/reranking/__init__.py tests/reranking/test_epistemic_fusion.py
git commit -m "feat(reranking): pure epistemic score fusion module"
```

---

### Task 3: Abstention floor uses pre-fusion rerank score

Fusion shrinks scores (max multiplier 1.0). RERANK_SCORE_FLOOR (0.05) exists for abstention honesty and is calibrated against raw reranker output, so the floor must compare against the PRE-fusion score when available. The per-layer thresholds and adaptive tau operate on fused scores (tau is relative: alpha * max fused score), which is correct as-is.

**Files:**
- Modify: `src/context_service/reranking/quality.py:112-130`
- Test: `tests/reranking/test_quality.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/reranking/test_quality.py`, matching its existing style)

```python
class TestThresholdFilterRerankScoreBasis:
    def test_floor_uses_rerank_score_when_present(self) -> None:
        # Fused relevance dropped below floor, but raw rerank score is above:
        # the result must be KEPT (floor judges reranker calibration, not fusion).
        results = [
            {"layer": "knowledge", "relevance_score": 0.03, "rerank_score": 0.40},
        ]
        kept, below = apply_threshold_filter(results, rerank_floor=0.05)
        assert len(kept) == 1
        assert below == 0

    def test_floor_drops_when_rerank_score_below(self) -> None:
        results = [
            {"layer": "knowledge", "relevance_score": 0.04, "rerank_score": 0.04},
        ]
        kept, below = apply_threshold_filter(results, rerank_floor=0.05)
        assert kept == []
        assert below == 1

    def test_floor_falls_back_to_relevance_score(self) -> None:
        # No rerank_score key (older callers): behavior unchanged.
        results = [{"layer": "memory", "relevance_score": 0.04}]
        kept, below = apply_threshold_filter(results, rerank_floor=0.05)
        assert kept == []
        assert below == 1

    def test_min_threshold_also_uses_rerank_basis(self) -> None:
        # Fused (post-fusion) score is for ORDERING only; floor AND adaptive
        # tau both judge the raw rerank score (research: threshold semantics
        # become incoherent if tau shifts with confidence multipliers).
        results = [
            {"layer": "knowledge", "relevance_score": 0.10, "rerank_score": 0.90},
        ]
        kept, below = apply_threshold_filter(
            results, rerank_floor=0.05, min_threshold=0.20
        )
        assert len(kept) == 1
        assert below == 0

    def test_adaptive_threshold_score_key(self) -> None:
        results = [
            {"layer": "knowledge", "relevance_score": 0.40, "rerank_score": 0.90},
            {"layer": "knowledge", "relevance_score": 0.30, "rerank_score": 0.50},
        ]
        tau, max_score = compute_adaptive_threshold(
            results, alpha=0.7, score_key="rerank_score"
        )
        assert max_score == 0.90
        assert tau == pytest.approx(0.63)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/reranking/test_quality.py -k RerankScoreBasis -v`
Expected: `test_floor_uses_rerank_score_when_present` FAILS (result is dropped); the fallback tests may already pass.

- [ ] **Step 3: Change the floor basis in `apply_threshold_filter`**

In `src/context_service/reranking/quality.py`, replace the `if rerank_floor is not None:` branch (lines 118-121) and the trailing comparison so the rerank-floor path is self-contained:

```python
        if rerank_floor is not None:
            # Floor and adaptive tau judge reranker calibration ("is this about
            # the query at all"); fusion (epistemic multipliers) shrinks
            # relevance_score and is for ordering only, so threshold against
            # the pre-fusion score when the caller provided one.
            floor_basis = r.get("rerank_score")
            if not isinstance(floor_basis, (int, float)):
                floor_basis = score
            threshold: float = rerank_floor
            if min_threshold is not None:
                threshold = max(rerank_floor, min_threshold)
            if float(floor_basis) >= threshold:
                kept.append(r)
            else:
                below += 1
            continue
        layer = r.get("layer", "memory")
        threshold = _threshold_for_layer(layer, threshold_overrides)
        if min_threshold is not None:
            threshold = max(threshold, min_threshold)
        if score >= threshold:
            kept.append(r)
        else:
            below += 1
```

(Also update the docstring sentence about `rerank_floor` to mention the `rerank_score` basis.)

Additionally, give `compute_adaptive_threshold` a score-key parameter so tau can be computed on the pre-fusion basis (quality.py:55-83):

```python
def compute_adaptive_threshold(
    results: list[dict[str, Any]],
    alpha: float = 0.7,
    floor: float = 0.2,
    score_key: str = "relevance_score",
) -> tuple[float, float]:
```

and inside the loop read `r.get(score_key)` instead of `r.get("relevance_score")` (keep the isinstance numeric check unchanged).

Same treatment for `compute_retrieval_quality` (Opus review B6: quality buckets average `relevance_score`, and fused scores shrink, so quality labels would turn systematically pessimistic when fusion demotes). Add the same parameter (quality.py:134-186):

```python
def compute_retrieval_quality(
    kept: list[dict[str, Any]],
    below_threshold: int,
    fallback_used: bool = False,
    score_key: str = "relevance_score",
) -> tuple[RetrievalQuality, str | None]:
```

and in the score collection read `r.get(score_key)` with a fallback to `r.get("relevance_score")` when the keyed value is not numeric. Quality classification judges retrieval relevance, same as the floor and tau; the epistemic verdict is carried separately by the `epistemic` breakdown and `conflict_status`.

Test (append to the same test class):

```python
    def test_quality_uses_rerank_basis(self) -> None:
        kept = [
            {"layer": "knowledge", "relevance_score": 0.45, "rerank_score": 0.80},
        ]
        quality, _ = compute_retrieval_quality(kept, 0, score_key="rerank_score")
        assert quality == "high"
```

- [ ] **Step 4: Run the full quality test file**

Run: `uv run pytest tests/reranking/test_quality.py -v`
Expected: all PASS (existing tests must not regress)

- [ ] **Step 5: Commit**

```bash
git add src/context_service/reranking/quality.py tests/reranking/test_quality.py
git commit -m "feat(reranking): abstention floor compares pre-fusion rerank score"
```

---

### Task 4: Surface superseded_by on QueryResult

Small and independent; do it before the wiring task so the wiring task can surface the field.

**Files:**
- Modify: `src/context_service/services/models.py:70-84`
- Modify: `src/context_service/services/context.py:1541-1556`
- Test: covered by Task 5's wiring test plus the type checker; no store round-trip needed (props passthrough).

- [ ] **Step 1: Add the field to QueryResult** (`services/models.py`, after `tier`)

```python
    superseded_by: str | None = None
```

- [ ] **Step 2: Populate it in ContextService.query** (`services/context.py`, in the `QueryResult(` construction at line 1541, after `tier=props.get("tier"),`)

```python
                    superseded_by=(
                        str(props["superseded_by"]) if props.get("superseded_by") else None
                    ),
```

Note: with default `include_superseded=False` this is always None (superseded nodes are dropped at line 1499); it carries signal when callers pass `include_superseded=True`, which is exactly the history/audit use case.

- [ ] **Step 3: Typecheck**

Run: `just check`
Expected: PASS (mypy strict accepts the new optional field)

- [ ] **Step 4: Commit**

```bash
git add src/context_service/services/models.py src/context_service/services/context.py
git commit -m "feat(services): expose superseded_by on QueryResult"
```

---

### Task 5: Wire fusion into the context_query read path

**Files:**
- Modify: `src/context_service/mcp/tools/context_query.py`
- Test: `tests/mcp/tools/test_context_query_fusion.py`

- [ ] **Step 1: Write the failing test** (modeled on `tests/mcp/tools/test_context_query_reranking.py`; use plain dataclass fakes, not MagicMock results, so attribute mutation works)

```python
"""Tests for epistemic fusion wiring in _context_query (sprint step 1)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class _FakeQueryResult:
    node_id: str
    layer: str
    content: str
    confidence: float
    relevance_score: float
    summary: str | None = None
    tags: list[str] | None = None
    created_at: None = None
    conflict_status: str = "none"
    credibility: float = 0.0
    credibility_factors: dict | None = None
    tier: str | None = None
    superseded_by: str | None = None


def _settings(fusion_enabled: bool = True) -> MagicMock:
    s = MagicMock()
    s.reranking.enabled = False  # isolate fusion from reranking
    s.reranking.adaptive_threshold_enabled = False
    s.reranking.expand_hard_queries = False
    s.causal.query_enabled = False
    s.epistemic_fusion.enabled = fusion_enabled
    s.epistemic_fusion.confidence_weight = 0.5
    s.epistemic_fusion.conflict_penalty = 0.5
    s.result_cache.memory_ttl = 300
    s.result_cache.knowledge_ttl = 3600
    s.result_cache.wisdom_ttl = 1800
    return s


def _silo_service() -> MagicMock:
    silo = MagicMock()
    silo.metadata = {}
    svc = MagicMock()
    svc.get_by_id = AsyncMock(return_value=silo)
    return svc


@pytest.mark.asyncio
async def test_fusion_reorders_and_surfaces_breakdown() -> None:
    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    low_evidence = _FakeQueryResult(
        node_id="low", layer="knowledge", content="unsourced claim",
        confidence=0.1, relevance_score=0.80,
    )
    high_evidence = _FakeQueryResult(
        node_id="high", layer="knowledge", content="corroborated fact",
        confidence=1.0, relevance_score=0.70, superseded_by=None,
    )

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=mock_auth,
        ),
        patch("context_service.mcp.tools.context_query.get_context_service") as mock_svc,
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=_silo_service(),
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "context_service.mcp.tools.context_query.get_settings",
            return_value=_settings(),
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
    ):
        mock_svc.return_value.query = AsyncMock(
            return_value=[low_evidence, high_evidence]
        )
        mock_svc.return_value.vector_store = None
        mock_svc.return_value.embedding_client = None

        from context_service.mcp.tools.context_query import _context_query

        result = await _context_query(
            silo_id="test-silo", query="auth method", top_k=10, bypass_cache=True
        )

    ids = [r["node_id"] for r in result["results"]]
    # fused: low = 0.80 * (0.5 + 0.5*0.1) = 0.44; high = 0.70 * 1.0 = 0.70
    assert ids == ["high", "low"]
    low_dict = next(r for r in result["results"] if r["node_id"] == "low")
    assert low_dict["epistemic"]["confidence_factor"] == pytest.approx(0.55)
    assert low_dict["epistemic"]["multiplier"] == pytest.approx(0.55)
    assert low_dict["relevance_score"] == pytest.approx(0.44)
    assert "superseded_by" in low_dict
    # Reranking did not run, so no rerank_score basis is exposed.
    assert low_dict["rerank_score"] is None


@pytest.mark.asyncio
async def test_fusion_disabled_preserves_order() -> None:
    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    low_evidence = _FakeQueryResult(
        node_id="low", layer="knowledge", content="unsourced claim",
        confidence=0.1, relevance_score=0.80,
    )
    high_evidence = _FakeQueryResult(
        node_id="high", layer="knowledge", content="corroborated fact",
        confidence=1.0, relevance_score=0.70,
    )

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=mock_auth,
        ),
        patch("context_service.mcp.tools.context_query.get_context_service") as mock_svc,
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=_silo_service(),
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "context_service.mcp.tools.context_query.get_settings",
            return_value=_settings(fusion_enabled=False),
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
    ):
        mock_svc.return_value.query = AsyncMock(
            return_value=[low_evidence, high_evidence]
        )
        mock_svc.return_value.vector_store = None
        mock_svc.return_value.embedding_client = None

        from context_service.mcp.tools.context_query import _context_query

        result = await _context_query(
            silo_id="test-silo", query="auth method", top_k=10, bypass_cache=True
        )

    ids = [r["node_id"] for r in result["results"]]
    assert ids == ["low", "high"]
    assert result["results"][0].get("epistemic") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_context_query_fusion.py -v`
Expected: FAIL - first test gets `["low", "high"]` order and KeyError/None on `"epistemic"`.

- [ ] **Step 3: Wire fusion into `_context_query`**

In `src/context_service/mcp/tools/context_query.py`:

Add the import (with the other reranking imports at line 25-33):

```python
from context_service.reranking.epistemic_fusion import (
    EpistemicAdjustment,
    apply_epistemic_fusion,
)
```

Directly after the `_apply_reranking` call (after line 440, before `_emit_access_events`):

```python
    # Epistemic fusion: scale post-rerank scores by confidence/conflict state
    # so evidence is load-bearing in final ranking (sprint step 1). The
    # pre-fusion score is kept per node: the abstention floor in
    # apply_threshold_filter compares against it when reranking ran.
    epistemic_adjustments: dict[str, EpistemicAdjustment] = {}
    prefusion_scores: dict[str, float | None] = {}
    if settings.epistemic_fusion.enabled:
        prefusion_scores = {str(r.node_id): r.relevance_score for r in results}
        epistemic_adjustments = apply_epistemic_fusion(
            results,
            confidence_weight=settings.epistemic_fusion.confidence_weight,
            conflict_penalty=settings.epistemic_fusion.conflict_penalty,
        )
```

Extend `raw_result_dicts` (the dict literal at lines 454-470) with three entries:

```python
            "superseded_by": r.superseded_by,
            "rerank_score": (
                prefusion_scores.get(str(r.node_id)) if reranked_applied else None
            ),
            "epistemic": (
                epistemic_adjustments[str(r.node_id)].to_dict()
                if str(r.node_id) in epistemic_adjustments
                else None
            ),
```

No change needed in the threshold call: `apply_threshold_filter` already receives the dicts and (from Task 3) prefers `rerank_score` as the floor basis when present.

Also update the adaptive-threshold block (lines 482-503) so tau is computed on the pre-fusion basis:

```python
    score_basis_key = (
        "rerank_score"
        if settings.epistemic_fusion.enabled and reranked_applied
        else "relevance_score"
    )
    effective_min_threshold = min_threshold
    if settings.reranking.adaptive_threshold_enabled and reranked_applied:
        adaptive_tau, max_score = compute_adaptive_threshold(
            raw_result_dicts,
            alpha=settings.reranking.adaptive_alpha,
            score_key=score_basis_key,
        )
        if effective_min_threshold is None or adaptive_tau > effective_min_threshold:
            effective_min_threshold = adaptive_tau

        def _score_above_tau(r: dict[str, Any]) -> bool:
            s = r.get(score_basis_key)
            return isinstance(s, (int, float)) and float(s) >= adaptive_tau

        kept_count = len(list(filter(_score_above_tau, raw_result_dicts)))
        record_adaptive_threshold(
            tau=adaptive_tau,
            max_score=max_score,
            kept=kept_count,
            filtered=len(raw_result_dicts) - kept_count,
            silo_id=silo_id,
        )
```

And pass the same basis to the quality computation (line 512):

```python
    retrieval_quality, suggestion = compute_retrieval_quality(
        result_dicts, below_threshold, fallback_used=rerank_fallback,
        score_key=score_basis_key,
    )
```

(`score_basis_key` is defined above the adaptive block, so it is in scope whether or not adaptive thresholding ran.)

- [ ] **Step 4: Run the new tests plus the neighboring suites**

MANDATORY (Opus review B3, not conditional): existing tests that drive `_context_query` with bare `MagicMock()` settings WILL break - fusion runs with a MagicMock `confidence_weight`, producing MagicMock scores that raise `TypeError` in the sort. Before running, grep for every such test and add `mock_settings.epistemic_fusion.enabled = False` (one line each, do not weaken assertions):

```bash
grep -rln "get_settings" tests/mcp/tools/ | xargs grep -l "_context_query\|_context_recall"
```

At minimum: `test_context_query_reranking.py` (both tests) and any cache test that drives `_context_query` end-to-end.

Run: `uv run pytest tests/mcp/tools/test_context_query_fusion.py tests/mcp/tools/test_context_query_reranking.py tests/mcp/tools/test_context_query_cache.py tests/mcp/tools/test_recall_trust_gate.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/context_query.py tests/mcp/tools/test_context_query_fusion.py tests/mcp/tools/test_context_query_reranking.py
git commit -m "feat(recall): fuse epistemic state into post-rerank ranking"
```

---

### Task 6: Document env vars

**Files:**
- Modify: `.env.example` (note: this file already has uncommitted changes in the working tree - append only, do not revert anything)

- [ ] **Step 1: Append the new settings block** (follow the file's existing nested-config naming convention - check how `TRUST_GATE` or `EVIDENCE_ENFORCEMENT` vars are spelled in the file and mirror it; pydantic nested delimiter is `__`)

```bash
# Epistemic score fusion (read path). Confidence and conflict state scale
# post-rerank relevance so evidence is load-bearing at recall time.
# EPISTEMIC_FUSION__ENABLED=true
# EPISTEMIC_FUSION__CONFIDENCE_WEIGHT=0.3
# EPISTEMIC_FUSION__CONFLICT_PENALTY=0.5
```

- [ ] **Step 2: Verify the prefix matches** how existing nested vars are spelled in `.env.example` (e.g. if evidence enforcement appears as `EVIDENCE_ENFORCEMENT__ENFORCE`, keep the same style; if the file uses a global app prefix, apply it).

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs(env): document epistemic fusion settings"
```

---

### Task 7: Full verification

- [ ] **Step 1: Lint + typecheck**

Run: `just check`
Expected: PASS (mypy strict + ruff). Fix any findings before proceeding.

- [ ] **Step 2: Full test suite**

Run: `just test`
Expected: no NEW failures relative to main. Known pre-existing debt: ~31 tests failing from outdated signatures/mocks (see project memory "Test debt") - compare against a main-branch run if unsure: `git stash && just test 2>&1 | tail -5 && git stash pop` is NOT safe with a branch; instead run `git checkout main && just test` in a separate worktree if needed, or rely on CI.

- [ ] **Step 3: Mark step 1 done in the sprint plan**

Edit `context/plans/2026-06-11-defensibility-sprint.md`: under "Steps", annotate step 1 with `(DONE - see 2026-06-11-step1-read-path-epistemic-fusion.md)`.

- [ ] **Step 4: Commit and prepare PR**

```bash
git add context/plans/2026-06-11-defensibility-sprint.md
git commit -m "docs(plans): mark sprint step 1 read-path fusion complete"
git push -u origin feat/read-path-epistemic-fusion
```

PR title: `feat(recall): epistemic score fusion on the read path`. Body should cite the moat-audit finding (reranker overwrote epistemic signal) and the benchmark dependency.

---

## Calibration note (research findings, 2026-06-11)

A web research pass on score-fusion methods completed before plan finalization. Findings that shaped this plan:

- **The dampened multiplicative form is validated**: `final = rerank * ((1-w) + w*signal)` matches Elastic's recommended multiplicative-boost pattern for query-independent priors (scale-invariant to per-query rerank score distributions) and CrAM (AAAI 2025), which down-weights influence multiplicatively by credibility in [0,1]. Never use a bare `* confidence` multiplier - a 0.1-confidence node would be annihilated regardless of relevance (the exact inverse of the current bug).
- **Thresholds on pre-fusion scores** (incorporated in Tasks 3/5): abstention literature says floors should key on evidence relevance ("is this about the query"), not composite scores; adaptive tau on fused scores would shift with whichever document happens to be high-confidence. Fused scores are for ordering only.
- **Defaults**: W_CONF=0.3 and conflict_penalty=0.5 confirmed as sound starting points. Tune on the LongMemEval benchmark in this order: confidence_weight first, then conflict_penalty sweep {0.3, 0.5, 0.7}. Ablate each signal to w=0 and confirm metric movement - weights below ~0.1 tend to be decorative (lesson from arXiv 2509.19376: too-small weights make the signal non-load-bearing, which is this bug in general form).
- **Deferred follow-ups** (benchmark-gated, do NOT add to v1):
  1. Per-query min-max normalization of rerank scores before fusion (worth it if the TEI/LiteLLM reranker emits uncalibrated logits; changes retrieval_quality bucket semantics, so do it as its own change).
  2. Post-rerank freshness multiplier with per-layer half-life (memory ~14d, knowledge ~90d, wisdom none). Today freshness is applied pre-rerank and the reranker overwrites it, so freshness only affects candidate selection - same decorative-signal failure class. Watch for double-decay if added.
  3. Credibility (W~0.15) and capped corroboration (W~0.1) multipliers - corroboration_count is not on QueryResult yet.
  4. Keep heat OUT of post-rerank fusion (retrieval-popularity feedback loop).
- **Conflict handling stance**: the conflict-RAG literature (MADAM-RAG, ArbGraph) prefers surfacing conflicts to the generator over suppression. Engrammic's demote (this plan) + withhold (trust gate) + conflict_status in payload is stricter than literature but coherent for an epistemic product; the surfaced flag satisfies the transparency recommendation.

Key sources: Elastic multiplicative boosting, Vespa phased ranking, CrAM (arXiv 2406.11497), CONFACT (IJCAI 2025), freshness-in-RAG (arXiv 2509.19376), RALM abstention (arXiv 2509.01476), Cohere rerank best practices.

## Self-review notes

- Spec coverage vs sprint step 1: rerank fusion (Tasks 2+5), contradiction demotion (penalty in Task 2; withholding already exists via trust gate - documented in scope note), provenance surfacing (Task 4 superseded_by + Task 5 epistemic breakdown), ConfidenceBreakdown population (consciously replaced by the fusion breakdown dict on the live path - sage dataclass is the non-live brain path), hard enforcement mode (already implemented and tested; only env documentation added in Task 6).
- Result cache: fused dicts are cached post-fusion; a fusion-config change can serve stale rankings for up to the layer TTL (max 1h). Acceptable; cache keys already include knowledge_version for data changes.
- Type consistency check: `EpistemicAdjustment.to_dict()` used in Task 5 matches Task 2 definition; `rerank_score`/`epistemic`/`superseded_by` dict keys consistent between Task 3 filter, Task 5 wiring, and tests.
