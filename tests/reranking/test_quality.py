"""Tests for retrieval-worthiness classification."""

from __future__ import annotations

import pytest

from context_service.reranking.quality import (
    LAYER_THRESHOLDS,
    RERANK_SCORE_FLOOR,
    apply_threshold_filter,
    classify_quality,
    compute_adaptive_threshold,
    compute_retrieval_quality,
)


class TestLayerThresholds:
    def test_defaults_present(self) -> None:
        assert LAYER_THRESHOLDS["knowledge"] == 0.35
        assert LAYER_THRESHOLDS["wisdom"] == 0.35
        assert LAYER_THRESHOLDS["memory"] == 0.25
        assert LAYER_THRESHOLDS["intelligence"] == 0.25

    def test_knowledge_stricter_than_memory(self) -> None:
        assert LAYER_THRESHOLDS["knowledge"] > LAYER_THRESHOLDS["memory"]


class TestClassifyQuality:
    @pytest.mark.parametrize(
        "avg,expected",
        [
            (0.7, "high"),
            (0.61, "high"),
            (0.6, "partial"),
            (0.5, "partial"),
            (0.4, "partial"),
            (0.39, "low"),
            (0.0, "low"),
        ],
    )
    def test_buckets(self, avg: float, expected: str) -> None:
        assert classify_quality(avg) == expected


class TestApplyThresholdFilter:
    def _make_result(self, layer: str, score: float) -> dict:
        return {"node_id": "n", "layer": layer, "relevance_score": score, "content": ""}

    def test_filters_below_knowledge_threshold(self) -> None:
        results = [
            self._make_result("knowledge", 0.6),
            self._make_result("knowledge", 0.3),  # below 0.35
        ]
        kept, below = apply_threshold_filter(results)
        assert len(kept) == 1
        assert kept[0]["relevance_score"] == 0.6
        assert below == 1

    def test_filters_below_memory_threshold(self) -> None:
        results = [
            self._make_result("memory", 0.35),
            self._make_result("memory", 0.2),  # below 0.25
        ]
        kept, below = apply_threshold_filter(results)
        assert len(kept) == 1
        assert below == 1

    def test_no_score_passthrough(self) -> None:
        results = [{"node_id": "n", "layer": "knowledge", "content": ""}]
        kept, below = apply_threshold_filter(results)
        assert len(kept) == 1
        assert below == 0

    def test_per_silo_override(self) -> None:
        results = [
            self._make_result("knowledge", 0.30),  # below default 0.35 but above override 0.25
        ]
        kept, below = apply_threshold_filter(results, threshold_overrides={"knowledge": 0.25})
        assert len(kept) == 1
        assert below == 0

    def test_all_filtered(self) -> None:
        results = [
            self._make_result("knowledge", 0.1),
            self._make_result("wisdom", 0.2),
        ]
        kept, below = apply_threshold_filter(results)
        assert kept == []
        assert below == 2

    def test_unknown_layer_uses_memory_threshold(self) -> None:
        results = [
            {"node_id": "n", "layer": "unknown_layer", "relevance_score": 0.20, "content": ""},
        ]
        # 0.20 < 0.25 (memory fallback) -> filtered
        kept, below = apply_threshold_filter(results)
        assert kept == []
        assert below == 1

    def test_min_threshold_override(self) -> None:
        results = [
            self._make_result("knowledge", 0.25),
            self._make_result("wisdom", 0.25),
        ]
        kept, below = apply_threshold_filter(results, min_threshold=0.2)
        assert len(kept) == 2
        assert below == 0

    def test_bypass_skips_all_filtering(self) -> None:
        results = [
            self._make_result("knowledge", 0.1),
            self._make_result("wisdom", 0.05),
        ]
        kept, below = apply_threshold_filter(results, bypass=True)
        assert len(kept) == 2
        assert below == 0

    def test_rerank_floor_constant_is_nonzero(self) -> None:
        assert RERANK_SCORE_FLOOR > 0.0

    def test_rerank_floor_keeps_above_floor(self) -> None:
        results = [
            self._make_result("knowledge", 0.05),  # exactly at floor
            self._make_result("memory", 0.10),  # above floor
        ]
        kept, below = apply_threshold_filter(results, rerank_floor=RERANK_SCORE_FLOOR)
        assert len(kept) == 2
        assert below == 0

    def test_rerank_floor_drops_below_floor(self) -> None:
        results = [
            self._make_result("knowledge", 0.04),  # below 0.05 floor
            self._make_result("memory", 0.80),  # above floor
        ]
        kept, below = apply_threshold_filter(results, rerank_floor=RERANK_SCORE_FLOOR)
        assert len(kept) == 1
        assert kept[0]["relevance_score"] == 0.80
        assert below == 1

    def test_rerank_floor_ignores_per_layer_thresholds(self) -> None:
        # knowledge floor is 0.35, but with rerank_floor=0.05 a score of 0.20 should pass
        results = [
            self._make_result("knowledge", 0.20),
        ]
        kept, below = apply_threshold_filter(results, rerank_floor=0.05)
        assert len(kept) == 1
        assert below == 0

    def test_rerank_floor_bypass_returns_all(self) -> None:
        results = [
            self._make_result("knowledge", 0.01),  # below floor
            self._make_result("memory", 0.02),  # below floor
        ]
        kept, below = apply_threshold_filter(results, rerank_floor=0.05, bypass=True)
        assert len(kept) == 2
        assert below == 0

    def test_rerank_floor_none_score_passthrough(self) -> None:
        results = [{"node_id": "n", "layer": "knowledge", "content": ""}]
        kept, below = apply_threshold_filter(results, rerank_floor=0.05)
        assert len(kept) == 1
        assert below == 0

    def test_rerank_floor_min_threshold_lowers_effective_floor(self) -> None:
        # min_threshold=0.02 < rerank_floor=0.05 -> effective floor is 0.02
        results = [
            self._make_result("knowledge", 0.03),  # between 0.02 and 0.05
            self._make_result("knowledge", 0.01),  # below 0.02
        ]
        kept, below = apply_threshold_filter(results, rerank_floor=0.05, min_threshold=0.02)
        assert len(kept) == 1
        assert kept[0]["relevance_score"] == 0.03
        assert below == 1


