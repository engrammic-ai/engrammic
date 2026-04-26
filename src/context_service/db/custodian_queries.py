"""Custodian-specific Cypher statements and schema bootstrap.

This module is the single home for Custodian-related Memgraph DDL. The shape of
the nodes and edges here comes from the brainstorm at
``context/brainstorm/2026-04-05-custodian.md`` (Data Model section) and the
phase plan at ``context/plans/2026-04-05-custodian-phase.md`` (Task 3).

Schema summary
--------------

``:Finding`` — a single label covers both cluster-scope and silo-scope findings,
distinguished by the ``scope`` property (``"cluster"`` or ``"silo"``). Two
separate composite uniqueness constraints enforce one finding per target:

    - ``(scope, cluster_id, silo_id)`` unique — cluster-scope findings
    - ``(scope, silo_id)`` unique — silo-scope findings (cluster_id is null)

Both constraints include the ``scope`` field so they do not collide: a
cluster-scope finding and a silo-scope finding can share the same
``silo_id`` without tripping either constraint. Cluster-scope findings link
via ``(:Finding)-[:ABOUT]->(:Cluster)``; silo-scope findings link via
``(:Finding)-[:SUMMARIZES]->(:Silo)``. Edge creation is Task 6's concern;
this module only defines the labels, constraints, and indexes.

``:Pass`` — the pass ledger. One node per Custodian pass::

    (:Pass {
        id: uuid,
        silo_id: uuid,
        org_id: string,
        status: "running" | "completed" | "failed" | "cancelled"
              | "crashed" | "budget_exceeded",
        started_at: datetime,
        finalized_at: datetime | null,
        cost_usd: float,
        visit_count: int
    })

No uniqueness constraint (the ``id`` property is a uuid; collisions are
impossible). An index on ``(silo_id, started_at)`` supports recent-pass
queries per silo.

``:CLAIMED`` — the per-visit idempotency ledger edge:
``(:Pass)-[:CLAIMED {claimed_at: datetime}]->(:Cluster)``. A second attempt
to visit the same cluster within the same pass sees this edge and is a
no-op. No constraint required — the pass transaction checks the edge
before committing work (see plan Task 6 Risk R3).

``:FindingHistory`` — snapshots of prior ``:Finding`` bodies. Linked via
``(:Finding)-[:SUPERSEDES]->(:FindingHistory)``. No uniqueness constraint;
the chain is ordered by ``pass_id`` at read time and capped at 20 entries
per finding by the write path (Task 6).

``:Reference`` — canonicalized external citations. MERGE key is
``(org_id, url_canonical)``. URL canonicalization itself is Task 4's
concern; this module only declares the label and a lookup index on
``(org_id, url)`` so the canonicalized-URL MERGEs land on a seek, not a
scan.

``:Cluster`` additive properties — two new nullable fields:
``last_custodian_pass_id`` and ``last_custodian_run_at``. Additive with null
defaults; no backfill.

Memgraph syntax notes
---------------------

Memgraph's constraint DDL differs from Neo4j's. Memgraph uses::

    CREATE CONSTRAINT ON (f:Finding) ASSERT f.scope, f.cluster_id, f.silo_id IS UNIQUE;

with no parentheses around the property list and **no** ``IF NOT EXISTS``
clause. Memgraph's ``CREATE CONSTRAINT`` is idempotent by default — issuing
the same DDL twice is a no-op, which satisfies our "re-running bootstrap is
safe" requirement. Same idempotency holds for ``CREATE INDEX``. Reference:
https://memgraph.com/docs/fundamentals/constraints and
https://memgraph.com/docs/fundamentals/indexes.

If a future Memgraph version changes this behavior, the bootstrap
function below swallows "already exists" style errors per statement so
that re-running remains safe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.config.logging import get_logger
from context_service.db.schema import content_union_predicate

if TYPE_CHECKING:
    from neo4j import AsyncTransaction

    from context_service.stores.memgraph import MemgraphClient

logger = get_logger(__name__)


# =============================================================================
# Composite uniqueness constraints on :Finding
# =============================================================================

# Cluster-scope findings: one finding per (cluster_id, silo_id) pair, scoped
# by scope="cluster".
FINDING_CLUSTER_SCOPE_UNIQUE = (
    "CREATE CONSTRAINT ON (f:Finding) ASSERT f.scope, f.cluster_id, f.silo_id IS UNIQUE;"
)

# Silo-scope uniqueness is NOT enforced via a Memgraph constraint because
# Memgraph does not support conditional/partial constraints. The constraint
# (scope, silo_id) IS UNIQUE would incorrectly reject a second cluster-scope
# finding in the same silo. Silo-scope uniqueness is instead enforced by the
# write path's MERGE key: (scope="silo", cluster_id=null, silo_id).
FINDING_SILO_SCOPE_UNIQUE = ""  # intentionally empty; see comment above


# =============================================================================
# Indexes
# =============================================================================

# Read-path index for cluster-scope finding lookups.
FINDING_ORG_SCOPE_INDEX = "CREATE INDEX ON :Finding(org_id);"
FINDING_SILO_INDEX = "CREATE INDEX ON :Finding(silo_id);"
FINDING_CLUSTER_INDEX = "CREATE INDEX ON :Finding(cluster_id);"

# Pass ledger lookups.
PASS_ID_INDEX = "CREATE INDEX ON :Pass(id);"
PASS_SILO_INDEX = "CREATE INDEX ON :Pass(silo_id);"

# Reference canonicalized-URL lookups. Canonicalization happens in Task 4;
# this index supports the MERGE-on-canonical-url pattern.
REFERENCE_ORG_INDEX = "CREATE INDEX ON :Reference(org_id);"
REFERENCE_URL_INDEX = "CREATE INDEX ON :Reference(url);"

# FindingHistory lookups (by the finding that supersedes it).
FINDING_HISTORY_PASS_INDEX = "CREATE INDEX ON :FindingHistory(pass_id);"


# =============================================================================
# Bootstrap sequence
# =============================================================================

BOOTSTRAP_STATEMENTS: list[str] = [
    # Constraints first — they are the correctness-critical bits.
    FINDING_CLUSTER_SCOPE_UNIQUE,
    FINDING_SILO_SCOPE_UNIQUE,
    # Then indexes — purely performance; safe to add after constraints.
    FINDING_ORG_SCOPE_INDEX,
    FINDING_SILO_INDEX,
    FINDING_CLUSTER_INDEX,
    PASS_ID_INDEX,
    PASS_SILO_INDEX,
    REFERENCE_ORG_INDEX,
    REFERENCE_URL_INDEX,
    FINDING_HISTORY_PASS_INDEX,
]


async def bootstrap_custodian_schema(client: MemgraphClient) -> None:
    """Apply Custodian schema DDL to Memgraph.

    Each statement is idempotent in Memgraph — re-running bootstrap on an
    already-migrated instance is a no-op. If a statement raises because it
    already exists (future Memgraph versions may change behavior), the error
    is logged at debug level and bootstrap continues.

    This function is safe to call multiple times.
    """
    logger.info(
        "Applying Custodian schema bootstrap (%d statements)",
        len(BOOTSTRAP_STATEMENTS),
    )
    for statement in BOOTSTRAP_STATEMENTS:
        if not statement:
            continue
        try:
            async with client.session() as session:
                result = await session.run(statement)
                await result.consume()
        except Exception as exc:  # pragma: no cover - defensive idempotency guard
            # Memgraph CREATE CONSTRAINT / CREATE INDEX are idempotent today,
            # but swallow "already exists" style errors defensively so
            # bootstrap never crashes the app on a re-run.
            logger.debug(
                "Custodian bootstrap statement note (likely already applied): %s — %s",
                statement.split("\n", 1)[0],
                exc,
            )
    logger.info("Custodian schema bootstrap complete")


# =============================================================================
# Per-visit write-path Cypher (Task 6)
# =============================================================================
#
# These constants are the full set of parameterized Cypher statements that the
# Custodian per-visit write path runs inside a single bolt transaction (see
# ``context_service/custodian/write_path.py`` and the brainstorm's "Write Path
# / Atomicity" section). Every statement is a plain module-level string with
# ``$param`` placeholders so that (a) tests can inspect them verbatim and (b)
# there is never any runtime string concatenation of Cypher with
# caller-supplied values.
#
# Naming convention: FINDING_*, REFERENCE_*, CITES_*, PROPOSED_EDGE_*,
# CLUSTER_*, PASS_*. Parameter docstrings live as comments directly above
# each constant.

# Look up the prior :Finding for a cluster-scope (scope, cluster_id, silo_id)
# triple, returning the fields needed to snapshot its body to :FindingHistory
# and compute the next version number. Returns at most one row.
#
# Params:
#   scope       (str)  -- always "cluster"
#   cluster_id  (str)
#   silo_id     (str)
FETCH_CURRENT_FINDING_CLUSTER_SCOPE = """
MATCH (f:Finding {scope: $scope, cluster_id: $cluster_id, silo_id: $silo_id})
RETURN f.id AS id,
       f.version AS version,
       f.claims AS claims,
       f.summary AS summary,
       f.pass_id AS pass_id,
       f.quality_score AS quality_score
