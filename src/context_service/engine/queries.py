"""Parameterized Cypher queries for the hypergraph engine.

All queries use $parameters (never string interpolation) to prevent injection.
All queries include silo_id filtering for storage isolation (Node/Edge),
and org_id filtering for Silo ownership queries.

TIMESTAMP CONVENTION: all created_at/updated_at/last_accessed_at fields are
stored as epoch-MICROSECONDS integers via Cypher timestamp() (Memgraph's
timestamp() returns µs, not ms). The sweep query (SWEEP_ORPHAN_MEMORIES)
compares against timestamp() arithmetic — writing localDateTime() would
produce incompatible values and break the sweep threshold.
_parse_dt() in memgraph_store.py handles epoch-µs integers and native datetimes.

CITE v2 label scheme (5 nodes, 6 edges):
  :Memory    — raw observations (was: Document, Passage, Utterance, Event, Observation)
  :Claim     — evidence-backed assertions written by agents
  :Fact      — SAGE-promoted claims (system-created)
  :Belief    — SAGE-synthesized (system-created, agent-accepted)
  :Commitment — agent decisions
Content-union reads use content_union_predicate() from context_service.db.schema.
All retrieval-facing reads filter AND n.committed = true per O-75.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from primitives.eag.queries.silo import (
    CREATE_SILO as CREATE_SILO,
)
from primitives.eag.queries.silo import (
    DELETE_SILO as DELETE_SILO,
)
from primitives.eag.queries.silo import (
    GET_SILO as GET_SILO,
)
from primitives.eag.queries.silo import (
    LIST_SILOS as LIST_SILOS,
)
from primitives.eag.queries.silo import (
    RESET_SILO as RESET_SILO,
)
from primitives.eag.queries.silo import (
    UPDATE_SILO as UPDATE_SILO,
)
from primitives.schema import IntelligenceLabel, WisdomLabel

from context_service.db.schema import (
    EDGE_ABOUT,
    EDGE_DERIVED_FROM,
    EDGE_SUPERSEDES,
    LABEL_CLAIM,
    LABEL_COMMITMENT,
    LABEL_MEMORY,
    cite_union_predicate,
    content_union_predicate,
)

_LABEL_REASONING_CHAIN = IntelligenceLabel.REASONING_CHAIN  # "ReasoningChain"
_LABEL_COMMITMENT = WisdomLabel.COMMITMENT  # "Commitment"

# --- Node Queries ---
# NOTE: CREATE_NODE / UPSERT_NODE_SINGLE_RTT / BATCH_UPSERT_NODES are ingest-time
# write queries. They are label-specific because the engine layer currently
# defaults to :Document for single-node upserts. These are NOT retrieval-facing
# and do NOT need the committed filter.

CREATE_NODE = f"""
CREATE (n:{LABEL_MEMORY} {{
    id: $id,
    type: $type,
    content: $content,
    properties: $properties,
    silo_id: $silo_id,
    source_uri: $source_uri,
    content_hash: $content_hash,
    stale: $stale,
    extraction_status: $extraction_status,
    version: 1,
    created_at: timestamp(),
    updated_at: timestamp(),
    last_accessed_at: null,
    valid_from: $valid_from,
    valid_to: null,
    supersedes_id: null,
    committed: false,
    ingest_class: $ingest_class,
    content_class: $content_class,
    last_reset_at: timestamp(),
    reclassified_at: null
}})
RETURN n
"""

# Retrieval read — union over all content labels, committed filter per O-75.
# labels(n) is returned explicitly so _node_from_record can populate the
# label field; neo4j's .data() flattens Node values to property dicts only.
GET_NODE_RETRIEVAL = f"""
MATCH (n)
WHERE {content_union_predicate("n")}
  AND n.id = $id
  AND n.silo_id = $silo_id
  AND n.committed = true
  AND n.tombstoned_at IS NULL
RETURN n, labels(n) AS _labels
"""

# Internal read (ingest / maintenance) — no committed filter.
GET_NODE_INTERNAL = f"""
MATCH (n)
WHERE {content_union_predicate("n")}
  AND n.id = $id
  AND n.silo_id = $silo_id
RETURN n, labels(n) AS _labels
"""

BATCH_GET_NODES = f"""
MATCH (n)
WHERE {content_union_predicate("n")}
  AND n.id IN $ids
  AND n.silo_id = $silo_id
  AND n.committed = true
RETURN n, labels(n) AS _labels
"""

UPDATE_NODE_VERSIONED = f"""
MATCH (n)
WHERE {content_union_predicate("n")}
  AND n.id = $id
  AND n.silo_id = $silo_id
  AND n.version = $expected_version
SET n.content = $content,
    n.type = $type,
    n.properties = $properties,
    n.silo_id = $silo_id,
    n.source_uri = $source_uri,
    n.content_hash = $content_hash,
    n.stale = $stale,
    n.extraction_status = $extraction_status,
    n.version = $expected_version + 1,
    n.updated_at = timestamp()
RETURN n
"""

# Single-RTT upsert targets :Memory (primary content node at ingest).
# This constant is retained for legacy single-node upserts via MemgraphStore.
# Returns one row: action in {"created","noop","version","stale"}, stored_version, new_node_id.
UPSERT_NODE_SINGLE_RTT = f"""
MERGE (n:{LABEL_MEMORY} {{id: $id, silo_id: $silo_id}})
ON CREATE SET
    n.type = $type,
    n.content = $content,
    n.properties = $properties,
    n.source_uri = $source_uri,
    n.content_hash = $content_hash,
    n.stale = $stale,
    n.extraction_status = $extraction_status,
    n.version = 1,
    n.created_at = timestamp(),
    n.updated_at = timestamp(),
    n.last_accessed_at = NULL,
    n.valid_from = $valid_from,
    n.valid_to = NULL,
    n.supersedes_id = NULL,
    n.committed = false,
    n.ingest_class = $ingest_class,
    n.content_class = $content_class,
    n.last_reset_at = timestamp(),
    n.reclassified_at = NULL,
    n._upsert_action = 'created'
ON MATCH SET n._upsert_action = CASE
    WHEN n.version <> $expected_version THEN 'stale'
    WHEN n.content_hash IS NOT NULL
         AND $content_hash IS NOT NULL
         AND n.content_hash = $content_hash THEN 'noop'
    ELSE 'version'
