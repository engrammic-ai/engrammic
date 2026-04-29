"""Unit tests for custodian/fact_promotion.py — no DB required."""

from __future__ import annotations

from primitives.eag.epistemology.promotion import PromotionRule

from context_service.custodian.fact_promotion import evaluate_claim_for_fact


def _authoritative_claim(confidence: float = 0.85, claim_id: str = "claim-1") -> dict:
    return {
        "id": claim_id,
        "confidence": confidence,
        "source_tier": "authoritative",
    }


def _community_claim(confidence: float = 0.5, claim_id: str = "claim-x") -> dict:
    return {
        "id": claim_id,
        "confidence": confidence,
        "source_tier": "community",
    }


def test_r1_path_promotes() -> None:
    decision = evaluate_claim_for_fact(_authoritative_claim(0.85), evidence_count=1)
    assert decision.should_promote is True
    assert decision.rule == PromotionRule.R1


def test_r2_path_promotes() -> None:
    primary = _authoritative_claim(0.85, "claim-a")
    corroboration = _authoritative_claim(0.80, "claim-b")
    decision = evaluate_claim_for_fact(primary, evidence_count=2, corroborations=[corroboration])
    assert decision.should_promote is True
    assert decision.rule == PromotionRule.R2


def test_low_evidence_rejects() -> None:
    # Zero evidence short-circuits before epistemology
    decision = evaluate_claim_for_fact(_authoritative_claim(0.9), evidence_count=0)
    assert decision.should_promote is False
    assert decision.rule is None


def test_low_confidence_r1_rejects() -> None:
    # R1 requires raw_confidence >= 0.7
    decision = evaluate_claim_for_fact(_authoritative_claim(0.5), evidence_count=1)
    assert decision.should_promote is False


def test_non_authoritative_r1_rejects() -> None:
    # R1 requires authoritative source_tier
    decision = evaluate_claim_for_fact(_community_claim(0.9), evidence_count=1)
    assert decision.should_promote is False


def test_already_fact_shape_handled() -> None:
    # evaluate_claim_for_fact is pure and doesn't check :Fact label — it just
    # evaluates whatever props are passed. Passing props that look like an already-
    # promoted claim still works correctly.
    props = _authoritative_claim(0.85)
    props["promoted_at"] = "2026-04-28T00:00:00Z"
    props["promotion_rule"] = "R1"
    decision = evaluate_claim_for_fact(props, evidence_count=1)
    assert decision.should_promote is True


def test_unknown_source_tier_falls_back() -> None:
    props = {"id": "claim-z", "confidence": 0.9, "source_tier": "bogus"}
    decision = evaluate_claim_for_fact(props, evidence_count=1)
    # unknown tier -> treated as UNKNOWN, R1 rejects it
    assert decision.should_promote is False


def test_claim_to_fact_promotion_depends_on_custodian_visit() -> None:
    """claim_to_fact_promotion must declare custodian_visit as a dependency."""
    from context_service.pipelines.assets.fact_promotion import claim_to_fact_promotion

    assert any(
        "custodian_visit" in str(v)
        for v in claim_to_fact_promotion.keys_by_input_name.values()  # type: ignore[attr-defined]
    ), "claim_to_fact_promotion must depend on custodian_visit"