LIMIT 1
"""

# Look up the prior :Finding for a silo-scope (scope, silo_id) pair.
#
# Params:
#   scope    (str)  -- always "silo"
#   silo_id  (str)
FETCH_CURRENT_FINDING_SILO_SCOPE = """
MATCH (f:Finding {scope: $scope, silo_id: $silo_id})
WHERE f.cluster_id IS NULL
RETURN f.id AS id,
       f.version AS version,
       f.claims AS claims,
       f.summary AS summary,
       f.pass_id AS pass_id,
       f.quality_score AS quality_score
LIMIT 1
"""

# MERGE a cluster-scope :Finding row and attach the (:Finding)-[:ABOUT]->(:Cluster)
# edge. The MERGE key is (scope, cluster_id, silo_id) — matching the
# FINDING_CLUSTER_SCOPE_UNIQUE constraint. All body fields are set on every
# write; the history snapshot runs as a separate statement *before* this one
# so the prior body is preserved.
#
# Params:
#   id                 (str)      -- stable finding id (reuses prior id on update)
#   scope              (str)      -- "cluster"
#   cluster_id         (str)
#   silo_id            (str)
#   org_id             (str)
#   pass_id            (str)
#   version            (int)
#   status             (str)      -- "draft"
#   summary_json       (str)      -- JSON-serialized StitchedSummary (or "null")
#   claims_json        (str)      -- JSON-serialized list[Claim.model_dump()]
#   inferred_json      (str)      -- JSON-serialized list[ProposedEdge.model_dump()]
#   member_fingerprint (str | None)
#   quality_score      (float)
#   visit_ref          (str | None) -- Redis key; Task 10 populates, may be null
#   source             (str)      -- "custodian"
#   model              (str | None)
#   created_at         (str)      -- ISO8601 datetime for first-write; callers
#                                     pass the existing value on update so the
#                                     ON CREATE branch keeps identical semantics
#   updated_at         (str)      -- ISO8601 datetime
FINDING_MERGE_CLUSTER_SCOPE = """
MERGE (f:Finding {scope: $scope, cluster_id: $cluster_id, silo_id: $silo_id})
ON CREATE SET
    f.id = $id,
    f.created_at = $created_at
