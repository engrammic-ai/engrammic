"""Intelligence layer: stuck pattern detection and breakthrough tracking.

Phase 2a of metacognition plan. Detects when agents are stuck (repeated
similar queries without writes) and creates ephemeral StuckIndicator nodes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.engine.session_state import SessionState

logger = structlog.get_logger(__name__)

# Stuck detection thresholds
STUCK_QUERY_COUNT = 3  # queries needed to trigger
STUCK_WINDOW_MINUTES = 5  # time window
STUCK_SIMILARITY_THRESHOLD = 0.7  # how similar queries must be


def _query_similarity(q1: str, q2: str) -> float:
    """Compute similarity ratio between two queries."""
    return SequenceMatcher(None, q1.lower(), q2.lower()).ratio()


def detect_stuck_pattern(session: SessionState) -> list[str] | None:
    """Check if session shows stuck pattern.

    Returns list of similar query strings if stuck, None otherwise.

    Stuck = 3+ similar queries in 5 min window with no writes.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=STUCK_WINDOW_MINUTES)

    # Filter to recent queries without writes
    recent = [q for q in session.recent_queries if q.timestamp >= cutoff and not q.had_write]

    if len(recent) < STUCK_QUERY_COUNT:
        return None

    # Check last N queries for similarity
    last_queries = recent[-STUCK_QUERY_COUNT:]
    reference = last_queries[-1].query

    similar = [
        q.query
        for q in last_queries
        if _query_similarity(q.query, reference) >= STUCK_SIMILARITY_THRESHOLD
    ]

    if len(similar) >= STUCK_QUERY_COUNT:
        return similar

    return None


CREATE_STUCK_INDICATOR = """
MERGE (s:EpistemicState {id: $id, silo_id: $silo_id})
ON CREATE SET
    s.session_id = $session_id,
    s.indicator_type = 'stuck',
    s.query_pattern = $query_pattern,
    s.query_count = $query_count,
    s.created_at = $created_at,
    s.expires_at = $expires_at
RETURN s.id AS id
"""

CREATE_STUCK_ABOUT_EDGES = """
UNWIND $query_node_ids AS qid
MATCH (s:EpistemicState {id: $stuck_id, silo_id: $silo_id})
MATCH (q {id: qid, silo_id: $silo_id})
MERGE (s)-[:ABOUT]->(q)
"""


async def create_stuck_indicator(
    store: HyperGraphStore,
    silo_id: str,
    session_id: str,
    similar_queries: list[str],
    query_node_ids: list[str] | None = None,
) -> str:
    """Create a StuckIndicator (EpistemicState) node.

    Args:
        store: Graph store
        silo_id: Tenant silo
        session_id: Current session
        similar_queries: The repeated queries
        query_node_ids: Optional node IDs to link via ABOUT

    Returns:
        The stuck indicator node ID
    """
    stuck_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    # Expire with session (4 hours) or sooner
    expires_at = now + timedelta(hours=4)

    await store.execute_write(
        CREATE_STUCK_INDICATOR,
        {
            "id": stuck_id,
            "silo_id": silo_id,
            "session_id": session_id,
            "query_pattern": similar_queries[0][:200],  # representative
            "query_count": len(similar_queries),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        },
    )

    if query_node_ids:
        await store.execute_write(
            CREATE_STUCK_ABOUT_EDGES,
            {
                "stuck_id": stuck_id,
                "silo_id": silo_id,
                "query_node_ids": query_node_ids,
            },
        )

    logger.info(
        "stuck_indicator_created",
        stuck_id=stuck_id,
        session_id=session_id,
        silo_id=silo_id,
        query_count=len(similar_queries),
    )

    return stuck_id


GET_ACTIVE_STUCK_INDICATOR = """
MATCH (s:EpistemicState {
    session_id: $session_id,
    silo_id: $silo_id,
    indicator_type: 'stuck'
})
WHERE s.expires_at > $now
RETURN s.id AS id, s.query_pattern AS query_pattern
ORDER BY s.created_at DESC
LIMIT 1
"""


