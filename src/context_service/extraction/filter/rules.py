from __future__ import annotations

from typing import TYPE_CHECKING

from context_service.extraction.filter.models import FilterDecision, FilterRuleSet, RuleFired

if TYPE_CHECKING:
    from context_service.extraction.models import ClaimTriple


def _canon(claim: ClaimTriple) -> tuple[str, str, str]:
    return (
        claim.predicate.strip(),
        str(claim.subject).strip().lower(),
        str(claim.object).strip().lower(),
    )


def rule_1_hard_drop(claim: ClaimTriple, rs: FilterRuleSet) -> FilterDecision | None:
    """Return DROP if (predicate, subject_lower, object_lower) is in the hard-drop set."""
    if _canon(claim) in rs.hard_drop_triples:
        return FilterDecision.drop(
            rule=RuleFired.HARD_DROP,
            reason=f"hard_drop:{claim.predicate}",
        )
    return None


def rule_3_heuristic(claim: ClaimTriple, rs: FilterRuleSet) -> FilterDecision | None:
    """Return a decision, or None if the rule is not decisive."""
    p, s, o = _canon(claim)

    if p in rs.never_filter_predicates:
        return None  # pass through to Rule 4

    if p not in rs.suspect_predicates:
        return FilterDecision.keep(rule=RuleFired.HEURISTIC, reason="not_suspect_predicate")

    if s in rs.public_entity_allowlist and o in rs.public_entity_allowlist:
        return FilterDecision.drop(
            rule=RuleFired.HEURISTIC,
            reason="both_public_suspect_predicate",
        )

    return None  # fall through to Rule 4