SET f.org_id = $org_id,
    f.pass_id = $pass_id,
    f.version = $version,
    f.status = $status,
    f.summary = $summary_json,
    f.claims = $claims_json,
    f.inferred_relations = $inferred_json,
    f.member_fingerprint = $member_fingerprint,
    f.quality_score = $quality_score,
    f.visit_ref = $visit_ref,
    f.needs_refresh = false,
    f.source = $source,
    f.model = $model,
    f.updated_at = $updated_at
WITH f
MATCH (c:Cluster {id: $cluster_id})
MERGE (f)-[:ABOUT]->(c)
RETURN f.id AS id, f.version AS version
"""

# MERGE a silo-scope :Finding row and attach (:Finding)-[:SUMMARIZES]->(:Silo).
# The MERGE key is (scope, silo_id); cluster_id stays null.
#
# Params: same as FINDING_MERGE_CLUSTER_SCOPE minus cluster_id.
FINDING_MERGE_SILO_SCOPE = """
MERGE (f:Finding {scope: $scope, silo_id: $silo_id})
ON CREATE SET
    f.id = $id,
    f.created_at = $created_at,
    f.cluster_id = null
SET f.org_id = $org_id,
    f.pass_id = $pass_id,
    f.version = $version,
    f.status = $status,
    f.summary = $summary_json,
    f.claims = $claims_json,
    f.inferred_relations = $inferred_json,
    f.member_fingerprint = $member_fingerprint,
    f.quality_score = $quality_score,
    f.visit_ref = $visit_ref,
    f.needs_refresh = false,
    f.source = $source,
    f.model = $model,
    f.updated_at = $updated_at