class TestComputeRetrievalQuality:
    def _result(self, score: float) -> dict:
        return {"node_id": "n", "layer": "knowledge", "relevance_score": score}

    def test_high_quality(self) -> None:
        kept = [self._result(0.8), self._result(0.75)]
        quality, suggestion = compute_retrieval_quality(kept, below_threshold=0)
        assert quality == "high"
        assert suggestion is None

    def test_partial_quality(self) -> None:
        kept = [self._result(0.5), self._result(0.55)]
        quality, suggestion = compute_retrieval_quality(kept, below_threshold=0)
        assert quality == "partial"
        assert suggestion is not None

    def test_low_quality(self) -> None:
        kept = [self._result(0.35), self._result(0.32)]
        quality, suggestion = compute_retrieval_quality(kept, below_threshold=0)
        assert quality == "low"
        assert suggestion is not None

    def test_none_quality_empty_results(self) -> None:
        quality, suggestion = compute_retrieval_quality([], below_threshold=3)
        assert quality == "none"
        assert suggestion is not None

    def test_below_threshold_appended_to_suggestion(self) -> None:
        kept = [self._result(0.5)]
        quality, suggestion = compute_retrieval_quality(kept, below_threshold=2)
        assert quality == "partial"
        assert suggestion is not None
        assert "2" in suggestion

    def test_fallback_caps_high_to_partial(self) -> None:
        kept = [self._result(0.9), self._result(0.85)]
        quality, suggestion = compute_retrieval_quality(kept, below_threshold=0, fallback_used=True)
        assert quality == "partial"

    def test_fallback_does_not_change_low(self) -> None:
        kept = [self._result(0.2)]
        quality, _ = compute_retrieval_quality(kept, below_threshold=0, fallback_used=True)
        assert quality == "low"

    def test_no_scores_returns_high(self) -> None:
        kept = [{"node_id": "n", "layer": "knowledge"}]
        quality, suggestion = compute_retrieval_quality(kept, below_threshold=0)
        assert quality == "high"
        assert suggestion is None


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
        results = [
            {"layer": "knowledge", "relevance_score": 0.10, "rerank_score": 0.90},
        ]
        kept, below = apply_threshold_filter(results, rerank_floor=0.05, min_threshold=0.20)
        assert len(kept) == 1
        assert below == 0

    def test_adaptive_threshold_score_key(self) -> None:
        results = [
            {"layer": "knowledge", "relevance_score": 0.40, "rerank_score": 0.90},
            {"layer": "knowledge", "relevance_score": 0.30, "rerank_score": 0.50},
        ]
        tau, max_score = compute_adaptive_threshold(results, alpha=0.7, score_key="rerank_score")
        assert max_score == 0.90
        assert tau == pytest.approx(0.63)

    def test_quality_uses_rerank_basis(self) -> None:
        kept = [
            {"layer": "knowledge", "relevance_score": 0.45, "rerank_score": 0.80},
        ]
        quality, _ = compute_retrieval_quality(kept, 0, score_key="rerank_score")
        assert quality == "high"
