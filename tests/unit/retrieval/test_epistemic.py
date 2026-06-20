"""Tests for retrieval/epistemic.py module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from context_service.retrieval.epistemic import (
    EpistemicOptions,
    EpistemicResult,
    RecallHint,
    apply_as_of_filter,
    apply_layer_scoring,
)
from context_service.retrieval.fusion import FusedResult


def _make_result(
    node_id: str = "test-node",
    rrf_score: float = 0.5,
    layer: str = "memory",
    created_at: datetime | None = None,
    confidence: float = 0.8,
    properties: dict | None = None,
) -> FusedResult:
    """Helper to create FusedResult for testing."""
    return FusedResult(
        node_id=node_id,
        rrf_score=rrf_score,
        layer=layer,
        created_at=created_at or datetime.now(UTC),
        confidence=confidence,
        properties=properties or {},
    )


class TestApplyAsOfFilter:
    """Tests for apply_as_of_filter()."""

    def test_filters_nodes_created_after_as_of(self) -> None:
        """Nodes created after as_of should be excluded."""
        now = datetime.now(UTC)
        as_of = now - timedelta(days=1)

        results = [
            _make_result("old", created_at=now - timedelta(days=2)),
            _make_result("new", created_at=now),
        ]

        filtered = apply_as_of_filter(results, as_of)

        assert len(filtered) == 1
        assert filtered[0].node_id == "old"

    def test_filters_superseded_nodes(self) -> None:
        """Nodes with valid_to before as_of should be excluded."""
        now = datetime.now(UTC)
        as_of = now

        results = [
            _make_result(
                "superseded",
                created_at=now - timedelta(days=5),
                properties={"valid_to": (now - timedelta(days=1)).isoformat()},
            ),
            _make_result(
                "current",
                created_at=now - timedelta(days=5),
                properties={},
            ),
        ]

        filtered = apply_as_of_filter(results, as_of)

        assert len(filtered) == 1
        assert filtered[0].node_id == "current"

    def test_keeps_nodes_without_created_at(self) -> None:
        """Nodes without created_at should not be filtered."""
        as_of = datetime.now(UTC)

        results = [FusedResult(node_id="no-date", rrf_score=0.5, created_at=None)]

        filtered = apply_as_of_filter(results, as_of)

        assert len(filtered) == 1


class TestApplyLayerScoring:
    """Tests for apply_layer_scoring()."""

    def test_memory_layer_freshness_decay(self) -> None:
        """Memory layer scores should decay with age."""
        old_date = datetime.now(UTC) - timedelta(days=180)
        recent_date = datetime.now(UTC) - timedelta(hours=1)

        results = [
            _make_result("old-memory", rrf_score=0.8, layer="memory", created_at=old_date),
            _make_result("new-memory", rrf_score=0.8, layer="memory", created_at=recent_date),
        ]

        scored = apply_layer_scoring(results)

        # Recent memory should have higher adjusted score
        old_result = next(r for r in scored if r.node_id == "old-memory")
        new_result = next(r for r in scored if r.node_id == "new-memory")
        assert new_result.rrf_score > old_result.rrf_score

    def test_knowledge_layer_corroboration_boost(self) -> None:
        """Knowledge layer with corroboration should get boosted."""
        results = [
            _make_result(
                "corroborated",
                rrf_score=0.5,
                layer="knowledge",
                properties={"corroboration_count": 5},
            ),
            _make_result(
                "uncorroborated",
                rrf_score=0.5,
                layer="knowledge",
                properties={"corroboration_count": 0},
            ),
        ]

        scored = apply_layer_scoring(results)

        corr = next(r for r in scored if r.node_id == "corroborated")
        uncorr = next(r for r in scored if r.node_id == "uncorroborated")
        assert corr.rrf_score > uncorr.rrf_score

    def test_wisdom_layer_staleness_penalty(self) -> None:
        """Stale wisdom nodes should be penalized."""
        results = [
            _make_result(
                "fresh-belief",
                rrf_score=0.8,
                layer="wisdom",
                properties={"synthesis_state": "FRESH"},
            ),
            _make_result(
                "stale-belief",
                rrf_score=0.8,
                layer="wisdom",
                properties={"synthesis_state": "STALE"},
            ),
        ]

        scored = apply_layer_scoring(results)

        fresh = next(r for r in scored if r.node_id == "fresh-belief")
        stale = next(r for r in scored if r.node_id == "stale-belief")
        assert fresh.rrf_score > stale.rrf_score
        assert stale.rrf_score == pytest.approx(0.4)  # 0.8 * 0.5

    def test_results_sorted_by_adjusted_score(self) -> None:
        """Results should be re-sorted by adjusted rrf_score."""
        results = [
            _make_result("low", rrf_score=0.3, layer="intelligence"),
            _make_result("high", rrf_score=0.9, layer="intelligence"),
            _make_result("mid", rrf_score=0.6, layer="intelligence"),
        ]

        scored = apply_layer_scoring(results)

        assert scored[0].node_id == "high"
        assert scored[1].node_id == "mid"
        assert scored[2].node_id == "low"


class TestEpistemicDataclasses:
    """Tests for epistemic dataclasses."""

    def test_epistemic_options_defaults(self) -> None:
        """EpistemicOptions should have sensible defaults."""
        opts = EpistemicOptions()
        assert opts.as_of is None
        assert opts.include_synthesis is True
        assert opts.include_hints is False
        assert opts.min_confidence == 0.0

    def test_recall_hint_structure(self) -> None:
        """RecallHint should be constructible with all fields."""
        hint = RecallHint(
            hint_type="belief_candidate",
            message="Test hint",
            node_ids=["a", "b"],
            suggested_action="decide(...)",
        )
        assert hint.hint_type == "belief_candidate"
        assert len(hint.node_ids) == 2

    def test_epistemic_result_defaults(self) -> None:
        """EpistemicResult should default to empty hints and no synthesis."""
        result = EpistemicResult(results=[])
        assert result.hints == []
        assert result.synthesis_pending is False