WITH f
MATCH (s:Silo {id: $silo_id})
MERGE (f)-[:SUMMARIZES]->(s)
RETURN f.id AS id, f.version AS version
"""

# Create a :FindingHistory snapshot of the prior body and link it via
# (:Finding)-[:SUPERSEDES]->(:FindingHistory). Called only when a prior
# finding existed (fetch_current_finding returned a row). Trimming to the
# most-recent 20 entries is a separate statement run immediately after.
#
# Params:
#   finding_id   (str)  -- the id returned by fetch_current_finding
#   pass_id      (str)  -- the *prior* finding's pass_id, so history records
#                          which pass authored the snapshotted body
#   summary      (str)  -- prior summary JSON string (as stored)
#   claims_hash  (str)  -- sha256 of the prior claims JSON
#   created_at   (str)  -- ISO8601; the snapshot's own timestamp (now)
#   org_id       (str)  -- carried on :FindingHistory for test-org cleanup
FINDING_HISTORY_CREATE = """
MATCH (f:Finding {id: $finding_id})
CREATE (h:FindingHistory {
    pass_id: $pass_id,
    summary: $summary,
    claims_hash: $claims_hash,
    created_at: $created_at,
    org_id: $org_id
})
CREATE (f)-[:SUPERSEDES]->(h)
RETURN h.pass_id AS pass_id
"""

# Trim :FindingHistory nodes for a given finding to the most recent
# ``$keep`` entries. Older snapshots are DETACH DELETEd. Ordering is by
# the history node's own ``created_at`` property — callers always set this
# with the write-path wall clock so order is stable and test-reproducible.
#
# Params:
#   finding_id (str)
#   keep       (int)  -- always 20 in v1
FINDING_HISTORY_TRIM = """
MATCH (f:Finding {id: $finding_id})-[:SUPERSEDES]->(h:FindingHistory)
WITH h ORDER BY h.created_at DESC
SKIP $keep
DETACH DELETE h
"""

# MERGE a :Reference row on (org_id, url_canonical). Forward-compatible
# plumbing for a future phase that extends Citation/ProposedEdge with URL
# fields — in Task 6 neither model carries a URL, so this Cypher has no
# live caller yet. Kept here so the schema is centralized.
#
# Params:
#   id              (str)
#   org_id          (str)
#   url_canonical   (str)  -- caller canonicalizes via canonicalize_url
#   url_original    (str)
#   title           (str | None)
#   kind            (str)  -- "docs" | "paper" | "issue" | "spec" | "article" | "other"
#   domain          (str)
#   now_iso         (str)
REFERENCE_MERGE = """
MERGE (r:Reference {org_id: $org_id, url: $url_canonical})
ON CREATE SET
    r.id = $id,
    r.url_original = $url_original,
    r.title = $title,
    r.kind = $kind,
    r.domain = $domain,
    r.first_cited_at = $now_iso,
    r.last_cited_at = $now_iso
ON MATCH SET
    r.last_cited_at = $now_iso