async def get_active_stuck_indicator(
    store: HyperGraphStore,
    silo_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    """Get active stuck indicator for session, if any."""
    now = datetime.now(UTC).isoformat()
    result = await store.execute_query(
        GET_ACTIVE_STUCK_INDICATOR,
        {"session_id": session_id, "silo_id": silo_id, "now": now},
    )
    return result[0] if result else None


RESOLVE_STUCK_INDICATOR = """
MATCH (s:EpistemicState {id: $stuck_id, silo_id: $silo_id})
SET s.resolved_at = $resolved_at,
    s.resolved_by_action = $action,
    s.resolved_by_node = $node_id
RETURN s.id AS id, s.query_pattern AS query_pattern
"""

CREATE_BREAKTHROUGH = """
MERGE (b:Breakthrough {id: $id, silo_id: $silo_id})
ON CREATE SET
    b.query_pattern = $query_pattern,
    b.resolved_by_action = $action,
    b.resolved_by_node = $node_id,
    b.created_at = $created_at
WITH b
MATCH (s:EpistemicState {id: $stuck_id, silo_id: $silo_id})
MERGE (b)-[:RESOLVED]->(s)
RETURN b.id AS id
"""


async def resolve_stuck_indicator(
    store: HyperGraphStore,
    stuck_id: str,
    silo_id: str,
    action: str,
    node_id: str | None = None,
) -> str | None:
    """Mark a stuck indicator as resolved and create a Breakthrough.

    Returns the Breakthrough node ID if created, None if stuck indicator not found.

    Called when agent breaks out of stuck state (e.g., writes something).

    Args:
        store: Graph store
        stuck_id: The EpistemicState node ID
        silo_id: Tenant silo
        action: What resolved it (e.g., "remember", "learn")
        node_id: Optional node that was created

    Returns:
        Breakthrough node ID if created, None if stuck indicator not found.
    """
    result = await store.execute_write(
        RESOLVE_STUCK_INDICATOR,
        {
            "stuck_id": stuck_id,
            "silo_id": silo_id,
            "resolved_at": datetime.now(UTC).isoformat(),
            "action": action,
            "node_id": node_id,
        },
    )

    if not result:
        return None

    query_pattern = result[0].get("query_pattern")

    # Create Breakthrough node (persists cross-session)
    breakthrough_id = str(uuid.uuid4())
    await store.execute_write(
        CREATE_BREAKTHROUGH,
        {
            "id": breakthrough_id,
            "silo_id": silo_id,
            "stuck_id": stuck_id,
            "query_pattern": query_pattern,
            "action": action,
            "node_id": node_id,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(
        "stuck_indicator_resolved",
        stuck_id=stuck_id,
        breakthrough_id=breakthrough_id,
        action=action,
        node_id=node_id,
    )

    return breakthrough_id


# Query to find similar breakthroughs for hints
FIND_SIMILAR_BREAKTHROUGHS = """
MATCH (b:Breakthrough {silo_id: $silo_id})
WHERE b.query_pattern IS NOT NULL
RETURN b.id AS id,
       b.query_pattern AS query_pattern,
       b.resolved_by_action AS action,
       b.resolved_by_node AS node_id,
       b.created_at AS created_at
ORDER BY b.created_at DESC
LIMIT 50
"""


async def find_breakthrough_hints(
    store: HyperGraphStore,
    silo_id: str,
    query: str,
    similarity_threshold: float = 0.6,
) -> list[dict[str, Any]]:
    """Find past breakthroughs that match the current query.

    Used to surface hints when an agent might be getting stuck on
    something that was resolved before.

    Args:
        store: Graph store
        silo_id: Tenant silo
        query: Current query to match against
        similarity_threshold: Minimum similarity to include (default 0.6)

    Returns:
        List of matching breakthroughs with similarity scores
    """
    results = await store.execute_query(
        FIND_SIMILAR_BREAKTHROUGHS,
        {"silo_id": silo_id},
    )

    if not results:
        return []

    hints = []
    for row in results:
        pattern = row.get("query_pattern", "")
        if not pattern:
            continue

        similarity = _query_similarity(query, pattern)
        if similarity >= similarity_threshold:
            hints.append(
                {
                    "breakthrough_id": row["id"],
                    "query_pattern": pattern,
                    "resolved_by_action": row.get("action"),
                    "resolved_by_node": row.get("node_id"),
                    "similarity": round(similarity, 3),
                }
            )

    # Sort by similarity descending
    hints.sort(key=lambda x: x["similarity"], reverse=True)
    return hints[:5]  # Top 5 hints


# =============================================================================
# Phase 3: Metacognitive Queries
# =============================================================================

# Volatility detection: find topics with high supersession churn
FIND_VOLATILE_TOPICS = """
MATCH (n {silo_id: $silo_id})-[:SUPERSEDES*1..]->(old)
WITH n.id AS head_id, n.content AS content, count(old) AS chain_length
WHERE chain_length >= $min_chain_length
RETURN head_id, content, chain_length
ORDER BY chain_length DESC
LIMIT $limit
"""


async def detect_volatile_topics(
    store: HyperGraphStore,
    silo_id: str,
    min_chain_length: int = 3,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Find topics with high supersession churn (volatility).

    A volatile topic is one that has been superseded many times,
    indicating unstable or frequently-changing knowledge.

    Args:
        store: Graph store
        silo_id: Tenant silo
        min_chain_length: Minimum supersession chain length to consider volatile
        limit: Max results to return

    Returns:
        List of volatile topics with chain lengths
    """
    results = await store.execute_query(
        FIND_VOLATILE_TOPICS,
        {"silo_id": silo_id, "min_chain_length": min_chain_length, "limit": limit},
    )

    return [
        {
            "node_id": row["head_id"],
            "content_preview": (row.get("content") or "")[:100],
            "supersession_count": row["chain_length"],
            "warning": "High volatility - this topic has changed frequently",
        }
        for row in results
    ]


# Gap detection: track queries that returned no results
RECORD_UNANSWERED_QUERY = """
MERGE (g:KnownUnknown {query_hash: $query_hash, silo_id: $silo_id})
ON CREATE SET
    g.id = $id,
    g.query = $query,
    g.first_asked = $timestamp,
    g.ask_count = 1
ON MATCH SET
    g.last_asked = $timestamp,
    g.ask_count = g.ask_count + 1
RETURN g.id AS id, g.ask_count AS ask_count
"""

FIND_KNOWLEDGE_GAPS = """
MATCH (g:KnownUnknown {silo_id: $silo_id})
WHERE g.ask_count >= $min_asks
RETURN g.id AS id, g.query AS query, g.ask_count AS ask_count,
       g.first_asked AS first_asked, g.last_asked AS last_asked
ORDER BY g.ask_count DESC
LIMIT $limit
"""


async def record_knowledge_gap(
    store: HyperGraphStore,
    silo_id: str,
    query: str,
) -> dict[str, Any]:
    """Record an unanswered query as a known unknown.

    Called when recall returns no results for a query.

    Args:
        store: Graph store
        silo_id: Tenant silo
        query: The unanswered query

    Returns:
        Gap record with ask count
    """
    import hashlib

    query_hash = hashlib.sha256(query.lower().encode()).hexdigest()[:16]
    gap_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    result = await store.execute_write(
        RECORD_UNANSWERED_QUERY,
        {
            "id": gap_id,
            "silo_id": silo_id,
            "query": query[:500],  # Truncate long queries
            "query_hash": query_hash,
            "timestamp": now,
        },
    )

    if result:
        return {
            "gap_id": result[0].get("id") or gap_id,
            "ask_count": result[0].get("ask_count", 1),
        }
    return {"gap_id": gap_id, "ask_count": 1}


async def find_knowledge_gaps(
    store: HyperGraphStore,
    silo_id: str,
    min_asks: int = 2,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Find frequently-asked but unanswered queries.

    Args:
        store: Graph store
        silo_id: Tenant silo
        min_asks: Minimum ask count to surface
        limit: Max results

    Returns:
        List of knowledge gaps sorted by frequency
    """
    results = await store.execute_query(
        FIND_KNOWLEDGE_GAPS,
        {"silo_id": silo_id, "min_asks": min_asks, "limit": limit},
    )

    return [
        {
            "gap_id": row["id"],
            "query": row["query"],
            "ask_count": row["ask_count"],
            "first_asked": row.get("first_asked"),
            "last_asked": row.get("last_asked"),
        }
        for row in results
    ]


# Cross-agent provenance: contribution graph per belief
FIND_BELIEF_CONTRIBUTORS = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
OPTIONAL MATCH (b)<-[:SYNTHESIZED_FROM]-(f:Fact)
OPTIONAL MATCH (f)<-[:PROMOTED_FROM]-(c:Claim)
OPTIONAL MATCH (c)<-[:ASSERTED_BY]-(a:Agent)
WITH b, collect(DISTINCT {
    claim_id: c.id,
    claim_content: c.content,
    agent_id: a.id,
    agent_role: a.role
}) AS contributions
RETURN b.id AS belief_id, b.content AS belief_content, contributions
"""

FIND_AGENT_CONTRIBUTIONS = """
MATCH (a:Agent {id: $agent_id, silo_id: $silo_id})
OPTIONAL MATCH (a)-[:ASSERTED_BY]->(c:Claim)
OPTIONAL MATCH (c)-[:PROMOTED_FROM]->(f:Fact)
OPTIONAL MATCH (f)-[:SYNTHESIZED_FROM]->(b:Belief)
WITH a,
     count(DISTINCT c) AS claims_made,
     count(DISTINCT f) AS facts_promoted,
     count(DISTINCT b) AS beliefs_influenced
RETURN a.id AS agent_id, a.role AS role,
       claims_made, facts_promoted, beliefs_influenced
"""


async def get_belief_provenance(
    store: HyperGraphStore,
    silo_id: str,
    belief_id: str,
) -> dict[str, Any] | None:
    """Get the contribution graph for a belief.

    Shows which agents contributed claims that were promoted to
    facts and synthesized into this belief.

    Args:
        store: Graph store
        silo_id: Tenant silo
        belief_id: The belief to trace

    Returns:
        Provenance info with contributing agents, or None if not found
    """
    results = await store.execute_query(
        FIND_BELIEF_CONTRIBUTORS,
        {"belief_id": belief_id, "silo_id": silo_id},
    )

    if not results:
        return None

    row = results[0]
    contributions = row.get("contributions") or []

    # Group by agent
    agents: dict[str, dict[str, Any]] = {}
    for contrib in contributions:
        agent_id = contrib.get("agent_id")
        if not agent_id:
            continue
        if agent_id not in agents:
            agents[agent_id] = {
                "agent_id": agent_id,
                "role": contrib.get("agent_role"),
                "claims": [],
            }
        if contrib.get("claim_id"):
            agents[agent_id]["claims"].append(
                {
                    "claim_id": contrib["claim_id"],
                    "content_preview": (contrib.get("claim_content") or "")[:100],
                }
            )

    return {
        "belief_id": row["belief_id"],
        "belief_content": row.get("belief_content"),
        "contributors": list(agents.values()),
        "contributor_count": len(agents),
    }


async def get_agent_contribution_stats(
    store: HyperGraphStore,
    silo_id: str,
    agent_id: str,
) -> dict[str, Any] | None:
    """Get contribution statistics for an agent.

    Args:
        store: Graph store
        silo_id: Tenant silo
        agent_id: The agent to query

    Returns:
        Contribution stats or None if agent not found
    """
    results = await store.execute_query(
        FIND_AGENT_CONTRIBUTIONS,
        {"agent_id": agent_id, "silo_id": silo_id},
    )

    if not results:
        return None

    row = results[0]
    return {
        "agent_id": row["agent_id"],
        "role": row.get("role"),
        "claims_made": row.get("claims_made", 0),
        "facts_promoted": row.get("facts_promoted", 0),
        "beliefs_influenced": row.get("beliefs_influenced", 0),
    }
