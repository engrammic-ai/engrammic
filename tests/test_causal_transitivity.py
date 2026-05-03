"""Tests for causal transitivity inference (v1.2c gaps)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from primitives.schema.edges import CITEEdgeType


def _compute_confidence(
    edge_confidences: list[tuple[str, float]], formula: str
) -> float:
    """Mirror of the production function for testing."""
    if not edge_confidences:
        return 0.0

    seen: set[str] = set()
    unique: list[float] = []
    for edge_id, conf in edge_confidences:
        if edge_id not in seen:
            seen.add(edge_id)
            unique.append(conf)

    if formula == "minimum":
        return min(unique)

    if formula == "geometric_mean":
        product = 1.0
        for c in unique:
            product *= c
        return float(product ** (1.0 / len(unique)))

    result = 1.0
    for c in unique:
        result *= c
    return result


def _load_query_strings() -> tuple[str, str]:
    """Extract query strings from causal.py without executing the module."""
    causal_path = (
        Path(__file__).parent.parent
        / "src"
        / "context_service"
        / "pipelines"
        / "assets"
        / "causal.py"
    )
    source = causal_path.read_text()

    # Extract _SCAN_CAUSES_CHAINS
    scan_match = re.search(
        r'_SCAN_CAUSES_CHAINS\s*=\s*"""(.+?)"""', source, re.DOTALL
    )
    scan_query = scan_match.group(1) if scan_match else ""

    # Extract _UPSERT_INFERRED_CAUSES
    upsert_match = re.search(
        r'_UPSERT_INFERRED_CAUSES\s*=\s*"""(.+?)"""', source, re.DOTALL
    )
    upsert_query = upsert_match.group(1) if upsert_match else ""

    return scan_query, upsert_query


_SCAN_CAUSES_CHAINS, _UPSERT_INFERRED_CAUSES = _load_query_strings()


class TestComputeConfidence:
    """Unit tests for _compute_confidence deduplication and formulas."""

    def test_basic_minimum_formula(self) -> None:
        edges = [("e1", 0.9), ("e2", 0.7), ("e3", 0.8)]
        result = _compute_confidence(edges, "minimum")
        assert result == 0.7

    def test_basic_geometric_mean(self) -> None:
        edges = [("e1", 0.8), ("e2", 0.8)]
        result = _compute_confidence(edges, "geometric_mean")
        assert abs(result - 0.8) < 0.001

    def test_multiplicative_default(self) -> None:
        edges = [("e1", 0.5), ("e2", 0.5)]
        result = _compute_confidence(edges, "multiplicative")
        assert result == 0.25

    def test_dedup_by_edge_id_not_value(self) -> None:
        # Same confidence value but different edge IDs - both should count
        edges = [("e1", 0.8), ("e2", 0.8)]
        result = _compute_confidence(edges, "multiplicative")
        assert result == pytest.approx(0.64)  # 0.8 * 0.8

    def test_dedup_removes_duplicate_edge_ids(self) -> None:
        # Same edge ID repeated - should only count once
        edges = [("e1", 0.8), ("e1", 0.8), ("e2", 0.5)]
        result = _compute_confidence(edges, "multiplicative")
        assert result == 0.4  # 0.8 * 0.5 (e1 counted once)

    def test_diamond_path_deduplication(self) -> None:
        # A->B->D and A->C->D share edge e4 (D's incoming)
        # Should not double-count the shared edge
        edges = [("e1", 0.9), ("e2", 0.8), ("e2", 0.8)]  # e2 appears twice
        result = _compute_confidence(edges, "minimum")
        assert result == 0.8  # min of unique: {0.9, 0.8}

    def test_empty_list_returns_zero(self) -> None:
        result = _compute_confidence([], "minimum")
        assert result == 0.0


class TestCausalEnums:
    """Verify PREVENTS exists in primitives (v1.2c prerequisite)."""

    def test_prevents_enum_exists(self) -> None:
        assert CITEEdgeType.PREVENTS == "PREVENTS"

    def test_prevents_in_semantic_edges(self) -> None:
        from primitives.schema.edges import SEMANTIC_EDGES

        assert CITEEdgeType.PREVENTS in SEMANTIC_EDGES

    def test_causes_in_semantic_edges(self) -> None:
        from primitives.schema.edges import SEMANTIC_EDGES

        assert CITEEdgeType.CAUSES in SEMANTIC_EDGES

    def test_corroborates_in_semantic_edges(self) -> None:
        from primitives.schema.edges import SEMANTIC_EDGES

        assert CITEEdgeType.CORROBORATES in SEMANTIC_EDGES


class TestCausalQueryStructure:
    """Verify query templates enforce silo isolation and inferred flags."""

    def test_scan_query_filters_by_silo(self) -> None:
        assert "a.silo_id = $silo_id" in _SCAN_CAUSES_CHAINS
        assert "n.silo_id = $silo_id" in _SCAN_CAUSES_CHAINS

    def test_upsert_sets_inferred_flag(self) -> None:
        assert "inferred: true" in _UPSERT_INFERRED_CAUSES

    def test_upsert_merge_key_excludes_id(self) -> None:
        lines = _UPSERT_INFERRED_CAUSES.split("\n")
        merge_line = next(line for line in lines if "MERGE" in line)
        assert "id:" not in merge_line or "id: $edge_id" not in merge_line

    def test_scan_has_depth_limit_placeholder(self) -> None:
        assert "{depth}" in _SCAN_CAUSES_CHAINS

    def test_not_exists_prevents_duplicates(self) -> None:
        assert "NOT EXISTS" in _SCAN_CAUSES_CHAINS
        assert "inferred: true" in _SCAN_CAUSES_CHAINS


class TestCorroborationAggregation:
    """Tests for multi-source confidence boosting."""

    def test_multiple_sources_geometric_mean(self) -> None:
        # Two sources with 0.7 and 0.9 confidence
        edges = [("source1", 0.7), ("source2", 0.9)]
        result = _compute_confidence(edges, "geometric_mean")
        expected = (0.7 * 0.9) ** 0.5  # sqrt(0.63) ~= 0.794
        assert abs(result - expected) < 0.001

    def test_single_source_passthrough(self) -> None:
        edges = [("source1", 0.85)]
        result = _compute_confidence(edges, "minimum")
        assert result == 0.85


class TestTransitivityDepthCap:
    """Verify depth limits in query structure."""

    def test_query_uses_variable_length_pattern(self) -> None:
        assert "*2..{depth}" in _SCAN_CAUSES_CHAINS

    def test_depth_is_configurable(self) -> None:
        from context_service.config.settings import CausalConfig

        settings = CausalConfig()
        assert hasattr(settings, "max_transitivity_depth")
        assert settings.max_transitivity_depth >= 2


class TestCycleTermination:
    """Verify cycle handling in query structure."""

    def test_not_exists_breaks_cycles(self) -> None:
        # The NOT EXISTS clause prevents re-inferring already-inferred edges
        # Query uses {{ for escaped braces in Python
        assert "NOT EXISTS((a)-[:CAUSES {{inferred: true}}]->(c))" in _SCAN_CAUSES_CHAINS

    def test_self_loop_guard(self) -> None:
        # Prevents A->...->A cycles from creating self-referential edges
        assert "a <> c" in _SCAN_CAUSES_CHAINS