END
WITH n, n._upsert_action AS action, n.version AS stored_version
FOREACH (_ IN CASE WHEN action = 'version' AND n.valid_to IS NULL THEN [1] ELSE [] END |
    SET n.valid_to = $valid_from
)
WITH n, action, stored_version
FOREACH (_ IN CASE WHEN action = 'version' THEN [1] ELSE [] END |
    CREATE (v:{LABEL_MEMORY} {{
        id: $new_id,
        type: $type,
        content: $content,
        properties: $properties,
        silo_id: $silo_id,
        source_uri: $source_uri,
        content_hash: $content_hash,
        stale: false,
        extraction_status: $extraction_status,
        version: stored_version + 1,
        created_at: timestamp(),
        updated_at: timestamp(),
        last_accessed_at: NULL,
        valid_from: $valid_from,
        valid_to: NULL,
        supersedes_id: $id,
        committed: false,
        ingest_class: coalesce(n.ingest_class, $ingest_class),
        content_class: coalesce(n.content_class, $content_class),
        last_reset_at: timestamp(),
        reclassified_at: NULL
    }})
    CREATE (v)-[r:SUPERSEDES {{source: 'version_bump', reason: 'author_update'}}]->(n)
)
REMOVE n._upsert_action
RETURN action,
       stored_version,
       CASE WHEN action = 'version' THEN $new_id ELSE NULL END AS new_node_id
"""

BATCH_UPSERT_NODES = f"""
UNWIND $rows AS r
MERGE (n:{LABEL_MEMORY} {{id: r.id, silo_id: r.silo_id}})
ON CREATE SET
    n.type = r.type,
    n.content = r.content,
    n.properties = r.properties,
    n.source_uri = r.source_uri,
    n.content_hash = r.content_hash,
    n.stale = r.stale,
    n.extraction_status = r.extraction_status,
    n.version = 1,
    n.created_at = timestamp(),
    n.updated_at = timestamp(),
    n.last_accessed_at = NULL,
    n.valid_from = r.valid_from,
    n.valid_to = NULL,
    n.supersedes_id = NULL,
    n.committed = false,
    n.ingest_class = r.ingest_class,
    n.content_class = r.content_class,
    n.last_reset_at = timestamp(),
    n.reclassified_at = NULL,
    n._upsert_action = 'created'
ON MATCH SET n._upsert_action = CASE
    WHEN n.version <> r.expected_version THEN 'stale'
    WHEN n.content_hash IS NOT NULL
         AND r.content_hash IS NOT NULL
         AND n.content_hash = r.content_hash THEN 'noop'
    ELSE 'version'
END
WITH r, n, n._upsert_action AS action, n.version AS stored_version
FOREACH (_ IN CASE WHEN action = 'version' AND n.valid_to IS NULL THEN [1] ELSE [] END |
    SET n.valid_to = r.valid_from
)
WITH r, n, action, stored_version
FOREACH (_ IN CASE WHEN action = 'version' THEN [1] ELSE [] END |
    CREATE (v:{LABEL_MEMORY} {{
        id: r.new_id,
        type: r.type,
        content: r.content,
        properties: r.properties,
        silo_id: r.silo_id,
        source_uri: r.source_uri,
        content_hash: r.content_hash,
        stale: false,
        extraction_status: r.extraction_status,
        version: stored_version + 1,
        created_at: timestamp(),
        updated_at: timestamp(),
        last_accessed_at: NULL,
        valid_from: r.valid_from,
        valid_to: NULL,
        supersedes_id: r.id,
        committed: false,
        ingest_class: coalesce(n.ingest_class, r.ingest_class),
        content_class: coalesce(n.content_class, r.content_class),
        last_reset_at: timestamp(),
        reclassified_at: NULL
    }})
    CREATE (v)-[r2:SUPERSEDES {{source: 'version_bump', reason: 'author_update'}}]->(n)
)
REMOVE n._upsert_action
RETURN r.id AS input_id,
       action,
       stored_version,
       CASE WHEN action = 'version' THEN r.new_id ELSE NULL END AS new_node_id
"""

# Binary edge upsert — endpoints may be any CITE node type.
BATCH_UPSERT_BINARY_EDGES = f"""
UNWIND $rows AS r
MATCH (a) WHERE {cite_union_predicate("a")} AND a.id = r.source_id AND a.silo_id = r.silo_id
MATCH (b) WHERE {cite_union_predicate("b")} AND b.id = r.target_id AND b.silo_id = r.silo_id
MERGE (a)-[e:EDGE {{id: r.id, silo_id: r.silo_id}}]->(b)
ON CREATE SET
    e.type = r.type,
    e.properties = r.properties,
    e.created_at = timestamp()
RETURN r.id AS input_id, e.id AS edge_id
"""

CREATE_VERSION = f"""
CREATE (n:{LABEL_MEMORY} {{
    id: $new_id,
    type: $type,
    content: $content,
    properties: $properties,
    silo_id: $silo_id,
    source_uri: $source_uri,
    content_hash: $content_hash,
    stale: false,
    extraction_status: $extraction_status,
    version: $new_version,
    created_at: timestamp(),
    updated_at: timestamp(),
    last_accessed_at: null,
    valid_from: $valid_from,
    valid_to: null,
    supersedes_id: $old_id,
    committed: false,
    ingest_class: $ingest_class,
    content_class: $content_class,
    last_reset_at: timestamp(),
    reclassified_at: null
}})
WITH n
MATCH (old:{LABEL_MEMORY} {{id: $old_id, silo_id: $silo_id}})
WHERE old.valid_to IS NULL
SET old.valid_to = $valid_from
CREATE (n)-[:SUPERSEDES {{reason: $reason}}]->(old)
RETURN n
"""

# Supersession chain pointers for O(1) head resolution.
# Recommended indexes for pointer lookups (run once per database):
#   CREATE INDEX ON :Node(tail_id);
#   CREATE INDEX ON :Node(head_id);
# Without these indexes, the O(1) claim for RESOLVE_CURRENT_HEAD is misleading.

# Cycle detection: check if new_node is reachable from target via SUPERSEDES.
# Used to prevent content-hash dedup from creating cycles when the deduped node
# is already downstream in the supersession chain being extended.
CHECK_SUPERSESSION_CYCLE = f"""
MATCH (target) WHERE {content_union_predicate("target")}
  AND target.id = $target_id AND target.silo_id = $silo_id
