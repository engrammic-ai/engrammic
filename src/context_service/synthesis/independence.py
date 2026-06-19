"""Independence scorer for CITE v2 synthesis corroboration.

Two facts corroborate a belief more strongly when they are independent of each other.
Independence is assessed along four dimensions: document source, authoring agent,
temporal gap, and source tier. The score is used by the synthesizer to gate
ProposedBelief creation via check_synthesis_threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import combinations


@dataclass
class FactMetadata:
    """Metadata required to assess independence between two corroborating facts.

    Fields are optional to accommodate partial provenance: a fact ingested from
    an external pipeline may lack agent_id, while a synthetic fact may lack
    document_id. Missing fields reduce the independence score conservatively
    (i.e., they do not contribute positive increments).
    """

    fact_id: str
    document_id: str | None
    agent_id: str | None
    created_at: datetime | None
    source_tier: str | None  # e.g. "authoritative", "validated", "community"


_TEMPORAL_GAP_HOURS = 24.0

_BASE_SCORE = 0.2
_DIFFERENT_DOCUMENT_BONUS = 0.3
_DIFFERENT_AGENT_BONUS = 0.3
_TEMPORAL_GAP_BONUS = 0.2
_DIFFERENT_TIER_BONUS = 0.2
_MAX_SCORE = 1.0


def calculate_independence(fact_a: FactMetadata, fact_b: FactMetadata) -> float:
    """Calculate the independence score between two facts.

    A higher score indicates that the two facts are unlikely to share a common
    failure mode, making their joint corroboration of a claim more valuable.

    Scoring breakdown:
        Base                       0.2  (always awarded)
        Different document         +0.3 (both non-None and differ)
        Different agent            +0.3 (both non-None and differ)
        Temporal gap > 24h         +0.2 (both non-None and gap exceeds threshold)
        Different source tier      +0.2 (both non-None and differ)
        Maximum                    1.0

    When a field is None on either fact it is treated as unknown and does not
    contribute a bonus. This is intentionally conservative: unknown provenance
    should not inflate the independence score.

    Args:
        fact_a: Metadata for the first fact.
        fact_b: Metadata for the second fact.

    Returns:
        Independence score in [0.2, 1.0].
    """
    score = _BASE_SCORE

    if (
        fact_a.document_id is not None
        and fact_b.document_id is not None
        and fact_a.document_id != fact_b.document_id
    ):
        score += _DIFFERENT_DOCUMENT_BONUS

    if (
        fact_a.agent_id is not None
        and fact_b.agent_id is not None
        and fact_a.agent_id != fact_b.agent_id
    ):
        score += _DIFFERENT_AGENT_BONUS

    if fact_a.created_at is not None and fact_b.created_at is not None:
        gap_hours = abs((fact_a.created_at - fact_b.created_at).total_seconds()) / 3600.0
        if gap_hours > _TEMPORAL_GAP_HOURS:
            score += _TEMPORAL_GAP_BONUS

    if (
        fact_a.source_tier is not None
        and fact_b.source_tier is not None
        and fact_a.source_tier != fact_b.source_tier
    ):
        score += _DIFFERENT_TIER_BONUS

    return min(score, _MAX_SCORE)


def check_synthesis_threshold(
    facts: list[FactMetadata],
    threshold: float = 2.0,
) -> bool:
    """Decide whether a set of facts clears the independence threshold for synthesis.

    Sums pairwise independence scores across all unique pairs in `facts` and
    returns True when the total meets or exceeds `threshold`. The default
    threshold of 2.0 requires roughly two fully-independent fact pairs, which
    guards against synthesizing beliefs from a single corroborating source
    observed twice.

    With N facts there are N*(N-1)/2 pairs. A set of 2 facts produces one pair;
    the maximum score for that pair is 1.0, so the default threshold of 2.0
    requires at least 3 facts unless the pair is highly independent and the
    caller lowers the threshold.

    Args:
        facts: Facts being evaluated for synthesis. Fewer than 2 facts always
               returns False (no pairs to evaluate).
        threshold: Minimum sum of pairwise independence scores required.
                   Must be positive. Defaults to 2.0.

    Returns:
        True if sum of pairwise scores >= threshold, False otherwise.
    """
    if len(facts) < 2:
        return False

    total = sum(
        calculate_independence(a, b)
        for a, b in combinations(facts, 2)
    )
    return total >= threshold
