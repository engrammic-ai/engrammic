"""Quality score helper for :Finding nodes (coverage-biased, used by Task 16 evaluation).

The v1 formula is a weighted sum of five signals, biased toward **coverage**
(0.30) as the strongest defense against agents that claim-stuff with weak
citations. See ``context/plans/2026-04-05-custodian-phase.md`` Task 2 for the
full rationale; the formula here matches the plan exactly.

Pure function, no I/O. For silo-scope findings the caller passes
``cluster_size = total_nodes_in_silo``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_service.custodian.models import FindingOutput


def quality_score(finding: FindingOutput, cluster_size: int) -> float:
    """Compute the v1 coverage-weighted quality score for a finding.

    Output is clamped to ``[0, 1]``. Zero-division is avoided by clamping
    every denominator with ``max(x, 1)``.
    """
    claims = finding.claims
    claim_count = len(claims)
    if claim_count == 0:
        return 0.0

    distinct_cited = len({c.node_id for cl in claims for c in cl.citations})
    primary_ratio = sum(1 for cl in claims if any(c.kind == "primary" for c in cl.citations)) / max(
        claim_count, 1
    )
    rel_count = len(finding.inferred_relations)
    sentence_count = len(finding.summary.summary) if finding.summary else 0

    density = min(claim_count / 5.0, 1.0)
    coverage = min(distinct_cited / max(cluster_size, 1), 1.0)
    relational = min(rel_count / 2.0, 1.0)
    summary_density = min(
        claim_count / max(sentence_count, 1) / 2.0,
        1.0,
    )

    score = (
        density * 0.25
        + coverage * 0.30
        + relational * 0.15
        + primary_ratio * 0.20
        + summary_density * 0.10
    )
    return max(0.0, min(score, 1.0))