OPTIONAL MATCH path = (target)-[:SUPERSEDES*1..20]->(candidate)
WHERE {content_union_predicate("candidate")} AND candidate.id = $new_id
RETURN path IS NOT NULL AS would_cycle
"""

# Cross-node SUPERSEDES for Custodian-detected semantic supersession.
# Sets tail_id on new node (if not already set), head_id on tail node for O(1) chain lookups.
# If new node already has tail_id (multi-supersession), first chain wins to avoid inconsistent state.
CREATE_CROSS_NODE_SUPERSEDES = f"""
MATCH (new) WHERE {content_union_predicate("new")} AND new.id = $from_id AND new.silo_id = $silo_id
MATCH (old) WHERE {content_union_predicate("old")} AND old.id = $to_id AND old.silo_id = $silo_id AND new <> old
MERGE (new)-[r:SUPERSEDES {{source: $source, reason: $reason}}]->(old)
ON CREATE SET r.created_at = $valid_from
WITH old, new, r
// Set valid_to on old if not already set
FOREACH (_ IN CASE WHEN old.valid_to IS NULL THEN [1] ELSE [] END |
  SET old.valid_to = $valid_from
)
WITH old, new
// Derive tail_id: old's tail_id if it exists (old was head of a chain), else old is the tail
WITH old, new, COALESCE(old.tail_id, old.id) AS derived_tail_id
// Only set tail_id if not already set (first supersession defines chain)
FOREACH (_ IN CASE WHEN new.tail_id IS NULL THEN [1] ELSE [] END |
  SET new.tail_id = derived_tail_id
)
// Use the effective tail (existing or newly set)
WITH new, COALESCE(new.tail_id, derived_tail_id) AS tail_id
// Update tail's head_id to point to new head
MATCH (tail) WHERE {content_union_predicate("tail")} AND tail.id = tail_id AND tail.silo_id = $silo_id
SET tail.head_id = new.id
RETURN count(*) AS created
"""

# Batch version-check with O(1) pointer fast-path for live-tip lookups.
# Falls back to chain walk for historical as_of or missing pointers.
# Uses single-query COALESCE pattern to avoid UNION fallback gaps.
FILTER_SUPERSEDED_AT = f"""
UNWIND $ids AS input_id
MATCH (input) WHERE {content_union_predicate("input")} AND input.id = input_id AND input.silo_id = $silo_id

// Fast path: try pointer lookup first
WITH input_id, input, COALESCE(input.tail_id, input.id) AS tail_id
OPTIONAL MATCH (tail) WHERE {content_union_predicate("tail")} AND tail.id = tail_id AND tail.silo_id = $silo_id
WITH input_id, input, COALESCE(tail.head_id, input.id) AS pointer_head_id

// Check if pointer head is valid at as_of
OPTIONAL MATCH (pointer_head) WHERE {content_union_predicate("pointer_head")}
  AND pointer_head.id = pointer_head_id AND pointer_head.silo_id = $silo_id
  AND coalesce(pointer_head.valid_from, pointer_head.created_at) <= $as_of
  AND (pointer_head.valid_to IS NULL OR pointer_head.valid_to > $as_of)

// If fast path succeeded, use it; otherwise chain walk
WITH input_id, input, pointer_head
CALL {{
  WITH input_id, input, pointer_head
  WITH input_id, pointer_head WHERE pointer_head IS NOT NULL
  RETURN pointer_head.id AS valid_id
  UNION
  WITH input_id, input, pointer_head
  WITH input_id, input WHERE pointer_head IS NULL
  OPTIONAL MATCH path = (tip)-[:SUPERSEDES*0..]->(input)
  WHERE {content_union_predicate("tip")}
    AND tip.silo_id = $silo_id
    AND coalesce(tip.valid_from, tip.created_at) <= $as_of
    AND (tip.valid_to IS NULL OR tip.valid_to > $as_of)
  WITH input_id, tip WHERE tip IS NOT NULL
  ORDER BY coalesce(tip.valid_from, tip.created_at) DESC
  WITH input_id, collect(tip)[0] AS chosen
  RETURN chosen.id AS valid_id
}}
RETURN input_id, valid_id
"""

# Fast-path O(1) lookup for current (live) chain head via pointers.
# Returns head_id for any node in a supersession chain, verifying the head
# is still valid (not superseded). Returns null if node doesn't exist or
# if the pointer head has been superseded (caller should fall back to chain walk).
RESOLVE_CURRENT_HEAD = f"""
MATCH (input) WHERE {content_union_predicate("input")} AND input.id = $id AND input.silo_id = $silo_id
// Derive tail: input's tail_id if set, else input might be the tail itself
WITH input, COALESCE(input.tail_id, input.id) AS tail_id
OPTIONAL MATCH (tail) WHERE {content_union_predicate("tail")} AND tail.id = tail_id AND tail.silo_id = $silo_id
WITH input, COALESCE(tail.head_id, input.id) AS pointer_head_id
// Verify head is still valid (not superseded)
OPTIONAL MATCH (head) WHERE {content_union_predicate("head")}
  AND head.id = pointer_head_id AND head.silo_id = $silo_id
  AND head.valid_to IS NULL
RETURN head.id AS head_id
"""

# O-14 + CLAUDE.md invariant: :Finding nodes are filtered at retrieval
# unless the caller is explicitly requesting drafts. A finding passes
# when either (a) it is extraction-sourced or (b) its status is
# 'published'. Non-:Finding nodes always pass — this fragment composes
# into Cypher via ``WHERE ... AND ({FILTER_FINDING_STATUS.format(var="n")})``.
# Callers that legitimately need drafts (custodian tooling, admin read
# paths) simply omit the fragment and document the escape hatch inline.
FILTER_FINDING_STATUS = (
    "(NOT {var}:Finding OR {var}.source = 'extraction' OR {var}.status = 'published')"
)


# Bi-temporal read — internal, no committed filter (used by version audits).
GET_NODE_AS_OF = f"""
MATCH (n) WHERE {content_union_predicate("n")} AND n.silo_id = $silo_id
  AND (n.id = $id OR n.supersedes_id = $id)
WITH n
WHERE coalesce(n.valid_from, n.created_at) <= $as_of
  AND (n.valid_to IS NULL OR n.valid_to > $as_of)
RETURN n
UNION
MATCH (n)-[:SUPERSEDES*]->(root)
WHERE {content_union_predicate("n")} AND n.silo_id = $silo_id AND root.id = $id
  AND coalesce(n.valid_from, n.created_at) <= $as_of
  AND (n.valid_to IS NULL OR n.valid_to > $as_of)
RETURN n
LIMIT 1
"""

GET_NODE_VERSION_CHAIN = f"""
MATCH (tip) WHERE {content_union_predicate("tip")} AND tip.id = $id AND tip.silo_id = $silo_id
  AND tip.valid_to IS NULL
OPTIONAL MATCH path = (tip)-[:SUPERSEDES*0..]->(old)
RETURN old ORDER BY old.created_at DESC
"""

UPDATE_EXTRACTION_STATUS = f"""
MATCH (n) WHERE {content_union_predicate("n")}
  AND n.id = $id AND n.silo_id = $silo_id
