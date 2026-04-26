"""Server-side citation validation for Custodian commits.

Every node_id an agent cites via commit_claim or commit_inferred_relation is
checked against:

1. Existence -- node present in Memgraph.
2. Tenant/silo membership -- node belongs to the calling visit's (tenant_id, silo_id).
3. Tool-returned set -- node_id must be in ctx.deps.seen_node_ids for the current visit.

Rejections are soft: the offending claim/edge is dropped, a rejection metric is
incremented, and the visit continues. Never raise to the caller on rejection --
this is a filter, not a gate.

Node label choice: content nodes live under ``:Document``, ``:Passage``, or
``:Claim`` labels (phase-3 split). The lookup query uses
``content_union_predicate`` to match any of the three.
``:Cluster``/``:Entity``/``:Silo`` labels exist for different purposes and are
not citeable targets.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from context_service.custodian.rejection_reasons import (
    CitationRejection,
    StructuralRejection,
)
from context_service.db.schema import content_union_predicate

if TYPE_CHECKING:
    from context_service.custodian.models import Claim, FindingOutput, ProposedEdge
    from context_service.stores.memgraph import MemgraphClient


# ---------------------------------------------------------------------------
# Rejection reasons -- use layer-split enums from rejection_reasons.py
# ---------------------------------------------------------------------------

# CitationRejectionReason is kept as a backward-compatible alias so existing
# call sites (metrics, tests) that reference it by name continue to work.
CitationRejectionReason = CitationRejection


# ---------------------------------------------------------------------------
# Metrics protocol -- decoupled from the concrete backend (Task 14)
# ---------------------------------------------------------------------------


@runtime_checkable
class RejectionMetrics(Protocol):
    """Minimal protocol the validator needs to increment rejection counters.

    Task 14 will provide the concrete implementation backed by Prometheus /
    OpenTelemetry. Keeping this a Protocol avoids pulling a metrics backend
    into ``validators.py`` -- unit tests can pass a ``unittest.mock.Mock``.
    """

    def increment_claim_rejection(
        self, reason: CitationRejection | StructuralRejection, count: int = 1
    ) -> None: ...


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    """Outcome of validating a single claim or proposed edge.

    ``detail`` is for logs/metrics -- never user-facing.
    """

    accepted: bool
    rejection_reason: CitationRejection | StructuralRejection | None = None
    offending_node_ids: list[str] = Field(default_factory=list)
    detail: str | None = None


class ClaimValidationResult(ValidationResult):
    pass


class EdgeValidationResult(ValidationResult):
    pass


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


# phase-3.6 note: no committed filter — validator must check in-flight nodes too
_LOOKUP_QUERY = (
    f"MATCH (n) WHERE {content_union_predicate('n')} AND n.id IN $node_ids"
    " RETURN n.id AS id, n.silo_id AS silo_id"
)


class CitationValidator:
    """Filters claims and proposed edges against the citation rules."""

    def __init__(
        self,
        memgraph_client: MemgraphClient,
        metrics: RejectionMetrics | None = None,
    ) -> None:
        self._client = memgraph_client
        self._metrics = metrics

    async def validate_claim(
        self,
        claim: Claim,
        silo_id: str,
        seen_node_ids: set[str],
    ) -> ClaimValidationResult:
        """Validate every citation on ``claim``.

        Runs the tool-returned-set check first (cheapest), then a single
        batched Cypher query for existence + silo membership across
        all remaining citations. First failing check wins the
        ``rejection_reason`` field; ``offending_node_ids`` lists every
        citation that failed any check.
        """
        citation_ids = [c.node_id for c in claim.citations]
        survivors = [nid for nid in citation_ids if nid in seen_node_ids]
        lookup_map = await self._lookup_nodes(survivors)
        return self._evaluate_claim_ids(citation_ids, silo_id, seen_node_ids, lookup_map)

    async def validate_proposed_edge(
        self,
        edge: ProposedEdge,
        silo_id: str,
        seen_node_ids: set[str],
    ) -> EdgeValidationResult:
        """Validate both endpoints and every supporting citation on ``edge``.

        Also defensively re-runs the schema + confidence checks that
        ``ProposedEdge.validate_all`` already enforces at construction. If
        the edge was built via a path that skipped model validation, those
        checks fire here with ``schema_violation`` / ``low_confidence``.
        """
        pre = self._pre_check_edge(edge)
        if pre is not None:
            self._record(pre.rejection_reason)  # type: ignore[arg-type]
            return pre

        all_ids = self._edge_node_ids(edge)
        survivors = [nid for nid in all_ids if nid in seen_node_ids]
        lookup_map = await self._lookup_nodes(survivors)
        return self._evaluate_edge_ids(all_ids, silo_id, seen_node_ids, lookup_map)

    async def validate_finding(
        self,
        finding: FindingOutput,
        seen_node_ids: set[str],
    ) -> tuple[list[ClaimValidationResult], list[EdgeValidationResult]]:
        """Validate every claim and every proposed edge on ``finding`` with a
        single Memgraph round-trip.

        Strategy: run pure-Python pre-checks on each edge (confidence, schema)
        first to exclude their ids from the lookup set; collect the union of
        every citation id on every claim plus every endpoint/supporting id on
        every surviving edge; filter to the ids present in ``seen_node_ids``
        (the rest can't reach the DB-backed checks anyway); issue
        ``_LOOKUP_QUERY`` exactly once; then evaluate each claim and edge in
        pure Python against the resulting ``{node_id: row}`` map.

        Returns two lists aligned with ``finding.claims`` and
        ``finding.inferred_relations`` in input order.
        """
        silo_id = finding.silo_id

        edge_pre: list[EdgeValidationResult | None] = [
            self._pre_check_edge(edge) for edge in finding.inferred_relations
        ]

        survivor_ids: set[str] = set()
        for claim in finding.claims:
            for c in claim.citations:
                if c.node_id in seen_node_ids:
                    survivor_ids.add(c.node_id)
        for edge, pre in zip(finding.inferred_relations, edge_pre, strict=True):
            if pre is not None:
                continue
            for nid in self._edge_node_ids(edge):
                if nid in seen_node_ids:
                    survivor_ids.add(nid)

        lookup_map = await self._lookup_nodes(sorted(survivor_ids))

        claim_results: list[ClaimValidationResult] = []
        for claim in finding.claims:
            citation_ids = [c.node_id for c in claim.citations]
            claim_results.append(
                self._evaluate_claim_ids(citation_ids, silo_id, seen_node_ids, lookup_map)
            )

        edge_results: list[EdgeValidationResult] = []
        for edge, pre in zip(finding.inferred_relations, edge_pre, strict=True):
            if pre is not None:
                self._record(pre.rejection_reason)  # type: ignore[arg-type]
                edge_results.append(pre)
                continue
            all_ids = self._edge_node_ids(edge)
            edge_results.append(
                self._evaluate_edge_ids(all_ids, silo_id, seen_node_ids, lookup_map)
            )

        return claim_results, edge_results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _lookup_nodes(self, node_ids: list[str]) -> dict[str, dict[str, str]]:
        """Issue the batched content-node lookup for ``node_ids`` (if any).

        Returns ``{node_id: {"silo_id": ...}}``. When
        ``node_ids`` is empty, skips the query and returns an empty map.
        """
        if not node_ids:
            return {}
        rows = await self._client.execute_query(_LOOKUP_QUERY, {"node_ids": node_ids})
        return {row["id"]: {"silo_id": row["silo_id"]} for row in rows}

    def _evaluate_claim_ids(
        self,
        citation_ids: list[str],
        silo_id: str,
        seen_node_ids: set[str],
        lookup_map: dict[str, dict[str, str]],
    ) -> ClaimValidationResult:
        first_reason, offenders, detail = self._check_node_ids_sync(
            citation_ids, silo_id, seen_node_ids, lookup_map
        )
        if first_reason is None:
            return ClaimValidationResult(accepted=True)
        self._record(first_reason)
        return ClaimValidationResult(
            accepted=False,
            rejection_reason=first_reason,
            offending_node_ids=offenders,
            detail=detail,
        )

    def _evaluate_edge_ids(
        self,
        all_ids: list[str],
        silo_id: str,
        seen_node_ids: set[str],
        lookup_map: dict[str, dict[str, str]],
    ) -> EdgeValidationResult:
        first_reason, offenders, detail = self._check_node_ids_sync(
            all_ids, silo_id, seen_node_ids, lookup_map
        )
        if first_reason is None:
            return EdgeValidationResult(accepted=True)
        self._record(first_reason)
        return EdgeValidationResult(
            accepted=False,
            rejection_reason=first_reason,
            offending_node_ids=offenders,
            detail=detail,
        )

    def _pre_check_edge(self, edge: ProposedEdge) -> EdgeValidationResult | None:
        """Pure-Python confidence + schema checks; returns a rejection result
        or ``None`` to indicate the edge passes the pre-check.

        Uses ``StructuralRejection`` so that schema/confidence failures are
        labelled under ``custodian_structural_rejections``, not the citation
        metric prefix.
        """
        if edge.confidence < 0.7:
            return EdgeValidationResult(
                accepted=False,
                rejection_reason=StructuralRejection.LOW_CONFIDENCE,
                offending_node_ids=[],
                detail=f"confidence {edge.confidence} < 0.7",
            )

        from context_service.extraction.models import EXTRACTION_SCHEMA

        if not EXTRACTION_SCHEMA.is_valid(edge.source_type, edge.type, edge.target_type):
            return EdgeValidationResult(
                accepted=False,
                rejection_reason=StructuralRejection.SCHEMA_VIOLATION,
                offending_node_ids=[],
                detail=(
                    f"({edge.source_type}, {edge.type}, {edge.target_type}) "
                    "not in 9-vocab extraction schema"
                ),
            )
        return None

    @staticmethod
    def _edge_node_ids(edge: ProposedEdge) -> list[str]:
        """Return every node id an edge names, deduped, in endpoint+supporting order."""
        all_ids: list[str] = []
        seen_local: set[str] = set()
        for node_id in (
            edge.source_node_id,
            edge.target_node_id,
            *edge.supporting_node_ids,
        ):
            if node_id not in seen_local:
                seen_local.add(node_id)
                all_ids.append(node_id)
        return all_ids

    @staticmethod
    def _check_node_ids_sync(
        node_ids: list[str],
        silo_id: str,
        seen_node_ids: set[str],
        lookup_map: dict[str, dict[str, str]],
    ) -> tuple[CitationRejection | None, list[str], str | None]:
        """Evaluate the citation checks against a pre-fetched lookup map.

        Returns ``(first_failing_reason, all_offending_ids, detail)``.
        ``first_failing_reason`` follows: hallucinated_node_id ->
        invalid_citation -> cross_silo.
        """
        offenders: list[str] = []
        first_reason: CitationRejection | None = None

        hallucinated: list[str] = [nid for nid in node_ids if nid not in seen_node_ids]
        if hallucinated:
            first_reason = CitationRejection.HALLUCINATED_NODE_ID
            offenders.extend(hallucinated)

        survivors = [nid for nid in node_ids if nid in seen_node_ids]
        if survivors:
            missing: list[str] = []
            cross_silo: list[str] = []

            for nid in survivors:
                row = lookup_map.get(nid)
                if row is None:
                    missing.append(nid)
                    continue
                if row["silo_id"] != silo_id:
                    cross_silo.append(nid)
                    continue

            for bucket, reason in (
                (missing, CitationRejection.INVALID_CITATION),
                (cross_silo, CitationRejection.CROSS_SILO),
            ):
                if bucket:
                    if first_reason is None:
                        first_reason = reason
                    offenders.extend(bucket)

        if first_reason is None:
            return None, [], None

        seen_off: set[str] = set()
        deduped: list[str] = []
        for nid in offenders:
            if nid not in seen_off:
                seen_off.add(nid)
                deduped.append(nid)

        detail = f"{len(deduped)} citation(s) rejected; first reason={first_reason}"
        return first_reason, deduped, detail

    def _record(self, reason: CitationRejection | StructuralRejection) -> None:
        """Increment the rejection metric if a backend is wired up."""
        if self._metrics is None:
            return
        # Metrics must never crash the write path.
        with contextlib.suppress(Exception):  # pragma: no cover
            self._metrics.increment_claim_rejection(reason)
