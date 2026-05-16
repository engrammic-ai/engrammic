"""Tests for retrieval-worthiness classification."""

from __future__ import annotations

import pytest

from context_service.reranking.quality import (
    LAYER_THRESHOLDS,
    apply_threshold_filter,
    classify_quality,
    compute_retrieval_quality,
)


class TestLayerThresholds:
    def test_defaults_present(self) -> None:
        assert LAYER_THRESHOLDS["knowledge"] == 0.5
        assert LAYER_THRESHOLDS["wisdom"] == 0.5
        assert LAYER_THRESHOLDS["memory"] == 0.3
        assert LAYER_THRESHOLDS["intelligence"] == 0.3

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
            self._make_result("knowledge", 0.4),  # below 0.5
        ]
        kept, below = apply_threshold_filter(results)
        assert len(kept) == 1
        assert kept[0]["relevance_score"] == 0.6
        assert below == 1

    def test_filters_below_memory_threshold(self) -> None:
        results = [
            self._make_result("memory", 0.35),
            self._make_result("memory", 0.2),  # below 0.3
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
            self._make_result("knowledge", 0.45),  # below default 0.5 but above override 0.4
        ]
        kept, below = apply_threshold_filter(results, threshold_overrides={"knowledge": 0.4})
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
            {"node_id": "n", "layer": "unknown_layer", "relevance_score": 0.25, "content": ""},
        ]
        # 0.25 < 0.3 (memory fallback) -> filtered
        kept, below = apply_threshold_filter(results)
        assert kept == []
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