SET n.extraction_status = $extraction_status,
    n.updated_at = timestamp()
RETURN n
"""

SILO_EXTRACTION_STATUS = f"""
MATCH (n) WHERE {content_union_predicate("n")} AND n.silo_id = $silo_id
RETURN n.extraction_status AS status, count(n) AS count
"""

DELETE_NODE = f"""
MATCH (n) WHERE {content_union_predicate("n")}
  AND n.id = $id AND n.silo_id = $silo_id
DETACH DELETE n
RETURN count(n) AS deleted
"""

# Retrieval-facing list — committed filter per O-75.
FIND_NODES = f"""
MATCH (n) WHERE {content_union_predicate("n")}
  AND n.silo_id = $silo_id
  AND n.committed = true
  AND ($type IS NULL OR n.type = $type)
RETURN n
ORDER BY n.created_at DESC
SKIP $offset
LIMIT $limit
"""

COUNT_NODES = f"""
MATCH (n) WHERE {content_union_predicate("n")} AND n.silo_id = $silo_id AND n.committed = true
RETURN count(n) AS count
"""

COUNT_EDGES_IN_SILO = f"""
MATCH (a) WHERE {content_union_predicate("a")} AND a.silo_id = $silo_id
MATCH (a)-[r]->(b) WHERE {content_union_predicate("b")} AND b.silo_id = $silo_id
RETURN count(r) AS count
"""

SUM_CONTENT_BYTES_IN_SILO = f"""
MATCH (n) WHERE {content_union_predicate("n")} AND n.silo_id = $silo_id AND n.committed = true
RETURN sum(size(coalesce(n.raw_payload, n.text, n.content, ''))) AS bytes
"""

# --- Binary Edge Queries ---

CREATE_BINARY_EDGE = f"""
MATCH (a) WHERE {cite_union_predicate("a")} AND a.id = $source_id AND a.silo_id = $silo_id
MATCH (b) WHERE {cite_union_predicate("b")} AND b.id = $target_id AND b.silo_id = $silo_id
CREATE (a)-[e:EDGE {{
    id: $id,
    type: $type,
    properties: $properties,
    silo_id: $silo_id,
    created_at: timestamp()
}}]->(b)
RETURN e
"""

GET_BINARY_EDGES_OUTGOING = f"""
MATCH (a) WHERE {cite_union_predicate("a")} AND a.id = $node_id AND a.silo_id = $silo_id
MATCH (a)-[e:EDGE]->(b) WHERE {cite_union_predicate("b")}
  AND b.silo_id = $silo_id
  AND ($type IS NULL OR e.type = $type)
RETURN e, b
ORDER BY e.created_at DESC
SKIP $offset
LIMIT $limit
"""

GET_BINARY_EDGES_INCOMING = f"""
MATCH (a) WHERE {cite_union_predicate("a")} AND a.id = $node_id AND a.silo_id = $silo_id
MATCH (a)<-[e:EDGE]-(b) WHERE {cite_union_predicate("b")}
  AND b.silo_id = $silo_id
  AND ($type IS NULL OR e.type = $type)
RETURN e, b
ORDER BY e.created_at DESC
SKIP $offset
LIMIT $limit
"""

GET_BINARY_EDGES_BOTH = f"""
MATCH (a) WHERE {cite_union_predicate("a")} AND a.id = $node_id AND a.silo_id = $silo_id
MATCH (a)-[e:EDGE]-(b) WHERE {cite_union_predicate("b")}
  AND b.silo_id = $silo_id
  AND ($type IS NULL OR e.type = $type)
RETURN e, b
ORDER BY e.created_at DESC
SKIP $offset
LIMIT $limit
"""

# DEPRECATED (CITE v2): Entity graph queries relied on EXTRACTED_FROM / MENTIONS edges
# and :Entity nodes — all removed in v2. The entity pivot is replaced by ABOUT edges
# and the Claim-centric knowledge model.
# TODO: remove stub after all callers are updated to v2 APIs
GET_ENTITY_GRAPH_NEIGHBORS = "RETURN null LIMIT 0"

DELETE_BINARY_EDGE = """
MATCH ()-[e:EDGE {id: $id, silo_id: $silo_id}]->()
DELETE e
RETURN count(e) AS deleted
"""

# --- HyperEdge Queries ---

CREATE_HYPEREDGE_NODE = """
CREATE (he:HyperEdge {
    id: $id,
    type: $type,
    properties: $properties,
    silo_id: $silo_id,
    created_at: timestamp()
})
RETURN he
"""

CREATE_PARTICIPANT = f"""
MATCH (he:HyperEdge {{id: $edge_id, silo_id: $silo_id}})
MATCH (n) WHERE {content_union_predicate("n")} AND n.id = $node_id AND n.silo_id = $silo_id
CREATE (n)<-[:PARTICIPANT {{role: $role}}]-(he)
"""

DELETE_PARTICIPANTS = """
MATCH (he:HyperEdge {id: $edge_id, silo_id: $silo_id})-[r:PARTICIPANT]->()
DELETE r
"""

GET_HYPEREDGE = f"""
MATCH (he:HyperEdge {{id: $id, silo_id: $silo_id}})
OPTIONAL MATCH (he)-[p:PARTICIPANT]->(n) WHERE {content_union_predicate("n")}
RETURN he, collect({{node_id: n.id, role: p.role}}) AS participants
"""

GET_HYPEREDGES_FOR_NODE = f"""
MATCH (n) WHERE {content_union_predicate("n")} AND n.id = $node_id AND n.silo_id = $silo_id
MATCH (n)<-[p:PARTICIPANT]-(he:HyperEdge)
WHERE ($type IS NULL OR he.type = $type)
  AND ($role IS NULL OR p.role = $role)
WITH he
ORDER BY he.created_at DESC
SKIP $offset
LIMIT $limit
OPTIONAL MATCH (he)-[p2:PARTICIPANT]->(n2) WHERE {content_union_predicate("n2")}
RETURN he, collect({{node_id: n2.id, role: p2.role}}) AS participants
"""

DELETE_HYPEREDGE = """
MATCH (he:HyperEdge {id: $id, silo_id: $silo_id})
DETACH DELETE he
RETURN count(he) AS deleted
"""

UPSERT_HYPEREDGE_WITH_PARTICIPANTS = f"""
MERGE (he:HyperEdge {{id: $id, silo_id: $silo_id}})
ON CREATE SET
    he.type = $type,
    he.properties = $properties,
    he.created_at = timestamp()
