"""Atomic per-visit Custodian write path.

Given a :class:`~context_service.custodian.models.FindingOutput` plus the
visit's tenant/silo/pass context and a
:class:`~context_service.custodian.validators.CitationValidator` instance,
:class:`WritePath` filters out hallucinated/cross-tenant citations, computes the
coverage-weighted quality score, and commits everything a visit produced -- the
finding upsert, :FindingHistory snapshot of the prior body, :CITES edges,
proposed-edge MERGEs, cluster ``last_custodian_*`` updates, and the :CLAIMED
pass-ledger edge -- inside a single bolt transaction against Memgraph. Either the
whole set lands or none of it does.

Silo-scope findings use ``(:Finding)-[:SUMMARIZES]->(:Silo)`` and skip the
cluster property update; cluster-scope findings use
``(:Finding)-[:ABOUT]->(:Cluster)`` and update
``last_custodian_pass_id``/``last_custodian_run_at``.

**All-claims-rejected policy.** When every claim a visit produced fails the
citation validator, the write is skipped entirely: no :Finding row, no
history snapshot, no cluster update, no :CLAIMED edge. :class:`WritePathResult`
returns all zeros with ``finding_id=""`` / ``version=0`` so the caller can
distinguish "committed empty" from "skipped".
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import BaseModel

from context_service.custodian.business_rules import BusinessRuleValidator
from context_service.custodian.pipeline import run_validation
from context_service.db.custodian_queries import (
    CITES_EDGE_CREATE_NODE,
    CLUSTER_LAST_CUSTODIAN_UPDATE,
    FINDING_HISTORY_CREATE,
    FINDING_HISTORY_TRIM,
    FINDING_MERGE_CLUSTER_SCOPE,
    FINDING_MERGE_SILO_SCOPE,
    PASS_CLAIMED_EDGE_MERGE,
    PROPOSED_EDGE_MERGE,
    fetch_current_finding,
)
from context_service.utils.json import dumps

if TYPE_CHECKING:
    from context_service.custodian.models import Claim, FindingOutput, ProposedEdge
    from context_service.custodian.validators import CitationValidator, RejectionMetrics
    from context_service.engine.protocols import HyperGraphStore

_default_business_validator = BusinessRuleValidator()


_STRIPPED_QUERY_PARAMS: frozenset[str] = frozenset({"ref", "fbclid"})

HISTORY_KEEP_COUNT: int = 20


def canonicalize_url(url: str) -> str:
    """Canonicalize a URL for MERGE dedup on (tenant_id, url_canonical).

    Applies: lowercase host, strip leading www., strip trailing slash
    (except root), drop utm_*/ref/fbclid params, drop fragment, sort
    remaining query params for determinism, preserve scheme.

    Raises:
        ValueError: if the URL has no scheme or no host.
    """
    if not isinstance(url, str) or not url:
        raise ValueError("url must be a non-empty string")

    parsed = urlparse(url)

    if not parsed.scheme:
        raise ValueError(f"url has no scheme: {url!r}")
    if not parsed.hostname:
        raise ValueError(f"url has no host: {url!r}")

    host = parsed.hostname.lower()
    if host.startswith("www."):
        host = host[4:]

    netloc = host
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"

    path = parsed.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    filtered_params = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _STRIPPED_QUERY_PARAMS
    ]
    filtered_params.sort()
    query = urlencode(filtered_params)

    return urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_claims(claims: list[Claim]) -> str:
    """JSON-serialize a list of Claim models with stable key ordering.

    Memgraph has no native JSON type -- claims are stored as a string property
    on :Finding. ``sort_keys=True`` is load-bearing for the claims-hash used
    in :FindingHistory so identical claim buffers hash to the same value
    regardless of attribute insertion order.
    """
    return dumps(
        [claim.model_dump() for claim in claims],
        sort_keys=True,
        separators=(",", ":"),
    )


def _serialize_edges(edges: list[ProposedEdge]) -> str:
    return dumps(
        [edge.model_dump() for edge in edges],
        sort_keys=True,
        separators=(",", ":"),
    )


def _serialize_summary(finding: FindingOutput) -> str:
    if finding.summary is None:
        return dumps(None)
    return dumps(finding.summary.model_dump(), sort_keys=True, separators=(",", ":"))


def _hash_claims(claims: list[Claim]) -> str:
    """Deterministic sha256 of a claims list for :FindingHistory identity."""
    payload = _serialize_claims(claims).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class WritePathResult(BaseModel):
    """Summary of a completed (or skipped) visit write.

    ``finding_id == ""`` and ``version == 0`` signal the all-claims-rejected
    skip branch. Every other field is a count of items that actually landed
    in Memgraph.
    """

    finding_id: str
    version: int
    claims_committed: int
    claims_rejected: int
    edges_committed: int
    edges_rejected: int
    references_upserted: int
    history_snapshot_created: bool
    skipped: bool = False


# ---------------------------------------------------------------------------
# WritePath
# ---------------------------------------------------------------------------


class WritePath:
    """Atomic per-visit write path.

    See the module docstring for the full contract. Usage::

        write_path = WritePath(memgraph_client, citation_validator)
        result = await write_path.write_visit(
            finding=finding,
            pass_id=pass_id,
            cluster_size=len(members),
            seen_node_ids=seen,
        )
    """

    def __init__(
        self,
        memgraph_client: HyperGraphStore,
        citation_validator: CitationValidator,
        metrics: RejectionMetrics | None = None,
        business_validator: BusinessRuleValidator | None = None,
    ) -> None:
        self._client = memgraph_client
        self._validator = citation_validator
        self._metrics = metrics
        self._business = business_validator or _default_business_validator

    async def write_visit(
        self,
        finding: FindingOutput,
        pass_id: str,
        cluster_size: int,
        seen_node_ids: set[str],
        *,
        org_id: str,
        visit_ref: str | None = None,
        model_name: str | None = None,
        member_fingerprint: str | None = None,
    ) -> WritePathResult:
        """Validate, persist, and summarize one visit's findings.

        1. Validates every claim and proposed edge via the citation validator.
           Rejected items are dropped (validator records the metric).
        2. If every claim was rejected, returns a skip result without writing.
        3. Reads the quality score from :class:`BusinessRuleValidator` result.
        4. Inside a single bolt transaction: snapshots any prior finding to
           :FindingHistory, MERGEs the new :Finding body with scope-aware
           uniqueness, trims history, creates :CITES edges to every cited
           node, MERGEs surviving proposed edges, updates cluster metadata
           (cluster-scope only), and MERGEs the :CLAIMED pass ledger edge
           (cluster-scope only).
        """
        # ------------------------------------------------------------------
        # Steps 1+2: citation validation then business rule gate via pipeline.
        # ------------------------------------------------------------------
        pipeline_result = await run_validation(
            finding=finding,
            seen_node_ids=seen_node_ids,
            citation_validator=self._validator,
            business_validator=self._business,
            cluster_size=cluster_size,
        )
        if pipeline_result.citation is None:
            raise RuntimeError("citation stage unexpectedly None after success")
        surviving_claims = pipeline_result.citation.surviving_claims
        surviving_edges = pipeline_result.citation.surviving_edges
        claims_rejected = pipeline_result.citation.claims_rejected
        edges_rejected = pipeline_result.citation.edges_rejected
        if pipeline_result.failed_at is not None:
            return WritePathResult(
                finding_id="",
                version=0,
                claims_committed=0,
                claims_rejected=claims_rejected,
                edges_committed=0,
                edges_rejected=edges_rejected,
                references_upserted=0,
                history_snapshot_created=False,
                skipped=True,
            )

        # ------------------------------------------------------------------
        # Step 3: use quality score from business rule result.
        # ------------------------------------------------------------------
        biz = pipeline_result.business
        if biz is None:
            raise RuntimeError("business stage unexpectedly None after success")
        survivor_finding = finding.model_copy(
            update={
                "claims": surviving_claims,
                "inferred_relations": surviving_edges,
            }
        )
        qscore = biz.computed_quality

        # ------------------------------------------------------------------
        # Step 4: single bolt transaction with all writes.
        # ------------------------------------------------------------------
        now_iso = _now_iso()
        claims_json = _serialize_claims(surviving_claims)
        edges_json = _serialize_edges(surviving_edges)
        summary_json = _serialize_summary(survivor_finding)

        history_created = False

        async with self._client.transaction() as tx:
            # 4a. Look up prior finding inside the same transaction.
            prior = await fetch_current_finding(
                tx,
                scope=finding.scope,
                cluster_id=finding.cluster_id,
                silo_id=finding.silo_id,
            )

            if prior is not None:
                finding_id = str(prior["id"])
                next_version = int(prior["version"] or 0) + 1
                created_at = None  # MERGE ON CREATE won't fire; existing row
                # 4b. Snapshot prior body to :FindingHistory.
                prior_claims_str = prior.get("claims") or "[]"
                prior_claims_hash = hashlib.sha256(
                    prior_claims_str.encode("utf-8")
                ).hexdigest()
                prior_summary = prior.get("summary") or dumps(None)
                prior_pass_id = prior.get("pass_id") or pass_id

                await tx.run(
                    FINDING_HISTORY_CREATE,
                    finding_id=finding_id,
                    pass_id=prior_pass_id,
                    summary=prior_summary,
                    claims_hash=prior_claims_hash,
                    created_at=now_iso,
                    org_id=org_id,
                )
                history_created = True
            else:
                finding_id = str(uuid.uuid4())
                next_version = 1
                created_at = now_iso

            # 4c. MERGE the finding body (scope-aware).
            merge_params: dict[str, Any] = {
                "id": finding_id,
                "scope": finding.scope,
                "org_id": org_id,
                "silo_id": finding.silo_id,
                "pass_id": pass_id,
                "version": next_version,
                "status": "draft",
                "summary_json": summary_json,
                "claims_json": claims_json,
                "inferred_json": edges_json,
                "member_fingerprint": member_fingerprint,
                "quality_score": qscore,
                "visit_ref": visit_ref,
                "source": "custodian",
                "model": model_name,
                "created_at": created_at if created_at is not None else now_iso,
                "updated_at": now_iso,
            }

            if finding.scope == "cluster":
                merge_params["cluster_id"] = finding.cluster_id
                merge_result = await tx.run(FINDING_MERGE_CLUSTER_SCOPE, **merge_params)
            else:
                merge_result = await tx.run(FINDING_MERGE_SILO_SCOPE, **merge_params)

            merge_row = await merge_result.single()
            if merge_row is None:
                raise RuntimeError(
                    f"finding MERGE returned no row -- scope={finding.scope} "
                    f"silo={finding.silo_id} cluster={finding.cluster_id}"
                )
            finding_id = str(merge_row["id"])

            # 4d. Trim :FindingHistory to the most-recent HISTORY_KEEP_COUNT.
            if history_created:
                await tx.run(
                    FINDING_HISTORY_TRIM,
                    finding_id=finding_id,
                    keep=HISTORY_KEEP_COUNT,
                )

            # 4e. Create :CITES edges to every cited :Node.
            cited_pairs: set[tuple[str, str]] = set()
            for claim in surviving_claims:
                for citation in claim.citations:
                    pair = (citation.node_id, citation.kind)
                    if pair in cited_pairs:
                        continue
                    cited_pairs.add(pair)
                    await tx.run(
                        CITES_EDGE_CREATE_NODE,
                        finding_id=finding_id,
                        node_id=citation.node_id,
                        kind=citation.kind,
                    )

            # 4f. MERGE each surviving proposed edge.
            for edge in surviving_edges:
                await tx.run(
                    PROPOSED_EDGE_MERGE,
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                    type=str(edge.type),
                    pass_id=pass_id,
                    source_type=edge.source_type,
                    target_type=edge.target_type,
                    confidence=float(edge.confidence),
                    rationale=edge.rationale,
                    supporting_node_ids=list(edge.supporting_node_ids),
                    org_id=org_id,
                    silo_id=finding.silo_id,
                    now_iso=now_iso,
                )

            # 4g. Cluster-scope only: last_custodian_* update + :CLAIMED edge.
            if finding.scope == "cluster" and finding.cluster_id is not None:
                await tx.run(
                    CLUSTER_LAST_CUSTODIAN_UPDATE,
                    cluster_id=finding.cluster_id,
                    silo_id=finding.silo_id,
                    pass_id=pass_id,
                    now_iso=now_iso,
                )
                await tx.run(
                    PASS_CLAIMED_EDGE_MERGE,
                    pass_id=pass_id,
                    cluster_id=finding.cluster_id,
                    claimed_at=now_iso,
                )

        return WritePathResult(
            finding_id=finding_id,
            version=next_version,
            claims_committed=len(surviving_claims),
            claims_rejected=claims_rejected,
            edges_committed=len(surviving_edges),
            edges_rejected=edges_rejected,
            references_upserted=0,
            history_snapshot_created=history_created,
            skipped=False,
        )
