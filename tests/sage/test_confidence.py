"""Tests for credibility formula."""

import pytest

from context_service.sage.confidence import (
    METHOD_WEIGHTS,
    SOURCE_TIER_WEIGHTS,
    compute_credibility,
)


class TestSourceTierWeights:
    """Tests for source tier weight constants."""

    def test_authoritative_is_highest(self) -> None:
        assert SOURCE_TIER_WEIGHTS["authoritative"] == 1.0

    def test_validated_weight(self) -> None:
        assert SOURCE_TIER_WEIGHTS["validated"] == 0.85

    def test_community_weight(self) -> None:
        assert SOURCE_TIER_WEIGHTS["community"] == 0.6

    def test_unknown_is_lowest(self) -> None:
        assert SOURCE_TIER_WEIGHTS["unknown"] == 0.4


class TestMethodWeights:
    """Tests for method weight constants."""

    def test_direct_is_highest(self) -> None:
        assert METHOD_WEIGHTS["direct"] == 1.0

    def test_validated_extractor_weight(self) -> None:
        assert METHOD_WEIGHTS["validated_extractor"] == 0.85

    def test_standard_extractor_weight(self) -> None:
        assert METHOD_WEIGHTS["standard_extractor"] == 0.75

    def test_experimental_is_lowest(self) -> None:
        assert METHOD_WEIGHTS["experimental"] == 0.6


class TestComputeCredibility:
    """Tests for compute_credibility function."""

    def test_basic_computation(self) -> None:
        breakdown = compute_credibility(
            source_tier="validated",
            method="direct",
            raw_confidence=0.9,
        )
        # 0.85 * 1.0 * 0.9 = 0.765
        assert breakdown.credibility == pytest.approx(0.765)

    def test_returns_breakdown_with_all_factors(self) -> None:
        breakdown = compute_credibility(
            source_tier="authoritative",
            method="standard_extractor",
            raw_confidence=0.8,
        )
        assert breakdown.source_tier == "authoritative"
        assert breakdown.source_tier_weight == 1.0
        assert breakdown.method == "standard_extractor"
        assert breakdown.method_weight == 0.75
        assert breakdown.raw_confidence == 0.8
        # 1.0 * 0.75 * 0.8 = 0.6
        assert breakdown.credibility == pytest.approx(0.6)

    def test_defaults_to_unknown_tier(self) -> None:
        breakdown = compute_credibility(
            source_tier=None,
            method="direct",
            raw_confidence=0.9,
        )
        assert breakdown.source_tier == "unknown"
        assert breakdown.source_tier_weight == 0.4

    def test_defaults_to_direct_method(self) -> None:
        breakdown = compute_credibility(
            source_tier="validated",
            method=None,
            raw_confidence=0.9,
        )
        assert breakdown.method == "direct"
        assert breakdown.method_weight == 1.0

    def test_clamps_raw_confidence_to_valid_range(self) -> None:
        breakdown = compute_credibility(
            source_tier="authoritative",
            method="direct",
            raw_confidence=1.5,  # Over 1.0
        )
        assert breakdown.raw_confidence == 1.0
        assert breakdown.credibility == pytest.approx(1.0)

    def test_clamps_negative_confidence_to_zero(self) -> None:
        breakdown = compute_credibility(
            source_tier="authoritative",
            method="direct",
            raw_confidence=-0.5,
        )
        assert breakdown.raw_confidence == 0.0
        assert breakdown.credibility == pytest.approx(0.0)

    def test_unrecognized_method_defaults_to_direct(self) -> None:
        breakdown = compute_credibility(
            source_tier="validated",
            method="bogus_method",
            raw_confidence=0.9,
        )
        assert breakdown.method == "direct"
        assert breakdown.method_weight == 1.0

    def test_to_dict_returns_serializable(self) -> None:
        breakdown = compute_credibility(
            source_tier="validated",
            method="direct",
            raw_confidence=0.9,
        )
        d = breakdown.to_dict()
        assert isinstance(d, dict)
        assert d["credibility"] == pytest.approx(0.765)
