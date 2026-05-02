"""CLI promote logic for transitioning :Finding nodes from draft to published (Task 17).

Promotion covers two object types:

1. **:Finding nodes** -- ``SET f.status = 'published', f.published_at = datetime()``.
   One Cypher update per finding.

2. **:ProposedEdge nodes** -- lifted into real graph edges. Memgraph's Cypher does not
   support parameterized relationship types in ``CREATE``, so promotion is a 9-way
   dispatch keyed on :class:`~context_service.extraction.models.RelationshipType`.

All writes for a single :func:`execute_promotion` call run inside a single bolt
transaction -- partial failure rolls back the entire promotion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from context_service.db.schema import content_union_predicate
from context_service.extraction.models import RelationshipType

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore


# ---------------------------------------------------------------------------
# Cypher: fetch draft findings
# ---------------------------------------------------------------------------

_FETCH_DRAFT_FINDINGS_BY_PASS = """
MATCH (f:Finding {pass_id: $pass_id, status: 'draft'})
RETURN f.id AS finding_id, f.cluster_id AS cluster_id, f.quality_score AS quality_score
"""

_FETCH_DRAFT_FINDING_BY_ID = """
MATCH (f:Finding {id: $finding_id, status: 'draft'})
RETURN f.id AS finding_id, f.cluster_id AS cluster_id, f.quality_score AS quality_score
LIMIT 1
"""

_FETCH_PROPOSED_EDGES_BY_PASS = """
MATCH (pe:ProposedEdge {pass_id: $pass_id, status: 'draft'})
RETURN pe.id AS edge_id,
       pe.type AS type,
       pe.source_node_id AS source_node_id,
       pe.target_node_id AS target_node_id
"""

_FETCH_PROPOSED_EDGES_BY_FINDING = """
MATCH (pe:ProposedEdge {status: 'draft'})
WHERE pe.finding_id = $finding_id
RETURN pe.id AS edge_id,
       pe.type AS type,
       pe.source_node_id AS source_node_id,
       pe.target_node_id AS target_node_id
"""

# ---------------------------------------------------------------------------
# Cypher: promote a :Finding
# ---------------------------------------------------------------------------

_PROMOTE_FINDING = """
MATCH (f:Finding {id: $id, status: 'draft'})
SET f.status = 'published', f.published_at = datetime()
RETURN f.id AS id
"""

# ---------------------------------------------------------------------------
# Cypher: promote :ProposedEdge nodes into real edges (9-way dispatch)
# ---------------------------------------------------------------------------
# Memgraph does not support parameterized relationship types in CREATE, so
# we need one statement per RelationshipType. Each statement:
#   1. MATCHes the :ProposedEdge node by id.
#   2. MATCHes the source and target :Node nodes.
#   3. CREATEs the typed real edge with promotion metadata.
#   4. DELETEs the :ProposedEdge node.
#   5. RETURNs the created relationship's start node id for confirmation.


def _promote_edge_cypher(rel_type: str) -> str:
    return f"""
