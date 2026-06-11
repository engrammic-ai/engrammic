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
        adjustments = apply_epistemic_fusion(results, confidence_weight=0.5, conflict_penalty=0.5)
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
