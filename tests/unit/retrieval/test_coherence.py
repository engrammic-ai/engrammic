"""Tests for coherence filtering."""

from context_service.retrieval.coherence import (
    _dominates,
    _get_layer_rank,
    filter_dominated_contradictions,
)


class TestLayerRank:
    def test_wisdom_highest(self):
        assert _get_layer_rank("wisdom") == 4

    def test_knowledge_middle(self):
        assert _get_layer_rank("knowledge") == 3

    def test_memory_low(self):
        assert _get_layer_rank("memory") == 2

    def test_intelligence_lowest(self):
        assert _get_layer_rank("intelligence") == 1

    def test_unknown_layer(self):
        assert _get_layer_rank("unknown") == 0

    def test_none_layer(self):
        assert _get_layer_rank(None) == 0

    def test_case_insensitive(self):
        assert _get_layer_rank("WISDOM") == 4
        assert _get_layer_rank("Knowledge") == 3


class TestDominates:
    def test_higher_layer_dominates(self):
        wisdom = {"layer": "wisdom", "confidence": 0.5}
        knowledge = {"layer": "knowledge", "confidence": 0.9}
        assert _dominates(wisdom, knowledge) is True
        assert _dominates(knowledge, wisdom) is False

    def test_same_layer_higher_confidence_dominates(self):
        high = {"layer": "knowledge", "confidence": 0.9}
        low = {"layer": "knowledge", "confidence": 0.5}
        assert _dominates(high, low) is True
        assert _dominates(low, high) is False

    def test_same_layer_same_confidence_recent_wins(self):
        old = {"layer": "knowledge", "confidence": 0.8, "created_at": "2026-01-01T00:00:00Z"}
        new = {"layer": "knowledge", "confidence": 0.8, "created_at": "2026-06-01T00:00:00Z"}
        assert _dominates(new, old) is True
        assert _dominates(old, new) is False

    def test_tie_neither_dominates(self):
        a = {"layer": "knowledge", "confidence": 0.8}
        b = {"layer": "knowledge", "confidence": 0.8}
        assert _dominates(a, b) is False
        assert _dominates(b, a) is False


class TestFilterDominatedContradictions:
    def test_empty_results(self):
        filtered, count = filter_dominated_contradictions([])
        assert filtered == []
        assert count == 0

    def test_no_contradictions(self):
        results = [
            {"node_id": "a", "layer": "knowledge", "confidence": 0.8, "contradicts": []},
            {"node_id": "b", "layer": "memory", "confidence": 0.6, "contradicts": []},
        ]
        filtered, count = filter_dominated_contradictions(results)
        assert len(filtered) == 2
        assert count == 0

    def test_contradiction_not_in_results(self):
        results = [
            {"node_id": "a", "layer": "knowledge", "confidence": 0.8, "contradicts": ["x"]},
        ]
        filtered, count = filter_dominated_contradictions(results)
        assert len(filtered) == 1
        assert count == 0

    def test_filter_dominated_by_layer(self):
        results = [
            {"node_id": "a", "layer": "wisdom", "confidence": 0.5, "contradicts": ["b"]},
            {"node_id": "b", "layer": "knowledge", "confidence": 0.9, "contradicts": ["a"]},
        ]
        filtered, count = filter_dominated_contradictions(results)
        assert len(filtered) == 1
        assert filtered[0]["node_id"] == "a"
        assert count == 1

    def test_filter_dominated_by_confidence(self):
        results = [
            {"node_id": "a", "layer": "knowledge", "confidence": 0.9, "contradicts": ["b"]},
            {"node_id": "b", "layer": "knowledge", "confidence": 0.5, "contradicts": ["a"]},
        ]
        filtered, count = filter_dominated_contradictions(results)
        assert len(filtered) == 1
        assert filtered[0]["node_id"] == "a"
        assert count == 1

    def test_bidirectional_contradiction(self):
        results = [
            {"node_id": "a", "layer": "wisdom", "confidence": 0.8, "contradicts": ["b"]},
            {"node_id": "b", "layer": "memory", "confidence": 0.9, "contradicts": ["a"]},
        ]
        filtered, count = filter_dominated_contradictions(results)
        assert len(filtered) == 1
        assert filtered[0]["node_id"] == "a"
        assert count == 1

    def test_unidirectional_contradiction(self):
        results = [
            {"node_id": "a", "layer": "wisdom", "confidence": 0.8, "contradicts": ["b"]},
            {"node_id": "b", "layer": "memory", "confidence": 0.9, "contradicts": []},
        ]
        filtered, count = filter_dominated_contradictions(results)
        assert len(filtered) == 1
        assert filtered[0]["node_id"] == "a"
        assert count == 1

    def test_chain_of_contradictions(self):
        # A (wisdom) contradicts B (knowledge), B contradicts C (memory)
        # A dominates B, so B is filtered out.
        # C stays because B (which would dominate it) was already filtered.
        results = [
            {"node_id": "a", "layer": "wisdom", "confidence": 0.9, "contradicts": ["b"]},
            {"node_id": "b", "layer": "knowledge", "confidence": 0.8, "contradicts": ["c"]},
            {"node_id": "c", "layer": "memory", "confidence": 0.7, "contradicts": []},
        ]
        filtered, count = filter_dominated_contradictions(results)
        assert len(filtered) == 2
        node_ids = {r["node_id"] for r in filtered}
        assert "a" in node_ids
        assert "c" in node_ids
        assert "b" not in node_ids
        assert count == 1

    def test_tie_keeps_both(self):
        results = [
            {"node_id": "a", "layer": "knowledge", "confidence": 0.8, "contradicts": ["b"]},
            {"node_id": "b", "layer": "knowledge", "confidence": 0.8, "contradicts": ["a"]},
        ]
        filtered, count = filter_dominated_contradictions(results)
        assert len(filtered) == 2
        assert count == 0

    def test_preserves_order(self):
        results = [
            {"node_id": "x", "layer": "memory", "confidence": 0.5, "contradicts": []},
            {"node_id": "a", "layer": "wisdom", "confidence": 0.9, "contradicts": ["b"]},
            {"node_id": "y", "layer": "memory", "confidence": 0.6, "contradicts": []},
            {"node_id": "b", "layer": "knowledge", "confidence": 0.8, "contradicts": ["a"]},
            {"node_id": "z", "layer": "memory", "confidence": 0.7, "contradicts": []},
        ]
        filtered, count = filter_dominated_contradictions(results)
        assert len(filtered) == 4
        assert [r["node_id"] for r in filtered] == ["x", "a", "y", "z"]
        assert count == 1