ON MATCH SET
    he.type = $type,
    he.properties = $properties
WITH he
OPTIONAL MATCH (he)-[old:PARTICIPANT]->()
DELETE old
WITH he
UNWIND $participants AS p
MATCH (n) WHERE {content_union_predicate("n")} AND n.id = p.node_id AND n.silo_id = $silo_id
CREATE (n)<-[:PARTICIPANT {{role: p.role}}]-(he)
"""

# --- Graph Traversal Queries ---

# NEIGHBORHOOD is retrieval-facing — committed filter on both start and other.
# Walks typed CITE v2 edges (DERIVED_FROM, SYNTHESIZED_FROM, SUPPORTS, CONTRADICTS,
# SUPERSEDES, ABOUT) plus generic EDGE and PARTICIPANT.
NEIGHBORHOOD = f"""
MATCH (start) WHERE {content_union_predicate("start")}
  AND start.id = $id AND start.silo_id = $silo_id AND start.committed = true
CALL {{
    WITH start
    MATCH path = (start)-[:{EDGE_DERIVED_FROM}|{EDGE_ABOUT}|{EDGE_SUPERSEDES}|EDGE|PARTICIPANT*1..%d]-(other)
    WHERE {content_union_predicate("other")}
      AND other.silo_id = $silo_id
      AND other.id <> start.id
      AND other.committed = true
    RETURN other, length(path) AS dist
    LIMIT $max_nodes
}}
RETURN DISTINCT other, min(dist) AS distance
ORDER BY distance
"""

SHARED_PARTICIPATION = f"""
MATCH (a) WHERE {content_union_predicate("a")} AND a.id = $id AND a.silo_id = $silo_id
MATCH (a)<-[:PARTICIPANT]-(he:HyperEdge)-[:PARTICIPANT]->(b) WHERE {content_union_predicate("b")}
  AND b.id <> a.id AND b.silo_id = $silo_id
WITH b, count(DISTINCT he) AS shared_count
WHERE shared_count >= $threshold
RETURN b, shared_count
ORDER BY shared_count DESC
LIMIT $limit
"""

# SHORTEST_PATH is retrieval-facing — committed filter on both endpoints.
SHORTEST_PATH = f"""
MATCH (a) WHERE {content_union_predicate("a")} AND a.id = $source_id AND a.silo_id = $silo_id AND a.committed = true
MATCH (b) WHERE {content_union_predicate("b")} AND b.id = $target_id AND b.silo_id = $silo_id AND b.committed = true
MATCH path = shortestPath((a)-[:{EDGE_DERIVED_FROM}|{EDGE_ABOUT}|{EDGE_SUPERSEDES}|EDGE|PARTICIPANT*..%d]-(b))
WHERE ALL(n IN nodes(path) WHERE ({content_union_predicate("n")} AND n.silo_id = $silo_id) OR n:HyperEdge)
RETURN nodes(path) AS path_nodes
"""

# --- Export Queries (Visualization) ---

EXPORT_ALL_NODES = f"""
MATCH (n) WHERE {content_union_predicate("n")} AND n.silo_id = $silo_id AND n.committed = true
RETURN n
ORDER BY n.created_at
SKIP $offset
LIMIT $limit
"""

EXPORT_ALL_BINARY_EDGES = f"""
MATCH (a) WHERE {content_union_predicate("a")} AND a.silo_id = $silo_id
MATCH (a)-[e:EDGE]->(b) WHERE {content_union_predicate("b")} AND b.silo_id = $silo_id
RETURN e.id AS id, e.type AS type, e.properties AS properties,
       e.silo_id AS silo_id, e.created_at AS created_at,
       a.id AS source_id, b.id AS target_id
ORDER BY e.created_at
SKIP $offset
LIMIT $limit
"""

EXPORT_ALL_HYPEREDGES = f"""
MATCH (he:HyperEdge {{silo_id: $silo_id}})
OPTIONAL MATCH (he)-[p:PARTICIPANT]->(n) WHERE {content_union_predicate("n")}
RETURN he, collect({{node_id: n.id, role: p.role}}) AS participants
ORDER BY he.created_at
SKIP $offset
LIMIT $limit
"""

# --- Entity Export Queries ---
# DEPRECATED (CITE v2): :Entity nodes, EXTRACTED_FROM edges, and entity-to-entity
# relationships are removed in v2. The entity pivot is replaced by the Claim layer
# and ABOUT edges. These queries are kept as dead code for migration reference.
# EXPORT_ALL_ENTITIES = ...         # removed
# EXPORT_ENTITY_RELATIONSHIPS = ... # removed
# EXPORT_EXTRACTED_FROM = ...       # removed

# --- Index Queries ---
# Phase-3: engine layer owns HyperEdge, Silo, and EDGE indexes.
# Document/Passage/Claim/Entity indexes are owned by context_service.db.indexes
# and applied via MemgraphClient.ensure_indexes.
# Exception: tail_id and head_id are :Node indexes retained here because they
# support chain pointer lookups (supersession linked-list traversal), which is
# an engine-layer concern independent of node type.
CREATE_TAIL_ID_INDEX = "CREATE INDEX ON :Node(tail_id);"
CREATE_HEAD_ID_INDEX = "CREATE INDEX ON :Node(head_id);"

INDEX_QUERIES = [
    "CREATE INDEX ON :HyperEdge(id);",
    "CREATE INDEX ON :HyperEdge(silo_id);",
    "CREATE INDEX ON :HyperEdge(type);",
    "CREATE INDEX ON :Silo(id);",
    "CREATE INDEX ON :Silo(org_id);",
    "CREATE INDEX ON :EDGE(type);",
    "CREATE INDEX ON :EDGE(silo_id);",
    CREATE_TAIL_ID_INDEX,
    CREATE_HEAD_ID_INDEX,
]

# --- Sync Queries ---

FIND_NODE_BY_SOURCE_URI = f"""
MATCH (n) WHERE {content_union_predicate("n")}
  AND n.silo_id = $silo_id AND n.source_uri = $source_uri
  AND n.committed = true
RETURN n
"""

LIST_NODES_WITH_URI_BY_SILO = f"""
MATCH (n) WHERE {content_union_predicate("n")} AND n.silo_id = $silo_id
  AND n.source_uri IS NOT NULL
RETURN n.id AS id, n.source_uri AS source_uri, n.content_hash AS content_hash,
       n.version AS version, n.stale AS stale