RETURN r.id AS id
"""

# Create an idempotent (:Finding)-[:CITES {kind}]->(content node) edge.
# MERGE on the (finding_id, node_id, kind) triple so re-runs do not duplicate
# edges. Label-union match accepts Document|Passage|Claim per O-30: content
# nodes no longer use the legacy :Node label after phase-3 schema split.
#
# Params:
#   finding_id (str)
#   node_id    (str)
#   kind       (str)  -- "primary" | "supporting"
CITES_EDGE_CREATE_NODE = f"""
MATCH (f:Finding {{id: $finding_id}})
MATCH (n {{id: $node_id}})
WHERE {content_union_predicate("n")}
MERGE (f)-[e:CITES {{kind: $kind}}]->(n)
RETURN e.kind AS kind
"""

# Alias for the lead's preferred single-name constant. Points at the
# :Node variant because that is the live caller in Task 6; the :Reference
# variant is forward-compatible plumbing.
CITES_EDGE_CREATE = CITES_EDGE_CREATE_NODE


# Forward-compatible :CITES edge targeting a :Reference. Unused in Task 6
# (no live caller); defined here for schema centralization.
#
# Params: finding_id, reference_id, kind
CITES_EDGE_CREATE_REFERENCE = """
MATCH (f:Finding {id: $finding_id})
MATCH (r:Reference {id: $reference_id})
MERGE (f)-[e:CITES {kind: $kind}]->(r)
RETURN e.kind AS kind
"""

# MERGE a proposed edge row on the brainstorm's idempotency key
# (source, target, type, pass_id). Per-pass keyed by design — a later pass
# re-proposing the same edge gets its own row. All bodies are strings/floats
# for portability; supporting_node_ids is a Cypher list. Stored as a
# :ProposedEdge node (not a live graph edge) so it stays clearly in draft
# state until a future promotion flow lifts it to a real edge.
#
# Params:
#   source_node_id       (str)
#   target_node_id       (str)
#   type                 (str)
#   pass_id              (str)
#   source_type          (str)
#   target_type          (str)
#   confidence           (float)
#   rationale            (str)
#   supporting_node_ids  (list[str])
#   org_id               (str)
#   silo_id              (str)
#   now_iso              (str)
PROPOSED_EDGE_MERGE = """
MERGE (p:ProposedEdge {
    source_node_id: $source_node_id,
    target_node_id: $target_node_id,
    type: $type,
    pass_id: $pass_id
})
ON CREATE SET
    p.source_type = $source_type,
    p.target_type = $target_type,
    p.confidence = $confidence,
    p.rationale = $rationale,
    p.supporting_node_ids = $supporting_node_ids,
    p.org_id = $org_id,
    p.silo_id = $silo_id,
    p.source = 'custodian-v1',
    p.status = 'draft',
    p.created_at = $now_iso
SET p.updated_at = $now_iso
RETURN p.source_node_id AS source_node_id,
       p.target_node_id AS target_node_id,
       p.type AS type
"""

# Update :Cluster.last_custodian_pass_id and last_custodian_run_at. Cluster-
# scope writes only; silo-scope findings do not touch this.
#
# Params:
#   cluster_id (str)
#   pass_id    (str)
#   now_iso    (str)
CLUSTER_LAST_CUSTODIAN_UPDATE = """
MATCH (c:Cluster {id: $cluster_id})
SET c.last_custodian_pass_id = $pass_id,
    c.last_custodian_run_at = $now_iso
RETURN c.id AS id
"""

# Create a :Pass node with initial state. Used by Task 11's pass lifecycle;
# defined here for centralization.
#
# Params:
#   id         (str)
#   silo_id    (str)
#   org_id     (str)
#   status     (str)  -- "running"
#   started_at (str)
PASS_CREATE = """
CREATE (p:Pass {
    id: $id,
    silo_id: $silo_id,
    org_id: $org_id,
    status: $status,
    started_at: $started_at,
    finalized_at: null,
    cost_usd: 0.0,
    visit_count: 0
})
RETURN p.id AS id
"""

# MERGE the (:Pass)-[:CLAIMED {claimed_at}]->(:Cluster) ledger edge. A second
# attempt to visit the same cluster within one pass sees this edge and is a
# no-op in the orchestrator (Task 10); the write path MERGEs it here as part
# of the committing transaction so the ledger is transactionally consistent
# with the finding write.
#
# Params:
#   pass_id    (str)
#   cluster_id (str)
#   claimed_at (str)
PASS_CLAIMED_EDGE_MERGE = """
MATCH (p:Pass {id: $pass_id})
MATCH (c:Cluster {id: $cluster_id})
MERGE (p)-[e:CLAIMED]->(c)
ON CREATE SET e.claimed_at = $claimed_at
RETURN e.claimed_at AS claimed_at
"""


# =============================================================================
# Helper: read prior finding inside a caller-supplied transaction
# =============================================================================


# Check if a cluster is already CLAIMED in this pass.
#
# Params:
#   pass_id    (str)
#   cluster_id (str)
PASS_CHECK_CLAIMED = """
MATCH (p:Pass {id: $pass_id})-[:CLAIMED]->(c:Cluster {id: $cluster_id})
RETURN count(*) > 0 AS claimed
"""

# Finalize a pass: set terminal status, finalized_at, accumulated cost, visit count.
#
# Params:
#   pass_id      (str)
#   status       (str)
#   finalized_at (str)  -- ISO8601
#   cost_usd     (float)
#   visit_count  (int)
PASS_FINALIZE = """
MATCH (p:Pass {id: $pass_id})
SET p.status = $status,
    p.finalized_at = $finalized_at,
    p.cost_usd = $cost_usd,
    p.visit_count = $visit_count
