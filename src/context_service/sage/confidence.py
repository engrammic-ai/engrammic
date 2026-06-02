"""Credibility formula and tier weights.

Computes static credibility score at write time with full breakdown for transparency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SOURCE_TIER_WEIGHTS: dict[str, float] = {
    "authoritative": 1.0,  # Primary source: official docs, verified API response
    "validated": 0.85,  # Cross-checked against independent source
    "community": 0.6,  # Unverified but from known-good agent/source
    "unknown": 0.4,  # No provenance info
}

METHOD_WEIGHTS: dict[str, float] = {
    "direct": 1.0,  # Agent directly observed/verified
    "validated_extractor": 0.85,  # Extraction pipeline with validation
    "standard_extractor": 0.75,  # Standard extraction, no validation
    "experimental": 0.6,  # New/untested extraction method
}


@dataclass
class CredibilityBreakdown:
    """Full breakdown of credibility computation for transparency."""

    source_tier: str
    source_tier_weight: float
    method: str
    method_weight: float
    raw_confidence: float
    credibility: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_tier": self.source_tier,
            "source_tier_weight": self.source_tier_weight,
            "method": self.method,
            "method_weight": self.method_weight,
            "raw_confidence": self.raw_confidence,
            "credibility": self.credibility,
        }


def compute_credibility(
    source_tier: str | None,
    method: str | None,
    raw_confidence: float,
) -> CredibilityBreakdown:
    """Compute static credibility score with full breakdown.

    Formula: credibility = source_tier_weight * method_weight * raw_confidence

    Args:
        source_tier: Source quality tier (authoritative, validated, community, unknown).
        method: Extraction method (direct, validated_extractor, standard_extractor, experimental).
        raw_confidence: Raw confidence score from source (0.0-1.0).

    Returns:
        CredibilityBreakdown with all factors and final score.
    """
    tier = source_tier if source_tier in SOURCE_TIER_WEIGHTS else "unknown"
    tier_weight = SOURCE_TIER_WEIGHTS[tier]

    meth = method if method in METHOD_WEIGHTS else "direct"
    meth_weight = METHOD_WEIGHTS[meth]

    clamped_confidence = max(0.0, min(1.0, raw_confidence))

    credibility = tier_weight * meth_weight * clamped_confidence

    return CredibilityBreakdown(
        source_tier=tier,
        source_tier_weight=tier_weight,
        method=meth,
        method_weight=meth_weight,
        raw_confidence=clamped_confidence,
        credibility=credibility,
    )