"""

# NOTE: TOUCH_NODE_ACCESSED and BATCH_TOUCH_NODES_ACCESSED are retrieval-side
# (fired on read-cache hit), so they add the committed filter to ensure we
# do not accidentally touch uncommitted ghost nodes.
TOUCH_NODE_ACCESSED = f"""
MATCH (n) WHERE {content_union_predicate("n")}
  AND n.id = $id AND n.silo_id = $silo_id AND n.committed = true
SET n.last_accessed_at = timestamp()
RETURN n.id AS id
"""

BATCH_TOUCH_NODES_ACCESSED = f"""
UNWIND $ids AS nid
MATCH (n) WHERE {content_union_predicate("n")}
  AND n.id = nid AND n.silo_id = $silo_id AND n.committed = true
SET n.last_accessed_at = timestamp()
RETURN count(n) AS touched
"""

# NOTE: MARK_NODE_STALE is triggered from the retrieval path (staleness decay
# on read), so committed filter applies — we should not mark an uncommitted
# ghost node as stale.
MARK_NODE_STALE = f"""
MATCH (n) WHERE {content_union_predicate("n")}
  AND n.id = $id AND n.silo_id = $silo_id
  AND n.version = $expected_version AND n.committed = true
SET n.stale = true, n.version = $expected_version + 1, n.updated_at = timestamp()
RETURN n
"""

# --- CITE v2 Memory write queries ---
# In v2, Document+Passage two-step collapses to a single :Memory node write.
# Ingest writes :Memory directly; no chunking layer at graph level.

UPSERT_MEMORY_NODE = f"""
MERGE (m:{LABEL_MEMORY} {{id: $doc_id, silo_id: $silo_id}})
SET m.committed = false,
    m.current_version = $next_version,
    m.created_at = timestamp(),
    m.updated_at = timestamp(),
    m += $doc_props
RETURN m.id AS memory_id
"""

# Alias retained for callers that used the old name.
UPSERT_DOCUMENT_AND_PASSAGES = UPSERT_MEMORY_NODE

FLIP_MEMORY_COMMITTED_VERSION_GATED = f"""
MATCH (m:{LABEL_MEMORY} {{id: $doc_id, silo_id: $silo_id, current_version: $claim_version}})
SET m.committed = true
RETURN count(m) AS flipped
"""

# Alias retained for callers that used the old name.
FLIP_DOCUMENT_COMMITTED_VERSION_GATED = FLIP_MEMORY_COMMITTED_VERSION_GATED

RECLASSIFY_MEMORY = f"""
MATCH (m:{LABEL_MEMORY} {{id: $doc_id, silo_id: $silo_id}})
SET m.content_class = coalesce($content_class, m.content_class),
    m.ingest_class = coalesce($ingest_class, m.ingest_class),
    m.reclassified_at = timestamp()
RETURN m.id AS doc_id,
       m.content_class AS content_class,
       m.ingest_class AS ingest_class,
       m.raw_payload AS raw_payload,
       m.raw_payload_truncated AS raw_payload_truncated,
       m.uri AS uri,
       m.mime AS mime,
       m.content_hash AS content_hash
"""

# Alias retained for callers that used the old name.
RECLASSIFY_DOCUMENT = RECLASSIFY_MEMORY

# Tombstone cascade: hard delete :Memory node. In v2 there are no Passage child
# nodes; Claims are independent nodes linked by DERIVED_FROM.
TOMBSTONE_MEMORY = f"""
MATCH (m:{LABEL_MEMORY} {{id: $doc_id, silo_id: $silo_id}})
WITH m, 0 AS deleted_passages, 0 AS deleted_findings
DETACH DELETE m
RETURN 1 AS deleted_docs, deleted_passages, deleted_findings
"""

# Alias retained for callers that used the old name.
TOMBSTONE_DOCUMENT = TOMBSTONE_MEMORY

SWEEP_ORPHAN_MEMORIES = f"""
MATCH (m:{LABEL_MEMORY})
WHERE m.committed = false AND m.created_at < timestamp() - $age_ms
DETACH DELETE m
RETURN count(m) AS deleted_docs
"""

# Alias retained for callers that used the old name.
SWEEP_ORPHAN_DOCUMENTS = SWEEP_ORPHAN_MEMORIES

# --- Inference storage queries (phase-8, spec R16) ---

UPSERT_REASONING_CHAIN = f"""
MERGE (c:{_LABEL_REASONING_CHAIN} {{id: $chain_id}})
ON CREATE SET
    c.silo_id = $silo_id,
    c.tier = $tier,
    c.produced_by_model = $produced_by_model,
    c.produced_by_agent_id = $produced_by_agent_id,
    c.query_context_hash = $query_context_hash,
    c.created_at = $created_at,
    c.steps = $steps,
    c.status = $status,
    c.source = $source,
    c.valid_from = $valid_from,
    c.access_count = 0,
    c.heat_score = 0.0,
    c.committed = false
ON MATCH SET
    c.steps = COALESCE($steps, c.steps),
    c.access_count = c.access_count + 1,
    c.last_accessed_at = datetime()
RETURN c.id AS id, c.committed AS committed
"""

FLIP_CHAIN_COMMITTED = f"""
MATCH (c:{_LABEL_REASONING_CHAIN} {{id: $chain_id, silo_id: $silo_id}})
WHERE c.committed = false
SET c.committed = true
RETURN count(c) AS flipped
"""

UPSERT_COMMITMENT = f"""
MERGE (c:{LABEL_COMMITMENT} {{id: $commitment_id}})
ON CREATE SET
    c.silo_id = $silo_id,
    c.subject = $subject,
    c.predicate = $predicate,
    c.object = $object,
    c.scope = $scope,
    c.produced_by_agent_id = $produced_by_agent_id,
    c.status = $status,
    c.source = $source,
    c.confidence_tier = $confidence_tier,
    c.valid_from = $valid_from,
    c.valid_to = $valid_to,
    c.rationale_chain_id = $rationale_chain_id,
    c.predicate_version = $predicate_version,
    c.label_tier = $label_tier,
    c.distinct_agent_count = 1,
    c.fit_signal_base = 0.5,
    c.committed = false
ON MATCH SET
    c.distinct_agent_count = c.distinct_agent_count + 1
RETURN c.id AS id, c.committed AS committed
"""

FLIP_COMMITMENT_COMMITTED = f"""
MATCH (c:{LABEL_COMMITMENT} {{id: $commitment_id, silo_id: $silo_id}})
WHERE c.committed = false
SET c.committed = true
RETURN count(c) AS flipped
"""

CREATE_CRYSTALLIZED_INTO_EDGE = f"""
MATCH (chain:{_LABEL_REASONING_CHAIN} {{id: $chain_id}})
MATCH (target {{id: $target_id}})
WHERE (target:{LABEL_CLAIM} OR target:Finding OR target:{_LABEL_COMMITMENT})
  AND ({FILTER_FINDING_STATUS.format(var="target")})