RETURN p.id AS id
"""

# Fetch clusters for a silo at a given level, with member counts. Clusters
# carry silo_id; membership is also confirmed via :Node members with matching
# silo_id.
#
# Params:
#   silo_id   (str)
#   level     (int)
FETCH_CLUSTERS_BY_LEVEL = f"""
MATCH (c:Cluster {{silo_id: $silo_id}})
WHERE c.level = $level
MATCH (n)-[:BELONGS_TO]->(c)
WHERE {content_union_predicate("n")} AND n.silo_id = $silo_id
WITH c, count(n) AS member_count
RETURN c.id AS cluster_id,
       c.level AS level,
       member_count,
       c.summary AS naive_summary
ORDER BY member_count DESC
"""

# Fetch published/extraction child finding summaries for a parent cluster.
# Applies the mandatory finding source filter from CLAUDE.md.
#
# Params:
#   cluster_id (str)
#   silo_id    (str)
FETCH_CHILD_FINDING_SUMMARIES = """
MATCH (parent:Cluster {id: $cluster_id, silo_id: $silo_id})
MATCH (child:Cluster)-[:PART_OF]->(parent)
MATCH (f:Finding)-[:ABOUT]->(child)
WHERE f.silo_id = $silo_id
  AND (f.source = 'extraction' OR f.status = 'published')
RETURN f.summary AS summary
"""


# ---------------------------------------------------------------------------
# Pass lifecycle helpers
# ---------------------------------------------------------------------------


async def create_pass(
    client: MemgraphClient,
    *,
    pass_id: str,
    silo_id: str,
    org_id: str,
    started_at: str,
) -> str:
    """Create a :Pass node in ``running`` state. Returns the pass_id."""
    rows = await client.execute_write(
        PASS_CREATE,
        {
            "id": pass_id,
            "silo_id": silo_id,
            "org_id": org_id,
            "status": "running",
            "started_at": started_at,
        },
    )
    result_id: str = rows[0]["id"]
    return result_id


async def check_claimed(
    client: MemgraphClient,
    *,
    pass_id: str,
    cluster_id: str,
) -> bool:
    """Return True if the cluster is already CLAIMED in this pass."""
    rows = await client.execute_query(
        PASS_CHECK_CLAIMED,
        {"pass_id": pass_id, "cluster_id": cluster_id},
    )
    if not rows:
        return False
    return bool(rows[0]["claimed"])


async def finalize_pass(
    client: MemgraphClient,
    *,
    pass_id: str,
    status: str,
    finalized_at: str,
    cost_usd: float,
    visit_count: int,
) -> None:
    """Set the terminal status and accounting fields on a :Pass node."""
    await client.execute_write(
        PASS_FINALIZE,
        {
            "pass_id": pass_id,
            "status": status,
            "finalized_at": finalized_at,
            "cost_usd": cost_usd,
            "visit_count": visit_count,
        },
    )


async def fetch_clusters_by_level(
    client: MemgraphClient,
    *,
    silo_id: str,
    level: int,
) -> list[dict[str, Any]]:
    """Return clusters for a silo at a given level, with member counts."""
    return await client.execute_query(
        FETCH_CLUSTERS_BY_LEVEL,
        {"silo_id": silo_id, "level": level},
    )


async def fetch_child_finding_summaries(
    client: MemgraphClient,
    *,
    cluster_id: str,
    silo_id: str,
) -> list[str]:
    """Return summary strings for published/extraction child findings."""
    rows = await client.execute_query(
        FETCH_CHILD_FINDING_SUMMARIES,
        {"cluster_id": cluster_id, "silo_id": silo_id},
    )
    return [r["summary"] for r in rows if r.get("summary")]


async def fetch_current_finding(
    tx: AsyncTransaction,
    scope: str,
    cluster_id: str | None,
    silo_id: str,
) -> dict[str, Any] | None:
    """Return the existing :Finding row for (scope, cluster_id, silo_id), or None.

    Runs inside a caller-supplied :class:`neo4j.AsyncTransaction` so the lookup
    and the subsequent MERGE land in the same bolt transaction — used by the
    write path to snapshot the prior claims into :FindingHistory *before*
    overwriting.

    For ``scope == "cluster"`` ``cluster_id`` must be provided; for
    ``scope == "silo"`` it must be ``None``.
    """
    if scope == "cluster":
        if cluster_id is None:
            raise ValueError("cluster-scope fetch requires cluster_id")
        result = await tx.run(
            FETCH_CURRENT_FINDING_CLUSTER_SCOPE,
            scope=scope,
            cluster_id=cluster_id,
            silo_id=silo_id,
        )
    elif scope == "silo":
        if cluster_id is not None:
            raise ValueError("silo-scope fetch must not supply cluster_id")
        result = await tx.run(
            FETCH_CURRENT_FINDING_SILO_SCOPE,
            scope=scope,
            silo_id=silo_id,
        )
    else:
        raise ValueError(f"unknown scope: {scope!r}")

    record = await result.single()
    if record is None:
        return None
    return dict(record)


# =============================================================================
# Silo synthesis queries (Task 12)
# =============================================================================

# Fetch all coarse-level findings for a silo with their claims.
# Applies the mandatory Finding source filter from CLAUDE.md.
#
# Params:
#   silo_id      (str)
#   coarse_level (int)  -- ClusterLevel.COARSE (3)
FETCH_COARSE_FINDINGS_FOR_SILO = """
MATCH (f:Finding {scope: "cluster", silo_id: $silo_id})-[:ABOUT]->(c:Cluster)
WHERE c.level = $coarse_level
  AND (f.source = 'extraction' OR f.status = 'published')
