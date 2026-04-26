"""Business rule validation for Custodian write path (Stage 3).

Consolidates the business-rule gates that were previously split across
``write_path.py`` (all-claims-rejected skip, quality scoring) into a single
explicit validator. ``promotion.py`` retains the promotion DB writes; the
``min_quality`` threshold is a caller-supplied argument there, not logic
to move here.

This is a pure-Python layer with no DB dependency. It operates on the
surviving claims/edges after the citation validator (Stage 2) has filtered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from context_service.custodian.quality import quality_score
from context_service.custodian.rejection_reasons import BusinessRejection

if TYPE_CHECKING:
    from context_service.custodian.models import Claim, FindingOutput, ProposedEdge


@dataclass
class BusinessRuleResult:
    """Outcome of the business rule gate for a single visit.

    ``accepted=False`` means the visit should be skipped entirely (no DB write).
    When ``accepted=True``, ``computed_quality`` carries the quality score to
    persist on the :Finding node.
    """

    accepted: bool
    rejection_reason: BusinessRejection | None = None
    computed_quality: float = 0.0
    detail: str | None = None


class BusinessRuleValidator:
    """Stage 3 validator: business rule gates on surviving claims and edges.

    Call :meth:`evaluate` after the citation validator has filtered the
    finding down to its surviving claims/edges.

    Checks (in order):
    1. All-claims-rejected skip: if no claims survive and scope != 'silo',
       reject the visit so no :Finding is written.
    2. Quality score: compute the coverage-weighted score; expose it for
       the caller to persist.

    The silo-scope bypass (no claims by design) is preserved: silo-scope
    findings carry a summary but no claims, so the skip guard does not fire.
    """

    def evaluate(
        self,
        finding: FindingOutput,
        surviving_claims: list[Claim],
        surviving_edges: list[ProposedEdge],
        cluster_size: int,
    ) -> BusinessRuleResult:
        """Evaluate business rules against surviving claims and edges.

        Args:
            finding: The original finding (used for scope + summary access).
            surviving_claims: Claims that passed the citation validator.
            surviving_edges: Edges that passed the citation validator.
            cluster_size: Passed through to :func:`quality_score`.

        Returns:
            A :class:`BusinessRuleResult` with ``accepted=True`` and the
            computed quality score, or ``accepted=False`` with a rejection reason.
        """
        if not surviving_claims and finding.scope != "silo":
            return BusinessRuleResult(
                accepted=False,
                rejection_reason=BusinessRejection.ALL_CLAIMS_REJECTED,
                detail="all claims rejected by citation validator; skipping write",
            )

        survivor_finding = finding.model_copy(
            update={
                "claims": surviving_claims,
                "inferred_relations": surviving_edges,
            }
        )
        qscore = quality_score(survivor_finding, cluster_size)

        return BusinessRuleResult(
            accepted=True,
            computed_quality=qscore,
        )


__all__ = [
    "BusinessRuleResult",
    "BusinessRuleValidator",
]