MERGE (chain)-[:CRYSTALLIZED_INTO]->(target)
"""

CREATE_DERIVED_FROM_EVIDENCE_EDGE = f"""
MATCH (chain:{_LABEL_REASONING_CHAIN} {{id: $chain_id}})
MATCH (evidence {{id: $evidence_id}})
WHERE (evidence:{LABEL_MEMORY} OR evidence:{LABEL_CLAIM}
      OR evidence:Finding OR evidence:{LABEL_COMMITMENT} OR evidence:{_LABEL_REASONING_CHAIN})
  AND ({FILTER_FINDING_STATUS.format(var="evidence")})
MERGE (chain)-[r:DERIVED_FROM_EVIDENCE]->(evidence)
SET r.rank = $rank, r.relevance_score = $relevance_score
"""

CHECK_CHAIN_DEPTH = f"""
MATCH path = (c:{_LABEL_REASONING_CHAIN} {{id: $chain_id}})-[:DERIVED_FROM_EVIDENCE*1..4]->(target:{_LABEL_REASONING_CHAIN})
WITH length(path) AS depth
WHERE depth > 3
RETURN depth
LIMIT 1
"""

# In v2 :Memory nodes have no Passage children. Fetch Claims derived from a
# Memory node before tombstone — needed to cascade DERIVED_FROM_EVIDENCE walks.
GET_MEMORY_CLAIM_IDS = f"""
MATCH (m:{LABEL_MEMORY} {{id: $doc_id, silo_id: $silo_id}})<-[:{EDGE_DERIVED_FROM}]-(c:{LABEL_CLAIM})
RETURN c.id AS passage_id
"""

# Alias retained for callers that used the old name.
GET_DOCUMENT_PASSAGE_IDS = GET_MEMORY_CLAIM_IDS

# --- Erasure cascade queries (phase-8, P-G) ---

FIND_CHAINS_CITING_NODE = f"""
MATCH (chain:{_LABEL_REASONING_CHAIN})-[r:DERIVED_FROM_EVIDENCE]->(erased {{id: $erased_node_id}})
WHERE chain.silo_id = $silo_id
RETURN chain.id AS chain_id, chain.tier AS tier, r.rank AS rank,
       chain.steps AS steps
"""

FIND_CHAINS_CITING_NODE_RECURSIVE = f"""
MATCH path = (chain:{_LABEL_REASONING_CHAIN})-[:DERIVED_FROM_EVIDENCE*1..5]->(erased {{id: $erased_node_id}})
WHERE chain.silo_id = $silo_id
RETURN DISTINCT chain.id AS chain_id, chain.tier AS tier,
       length(path) AS distance
ORDER BY distance ASC
"""

REDACT_HOT_CHAIN_STEP = f"""
MATCH (chain:{_LABEL_REASONING_CHAIN} {{id: $chain_id, silo_id: $silo_id}})
WHERE chain.tier = 'hot'
SET chain.steps = $redacted_steps,
    chain.redacted_at = datetime(),
    chain.redaction_reason = $reason
RETURN chain.id AS id
"""

RETRACT_CHAIN = f"""
MATCH (chain:{_LABEL_REASONING_CHAIN} {{id: $chain_id, silo_id: $silo_id}})
SET chain.status = 'retracted',
    chain.valid_to = datetime(),
    chain.retraction_reason = 'erasure_cascade',
    chain.steps = null,
    chain.compact_summary = null
RETURN chain.id AS id
"""

# Sentinel for Qdrant commitment vector deletion (not a Cypher query).
DELETE_COMMITMENT_VECTOR = "qdrant_delete"


# ---------------------------------------------------------------------------
# Session trace event node queries (phase-8 P-E, spec R16-8/R16-13)
# ---------------------------------------------------------------------------

UPSERT_RETRIEVAL_EVENT = """
MERGE (e:RetrievalEvent {id: $event_id})
ON CREATE SET
    e.silo_id = $silo_id,
    e.session_id = $session_id,
    e.agent_id = $agent_id,
    e.query = $query,
    e.result_ids = $result_ids,
    e.created_at = datetime()
RETURN e.id AS id
"""

UPSERT_INGEST_EVENT = """
MERGE (e:IngestEvent {id: $event_id})
ON CREATE SET
    e.silo_id = $silo_id,
    e.session_id = $session_id,
    e.agent_id = $agent_id,
    e.document_id = $document_id,
    e.claim_ids = $claim_ids,
    e.created_at = datetime()
RETURN e.id AS id
"""

FIND_SESSION_EVENTS = """
MATCH (e)
WHERE (e:RetrievalEvent OR e:IngestEvent)
  AND e.session_id = $session_id
  AND e.silo_id = $silo_id
RETURN e, labels(e) AS labels
ORDER BY e.created_at ASC
"""

FIND_SESSIONS_WITH_OUTPUT = """
MATCH (e:IngestEvent {silo_id: $silo_id})
WHERE e.created_at > $since
WITH DISTINCT e.session_id AS session_id
MATCH (ie:IngestEvent {session_id: session_id})
WHERE ie.claim_ids IS NOT NULL AND size(ie.claim_ids) > 0
RETURN DISTINCT session_id
LIMIT $limit
"""


# ---------------------------------------------------------------------------
# Compaction queries (P-D)
# ---------------------------------------------------------------------------

FIND_COLD_CANDIDATE_CHAINS = f"""
MATCH (c:{_LABEL_REASONING_CHAIN} {{silo_id: $silo_id}})
WHERE c.tier = 'hot'
  AND (c.last_accessed_at < $threshold_datetime
       OR (c.last_accessed_at IS NULL AND c.created_at < $threshold_datetime))
RETURN c.id AS id, c.access_count AS access_count, c.steps AS steps
ORDER BY c.access_count ASC, c.created_at ASC
LIMIT $limit
"""

CHECK_CHAIN_AUDIT_LINKED = f"""
MATCH (c:{_LABEL_REASONING_CHAIN} {{id: $chain_id}})
OPTIONAL MATCH (c)<-[:PROMOTED_FROM]-(f1:Finding) WHERE {FILTER_FINDING_STATUS.format(var="f1")}
OPTIONAL MATCH (c)<-[:DERIVED_FROM_EVIDENCE]-(rc:{_LABEL_REASONING_CHAIN})
OPTIONAL MATCH (c)-[:CRYSTALLIZED_INTO]->(f2:Finding) WHERE {FILTER_FINDING_STATUS.format(var="f2")}
WITH c, f1, rc, f2
WHERE f1 IS NOT NULL OR rc IS NOT NULL OR f2 IS NOT NULL
RETURN true AS linked
"""

COMPACT_CHAIN = f"""
MATCH (c:{_LABEL_REASONING_CHAIN} {{id: $chain_id, silo_id: $silo_id}})
SET c.tier = 'cold',
    c.compact_summary = $compact_summary,
    c.compacted_at = datetime(),
    c.compacted_by_model = $compacted_by_model,
    c.steps = null