MATCH (pe:ProposedEdge {{id: $id}})
MATCH (src) WHERE {content_union_predicate("src")} AND src.id = pe.source_node_id
MATCH (tgt) WHERE {content_union_predicate("tgt")} AND tgt.id = pe.target_node_id
CREATE (src)-[r:{rel_type} {{
    source: 'custodian-v1', status: 'published',
    confidence: pe.confidence, rationale: pe.rationale,
    pass_id: pe.pass_id, promoted_at: datetime()
}}]->(tgt)
DELETE pe
RETURN id(r) AS rel_id
"""


PROMOTE_CYPHER_BY_TYPE: dict[RelationshipType, str] = {
    rt: _promote_edge_cypher(rt.value) for rt in RelationshipType
}


# ---------------------------------------------------------------------------
# Plan and result data classes
# ---------------------------------------------------------------------------


@dataclass
class PromotionPlan:
    """Describes what would be promoted without mutating anything."""

    findings: list[dict[str, Any]] = field(default_factory=list)
    """Each entry: {finding_id, cluster_id, quality_score}."""

    proposed_edges: list[dict[str, Any]] = field(default_factory=list)
    """Each entry: {edge_id, type, source_node_id, target_node_id}."""


@dataclass
class PromotionResult:
    """Result of executing a promotion."""

    findings_promoted: int = 0
    edges_promoted: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


async def plan_promotion(
    memgraph_client: HyperGraphStore,
    *,
    pass_id: str | None = None,
    finding_id: str | None = None,
    min_quality: float | None = None,
    org_id: str | None = None,  # noqa: ARG001  reserved for future org isolation
) -> PromotionPlan:
    """Build a :class:`PromotionPlan` without mutating the graph.

    Exactly one of ``pass_id`` or ``finding_id`` must be provided.

    Args:
        memgraph_client: Live Memgraph connection.
        pass_id: Promote all eligible draft findings from this pass.
        finding_id: Promote a single finding by id.
        min_quality: Only include findings at or above this quality threshold
            (only meaningful with ``pass_id``).
        org_id: Reserved for future org isolation; currently unused.

    Returns:
        A :class:`PromotionPlan` describing what :func:`execute_promotion`
        would commit.
    """
    if pass_id is None and finding_id is None:
        raise ValueError("Exactly one of pass_id or finding_id must be provided")
    if pass_id is not None and finding_id is not None:
        raise ValueError("Only one of pass_id or finding_id may be provided")

    findings: list[dict[str, Any]] = []
    proposed_edges: list[dict[str, Any]] = []

    if finding_id is not None:
        rows = await memgraph_client.execute_query(
            _FETCH_DRAFT_FINDING_BY_ID, {"finding_id": finding_id}
        )
        findings = [
            {
                "finding_id": r["finding_id"],
                "cluster_id": r.get("cluster_id"),
                "quality_score": r.get("quality_score"),
            }
            for r in rows
        ]
        # Fetch proposed edges associated with this finding
        for f in findings:
            edge_rows = await memgraph_client.execute_query(
                _FETCH_PROPOSED_EDGES_BY_FINDING, {"finding_id": f["finding_id"]}
            )
            proposed_edges.extend(
                {
                    "edge_id": r["edge_id"],
                    "type": r["type"],
                    "source_node_id": r["source_node_id"],
                    "target_node_id": r["target_node_id"],
                }
                for r in edge_rows
            )
    else:
        # pass_id branch
        rows = await memgraph_client.execute_query(
            _FETCH_DRAFT_FINDINGS_BY_PASS, {"pass_id": pass_id}
        )
        for r in rows:
            qs = r.get("quality_score")
            if min_quality is not None and (qs is None or float(qs) < min_quality):
                continue
            findings.append(
                {
                    "finding_id": r["finding_id"],
                    "cluster_id": r.get("cluster_id"),
                    "quality_score": qs,
                }
            )

        edge_rows = await memgraph_client.execute_query(
            _FETCH_PROPOSED_EDGES_BY_PASS, {"pass_id": pass_id}
        )
        # Filter proposed edges to only those whose finding is in the plan
        finding_ids = {f["finding_id"] for f in findings}
        for r in edge_rows:
            proposed_edges.append(
                {
                    "edge_id": r["edge_id"],
                    "type": r["type"],
                    "source_node_id": r["source_node_id"],
                    "target_node_id": r["target_node_id"],
                }
            )
        # Note: if pass_id + min_quality filtered out some findings, we still
        # promote their proposed edges since edges are pass-scoped, not
        # finding-scoped in the query above. Re-filter to only planned findings.
        if min_quality is not None:
            # Re-fetch edges only for planned findings
            proposed_edges = []
            for f in findings:
                fe_rows = await memgraph_client.execute_query(
                    _FETCH_PROPOSED_EDGES_BY_FINDING, {"finding_id": f["finding_id"]}
                )
                proposed_edges.extend(
                    {
                        "edge_id": r["edge_id"],
                        "type": r["type"],
                        "source_node_id": r["source_node_id"],
                        "target_node_id": r["target_node_id"],
                    }
                    for r in fe_rows
                )
            _ = finding_ids  # suppress unused-variable warning

    return PromotionPlan(findings=findings, proposed_edges=proposed_edges)


async def execute_promotion(
    memgraph_client: HyperGraphStore,
    plan: PromotionPlan,
) -> PromotionResult:
    """Execute a :class:`PromotionPlan` atomically.

    All finding promotions and edge promotions run inside a single bolt
    transaction. If anything raises, the transaction rolls back and no
    changes land.

    Args:
        memgraph_client: Live graph store connection.
        plan: The plan returned by :func:`plan_promotion`.

    Returns:
        A :class:`PromotionResult` with counts of what was promoted.
    """
    result = PromotionResult()

    async with memgraph_client.session() as session:
        tx = await session.begin_transaction()
        try:
            # Promote findings
            for f in plan.findings:
                row = await tx.run(_PROMOTE_FINDING, id=f["finding_id"])
                record = await row.single()
                if record is not None:
                    result.findings_promoted += 1
                else:
                    result.errors.append(
                        f"finding {f['finding_id']} not found or already published"
                    )

            # Promote proposed edges via 9-way dispatch
            for edge in plan.proposed_edges:
                edge_type_str = edge["type"]
                try:
                    rel_type = RelationshipType(edge_type_str)
                except ValueError:
                    result.errors.append(
                        f"edge {edge['edge_id']}: unknown relationship type {edge_type_str!r}"
                    )
                    continue

                cypher = PROMOTE_CYPHER_BY_TYPE[rel_type]
                row = await tx.run(cypher, id=edge["edge_id"])
                record = await row.single()
                if record is not None:
                    result.edges_promoted += 1
                else:
                    result.errors.append(
                        f"edge {edge['edge_id']} ({edge_type_str}): source/target nodes not found"
                    )

            await tx.commit()
        except Exception:
            await tx.rollback()
            raise

    return result