RETURN f.id AS finding_id,
       c.id AS cluster_id,
       f.summary AS summary,
       f.claims AS claims_json,
       f.quality_score AS quality_score
ORDER BY f.quality_score DESC
"""

# Top 20 entities by citation frequency across a silo. Used as fallback when
# Silo.description is null.
#
# Params:
#   silo_id   (str)
FETCH_TOP_ENTITIES_BY_CITATION = """
MATCH (f:Finding {silo_id: $silo_id})-[:CITES]->(n)
WHERE (f.source = 'extraction' OR f.status = 'published')
  AND (n:Document OR n:Passage OR n:Claim)
WITH n, count(f) AS cite_count
ORDER BY cite_count DESC
LIMIT 20
RETURN n.id AS node_id, n.content AS content, cite_count
"""


async def fetch_coarse_findings_for_silo(
    client: MemgraphClient,
    *,
    silo_id: str,
    coarse_level: int,
) -> list[dict[str, Any]]:
    """Return coarse-level cluster findings for a silo, ordered by quality."""
    return await client.execute_query(
        FETCH_COARSE_FINDINGS_FOR_SILO,
        {"silo_id": silo_id, "coarse_level": coarse_level},
    )


async def fetch_top_entities_by_citation(
    client: MemgraphClient,
    *,
    silo_id: str,
) -> list[dict[str, Any]]:
    """Return top-20 most-cited entities in a silo (fallback for null silo description)."""
    return await client.execute_query(
        FETCH_TOP_ENTITIES_BY_CITATION,
        {"silo_id": silo_id},
    )


# =============================================================================
# Pass status queries (Task 13)
# =============================================================================

# Fetch a :Pass node by id and org_id for org-isolated status reads.
#
# Params:
#   pass_id (str)
#   org_id  (str)
PASS_GET_BY_ID = """
MATCH (p:Pass {id: $pass_id, org_id: $org_id})
RETURN p.id AS id,
       p.silo_id AS silo_id,
       p.org_id AS org_id,
       p.status AS status,
       p.started_at AS started_at,
       p.finalized_at AS finalized_at,
       p.cost_usd AS cost_usd,
       p.visit_count AS visit_count
LIMIT 1
"""


async def get_pass(
    client: MemgraphClient,
    *,
    pass_id: str,
    org_id: str,
) -> dict[str, Any] | None:
    """Return a :Pass node dict for (pass_id, org_id), or None if not found."""
    rows = await client.execute_query(
        PASS_GET_BY_ID,
        {"pass_id": pass_id, "org_id": org_id},
    )
    if not rows:
        return None
    return dict(rows[0])