RETURN c.id AS id
"""

SHED_CHAIN = f"""
MATCH (c:{_LABEL_REASONING_CHAIN} {{id: $chain_id, silo_id: $silo_id}})
SET c.status = 'retracted',
    c.valid_to = datetime(),
    c.retraction_reason = 'shed_on_zero_access',
    c.steps = null
RETURN c.id AS id
"""


# ---------------------------------------------------------------------------
# Consensus promotion queries (P-F)
# ---------------------------------------------------------------------------

CREATE_FINDING_FROM_COMMITMENT = f"""
MATCH (c:{LABEL_COMMITMENT} {{id: $commitment_id, silo_id: $silo_id}})
MERGE (f:Finding {{id: $finding_id, silo_id: $silo_id}})
ON CREATE SET
    f.subject = c.subject,
    f.predicate = c.predicate,
    f.object = c.object,
    f.source = 'custodian_consensus',
    f.status = 'published',
    f.created_at = datetime(),
    f.confidence_tier = 'high',
    f.distinct_agent_count = c.distinct_agent_count
MERGE (c)-[:PROMOTED_TO]->(f)
RETURN f.id AS id
"""

CREATE_PROMOTED_FROM_EDGE = f"""
MATCH (f:Finding {{id: $finding_id}})
MATCH (c:{_LABEL_REASONING_CHAIN} {{id: $chain_id}})
MERGE (f)-[:PROMOTED_FROM]->(c)
SET c.status = 'superseded'
"""

# R-005: batch variant — collapses N per-chain tx.run() calls to one RTT.
BATCH_CREATE_PROMOTED_FROM_EDGES = f"""
MATCH (f:Finding {{id: $finding_id, silo_id: $silo_id}})
UNWIND $chain_ids AS cid
MATCH (c:{_LABEL_REASONING_CHAIN} {{id: cid, silo_id: $silo_id}})
MERGE (f)-[:PROMOTED_FROM]->(c)
SET c.status = 'superseded'
RETURN count(c) AS updated
"""

# ---------------------------------------------------------------------------
# Evidence Accessibility (chain_applicability Layer 3)
# ---------------------------------------------------------------------------

GET_SESSION_ACCESSIBLE_EVIDENCE = f"""
MATCH (n)
WHERE {content_union_predicate("n")}
  AND n.silo_id = $silo_id
  AND n.committed = true
  AND (n.session_id = $session_id
       OR (n)<-[:ACCESSED_BY]-(:Session {{id: $session_id}}))
RETURN n.id AS node_id
"""

MARK_NODE_ACCESSED = f"""
MATCH (n) WHERE {content_union_predicate("n")}
  AND n.id = $node_id AND n.silo_id = $silo_id
MATCH (s:Session {{id: $session_id, silo_id: $silo_id}})
MERGE (n)<-[:ACCESSED_BY {{at: timestamp()}}]-(s)
RETURN n.id AS node_id
"""

ENSURE_SESSION_NODE = """
MERGE (s:Session {id: $session_id, silo_id: $silo_id})
ON CREATE SET s.created_at = timestamp()
"""

GET_SILO_EVIDENCE_NODES = f"""
MATCH (n) WHERE {content_union_predicate("n")}
  AND n.silo_id = $silo_id
  AND n.committed = true
RETURN n.id AS node_id
LIMIT $limit
"""

# Fetch updated_at timestamps for a list of evidence node IDs.
# No silo filter: callers have already verified accessibility via
# get_accessible_evidence(). No committed filter: we want to detect
# modifications even on uncommitted (recently updated) nodes.
GET_EVIDENCE_UPDATED_AT = f"""
MATCH (n) WHERE {content_union_predicate("n")}
  AND n.id IN $ids
RETURN n.id AS id, n.updated_at AS updated_at
"""

# ---------------------------------------------------------------------------
# Stub-retention queries (data lifecycle management)
# ---------------------------------------------------------------------------

# Find interior chain nodes beyond max_length from head.
# Interior nodes are those with at least one SUPERSEDES predecessor (head) and
# at least one SUPERSEDES successor (tail) in the chain. The query matches
# paths from the head to interior nodes and then checks that each interior has
# a successor (tail). Only nodes beyond max_length hops from the head and not
# already stubbed are returned.
#
# Head detection: a chain head has head_id IS NULL (never been superseded itself)
# or head_id = head.id (self-referential pointer). A fresh chain head has no
# pointer set at all, so the IS NULL case must be included.
#
# Path length: p1 is the head-to-interior segment; length(p1) is the number of
# SUPERSEDES hops from head to interior. The full head-through-interior-to-tail
# path length would conflate interior depth with tail distance and produce wrong
# cutoff comparisons.
FIND_STALE_CHAIN_INTERIOR = f"""
MATCH (head)
WHERE {content_union_predicate("head")}
  AND head.silo_id = $silo_id
  AND (head.head_id IS NULL OR head.head_id = head.id)
WITH head
MATCH p1 = (head)-[:SUPERSEDES*]->(interior)
WHERE {content_union_predicate("interior")}
  AND interior.silo_id = $silo_id
  AND interior.stub IS NULL
  AND length(p1) > $max_length
WITH interior
MATCH (interior)-[:SUPERSEDES+]->(tail)
WHERE {content_union_predicate("tail")}
  AND tail.silo_id = $silo_id
  AND NOT (tail)-[:SUPERSEDES]->()
RETURN DISTINCT interior.id AS node_id
LIMIT $batch_size
"""

# Convert a node to a stub: clear content fields but preserve all edges so the
# chain structure and provenance remain intact.
CONVERT_TO_STUB = f"""
MATCH (n)
WHERE {content_union_predicate("n")}
  AND n.id = $id AND n.silo_id = $silo_id
SET n.stub = true,
    n.content = NULL,
    n.content_hash = NULL,
    n.embedding = NULL,
    n.stubbed_at = $stubbed_at,
    n.heat_dirty = true
RETURN n.id AS id
"""
