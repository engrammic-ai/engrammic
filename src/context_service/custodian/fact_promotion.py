"""Adapter: primitives epistemology promotion for :Claim -> :Claim:Fact.

Pure function only — no Memgraph access, no side effects.
Distinct from consensus_promotion.py (Claim:Commitment -> Finding).
"""

from __future__ import annotations

from typing import Any

from primitives.eag.epistemology.confidence import SourceTier
from primitives.eag.epistemology.promotion import (
    ClaimForPromotion,
    PromotionDecision,
    should_promote_r1,
    should_promote_r2,
)


def evaluate_claim_for_fact(
    claim_props: dict[str, Any],
    evidence_count: int,
    corroborations: list[dict[str, Any]] | None = None,
) -> PromotionDecision:
    """Decide whether a :Claim should be promoted to :Claim:Fact.

    Args:
        claim_props: raw Memgraph node properties for the :Claim
        evidence_count: number of evidence items / REFERENCES edges. Zero
            evidence short-circuits to a rejection before calling primitives.
        corroborations: list of OTHER claim_props that support this claim
            (multi-source corroboration). When provided and non-empty,
            R2 (multi-source) is evaluated; otherwise R1 (single-source).

    Returns:
        PromotionDecision from primitives — has at minimum a `should_promote: bool`
        and a `rule` field. See primitives/eag/epistemology/promotion.py for
        exact shape; do not redefine.
    """
    if evidence_count == 0:
        return PromotionDecision(
            should_promote=False,
            rule=None,
            reason="No evidence attached to claim",
        )

    raw_confidence: float = float(claim_props.get("confidence", 0.0))
    source_tier_value: str = str(claim_props.get("source_tier", SourceTier.UNKNOWN))
    try:
        source_tier = SourceTier(source_tier_value)
    except ValueError:
        source_tier = SourceTier.UNKNOWN

    fingerprint: str = str(claim_props.get("fingerprint", claim_props.get("id", "")))

    primary = ClaimForPromotion(
        fingerprint=fingerprint,
        combined_confidence=raw_confidence,
        source_tier=source_tier,
        raw_confidence=raw_confidence,
    )

    if corroborations:
        all_claims: list[ClaimForPromotion] = [primary]
        for c in corroborations:
            c_raw: float = float(c.get("confidence", 0.0))
            c_tier_value: str = str(c.get("source_tier", SourceTier.UNKNOWN))
            try:
                c_tier = SourceTier(c_tier_value)
            except ValueError:
                c_tier = SourceTier.UNKNOWN
            all_claims.append(
                ClaimForPromotion(
                    fingerprint=str(c.get("fingerprint", c.get("id", ""))),
                    combined_confidence=c_raw,
                    source_tier=c_tier,
                    raw_confidence=c_raw,
                )
            )
        return should_promote_r2(all_claims)

    return should_promote_r1(primary)
