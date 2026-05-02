"""Validation pipeline for Custodian write path."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_service.custodian.business_rules import BusinessRuleResult, BusinessRuleValidator
    from context_service.custodian.models import Claim, FindingOutput, ProposedEdge
    from context_service.custodian.validators import CitationValidator


@dataclass
class CitationStageResult:
    """Outcome of the citation validation stage."""

    passed: bool
    surviving_claims: list[Claim] = field(default_factory=list)
    surviving_edges: list[ProposedEdge] = field(default_factory=list)
    claims_rejected: int = 0
    edges_rejected: int = 0


@dataclass
class PipelineResult:
    """Structured outcome of the full validation pipeline.

    ``failed_at`` is ``None`` on success, ``"business"`` on failure.
    ``citation`` is always populated after the citation stage runs.
    ``business`` is ``None`` when the citation stage short-circuited.
    """

    passed: bool
    failed_at: str | None = None
    citation: CitationStageResult | None = None
    business: BusinessRuleResult | None = None


async def run_validation(
    finding: FindingOutput,
    seen_node_ids: set[str],
    citation_validator: CitationValidator,
    business_validator: BusinessRuleValidator,
    cluster_size: int,
) -> PipelineResult:
    """Run citation then business rule validation, returning a structured PipelineResult."""
    claim_results, edge_results = await citation_validator.validate_finding(finding, seen_node_ids)

    surviving_claims: list[Claim] = []
    claims_rejected = 0
    for claim, result in zip(finding.claims, claim_results, strict=True):
        if result.accepted:
            surviving_claims.append(claim)
        else:
            claims_rejected += 1

    surviving_edges: list[ProposedEdge] = []
    edges_rejected = 0
    for edge, edge_result in zip(finding.inferred_relations, edge_results, strict=True):
        if edge_result.accepted:
            surviving_edges.append(edge)
        else:
            edges_rejected += 1

    citation_stage = CitationStageResult(
        passed=True,
        surviving_claims=surviving_claims,
        surviving_edges=surviving_edges,
        claims_rejected=claims_rejected,
        edges_rejected=edges_rejected,
    )

    biz = business_validator.evaluate(finding, surviving_claims, surviving_edges, cluster_size)
    if not biz.accepted:
        return PipelineResult(
            passed=False, failed_at="business", citation=citation_stage, business=biz
        )

    return PipelineResult(passed=True, citation=citation_stage, business=biz)
