# Epistemic Layer Fixes

**Date:** 2026-05-17
**Status:** Draft (reviewed)
**Branch:** `phase-epistemic-layer-fixes`

## Summary

Address three architectural issues discovered during EAG exploration:
1. Evidence accessibility stub inverts incentive structure
2. Missing EpistemicStore abstraction above HyperGraphStore
3. Orphaned chains have no recovery job

## Approach

Evidence-first ordering in a single PR, tested incrementally:
1. Fix evidence accessibility (highest impact, unblocks correct incentives)
2. Build EpistemicStore abstraction (big refactor, uses fixed evidence logic)
3. Add orphan recovery job (safety net, independent)

---

## Issue 1: Evidence Accessibility Fix

### Problem

`get_accessible_evidence()` in `chain_applicability.py` returns empty set. The logic `evidence_used.issubset(accessible)` means only chains with NO evidence pass Layer 3. This inverts the incentive - agents who correctly ground reasoning in evidence get penalized with no chain reuse.

### Solution

Implement session-scoped evidence accessibility using edges (not overwriting properties).

**Design decision:** Use `:ACCESSED_BY` edges instead of a single `accessed_by_session` property. This preserves multi-session access history.

**`engine/queries.py`** - add queries:
```python
GET_SESSION_ACCESSIBLE_EVIDENCE = """
MATCH (n:Node {silo_id: $silo_id})
WHERE n.session_id = $session_id 
   OR (n)<-[:ACCESSED_BY]-(:Session {id: $session_id})
RETURN n.id AS node_id
"""

# Use MERGE to avoid duplicate edges
MARK_NODE_ACCESSED = """
MATCH (n:Node {id: $node_id, silo_id: $silo_id})
MATCH (s:Session {id: $session_id, silo_id: $silo_id})
MERGE (n)<-[:ACCESSED_BY {at: timestamp()}]-(s)
"""

# Ensure session node exists (called once per session start)
ENSURE_SESSION_NODE = """
MERGE (s:Session {id: $session_id, silo_id: $silo_id})
ON CREATE SET s.created_at = timestamp()
"""

GET_SILO_EVIDENCE_NODES = """
MATCH (n:Node {silo_id: $silo_id})
WHERE n.layer IN ['knowledge', 'memory']
RETURN n.id AS node_id
LIMIT $limit
"""
```

**`engine/chain_applicability.py`** - implement:
```python
from context_service.engine import queries
from datetime import UTC, datetime

log = structlog.get_logger(__name__)

async def get_accessible_evidence(silo_id: str, session_id: str) -> set[str]:
    """Return evidence node IDs accessible within this session context.
    
    Queries nodes that were:
    1. Created by this session (agent authored, via session_id property)
    2. Retrieved/accessed during this session (tracked via ACCESSED_BY edge)
    
    Session ID availability: passed from MCP auth context through find_applicable_chain.
    """
    from context_service.mcp.server import get_context_service
    
    ctx = get_context_service()
    store = ctx._memgraph
    
    try:
        rows = await store.execute_query(
            queries.GET_SESSION_ACCESSIBLE_EVIDENCE,
            {"silo_id": silo_id, "session_id": session_id}
        )
        accessible = {str(r["node_id"]) for r in rows}
        
        # Fallback: if session tracking incomplete, be permissive
        # Better to reuse too many chains than penalize evidence use
        if not accessible:
            log.info("session_evidence_empty_fallback", 
                     silo_id=silo_id, session_id=session_id)
            return await _get_silo_wide_evidence(silo_id, store)
        return accessible
    except Exception as e:
        log.warning("accessible_evidence_query_failed", error=str(e))
        # On failure, permissive fallback
        return await _get_silo_wide_evidence(silo_id, store)

async def _get_silo_wide_evidence(silo_id: str, store) -> set[str]:
    """Fallback: return all evidence in silo (permissive)."""
    rows = await store.execute_query(
        queries.GET_SILO_EVIDENCE_NODES,
        {"silo_id": silo_id, "limit": 1000}
    )
    return {str(r["node_id"]) for r in rows}
```

**`mcp/tools/recall.py`** - track access on retrieval:
```python
# Ensure session node exists (idempotent)
await store.execute_write(
    queries.ENSURE_SESSION_NODE,
    {"session_id": session_id, "silo_id": silo_id}
)

# After retrieving nodes, mark them as accessed by this session
for node in retrieved_nodes:
    try:
        await store.execute_write(
            queries.MARK_NODE_ACCESSED,
            {"node_id": str(node.id), "silo_id": silo_id, "session_id": session_id}
        )
    except Exception as e:
        # Non-fatal: log and continue
        log.warning("mark_node_accessed_failed", node_id=str(node.id), error=str(e))
```

### Done criteria

- [ ] Chains WITH evidence can pass Layer 3 when evidence was accessed in session
- [ ] Chains WITHOUT evidence still pass (unchanged behavior)
- [ ] Recall marks nodes as accessed via ACCESSED_BY edges
- [ ] Session node created on first access
- [ ] Fallback to silo-wide on session tracking gaps
- [ ] Multi-session access preserved (no overwrites)

---

## Issue 2: EpistemicStore Abstraction

### Problem

`synthesis.py` has ~10 direct `execute_query`/`execute_write` calls bypassing `HyperGraphStore` protocol. This couples synthesis to Memgraph's Cypher dialect - swapping graph stores requires rewriting synthesis.

### Solution

New protocol layer for CITE-domain operations.

### Query-to-Method Mapping

Based on analysis of `synthesis.py`:

| Line | Current Query | Protocol Method |
|------|---------------|-----------------|
| 137 | GET_FACTS_IN_CLUSTER | `get_fact_cluster()` |
| 164 | CREATE_BELIEF_FROM_FACTS | `create_belief()` |
| 179 | CREATE_BELIEF_FACT_EDGES | `link_belief_to_facts()` |
| 189 | UPDATE_BELIEF_CENTROID | `update_belief_centroid()` |
| 245 | FIND_SIMILAR_BELIEFS | `find_similar_beliefs()` |
| 342 | CREATE_MERGED_BELIEF | `create_merged_belief()` |
| 356 | CREATE_MERGED_BELIEF_FACT_EDGES | `link_merged_belief_to_facts()` |
| 365 | CREATE_MERGED_FROM_EDGES | `link_merged_from_sources()` |
| 377 | MARK_BELIEF_STALE | `mark_belief_stale()` |
| 420 | CHECK_BELIEF_COVERAGE | `check_belief_coverage()` |

### Dependency Injection

**Approach:** Wrap pattern - caller creates `EpistemicStore(graph_store)`.

```python
# In synthesis.py callers (e.g., custodian jobs)
from context_service.engine.epistemic_store import MemgraphEpistemicStore

graph_store = get_context_service()._memgraph
epistemic_store = MemgraphEpistemicStore(graph_store)
await synthesize_beliefs(epistemic_store, silo_id, ...)
```

### Transaction Semantics

Multi-step operations (create belief + link edges) should be atomic. Use the existing transaction pattern:

```python
class MemgraphEpistemicStore:
    async def create_belief_with_links(
        self, silo_id: str, content: str, fact_ids: list[str], ...
    ) -> str:
        """Atomic: create belief and link to facts in single transaction."""
        async with self._store.transaction() as tx:
            belief_id = await self._create_belief(tx, silo_id, content, ...)
            await self._link_belief_to_facts(tx, belief_id, fact_ids, silo_id)
            return belief_id
```

### Embedding Client Handling

The `update_belief_centroid` call is conditional on embedding_client. Options:
1. **Pass to protocol** (chosen): Optional parameter, method no-ops if None
2. Split into separate methods
3. Leave outside protocol

```python
async def update_belief_centroid(
    self, silo_id: str, belief_id: str, 
    embedding_client: EmbeddingClient | None = None
) -> None:
    """Update belief centroid embedding. No-op if embedding_client is None."""
    if embedding_client is None:
        return
    # ... compute and store centroid
```

### Feature Flag

For rollback safety, gate the abstraction:

```python
# settings.py
class FeatureFlags(BaseModel):
    use_epistemic_store: bool = False

# synthesis.py
if settings.feature_flags.use_epistemic_store:
    await epistemic_store.create_belief(...)
else:
    await store.execute_write(LEGACY_QUERY, ...)
```

Remove flag once migration validated in production.

**`engine/protocols.py`** - add protocol:
```python
from typing import Protocol, runtime_checkable, Any

@runtime_checkable
class EpistemicStore(Protocol):
    """CITE-domain operations for Wisdom/Intelligence layers.
    
    Sits above HyperGraphStore. Encapsulates belief synthesis,
    fact clustering, and reasoning chain operations.
    """
    
    # Fact clustering
    async def get_fact_cluster(
        self, silo_id: str, cluster_id: str
    ) -> list[dict[str, Any]]: ...
    
    async def get_unclustered_facts(
        self, silo_id: str, limit: int = 100
    ) -> list[dict[str, Any]]: ...
    
    # Belief creation (atomic with links)
    async def create_belief_with_links(
        self, silo_id: str, content: str, fact_ids: list[str],
        confidence: float, reasoning: str | None = None
    ) -> str: ...
    
    async def update_belief_centroid(
        self, silo_id: str, belief_id: str,
        embedding_client: Any | None = None
    ) -> None: ...
    
    # Belief queries
    async def find_similar_beliefs(
        self, silo_id: str, content: str, threshold: float = 0.8
    ) -> list[dict[str, Any]]: ...
    
    async def check_belief_coverage(
        self, silo_id: str, fact_ids: list[str]
    ) -> dict[str, Any]: ...
    
    # Belief merging (atomic)
    async def merge_beliefs(
        self, silo_id: str, source_belief_ids: list[str],
        merged_content: str, fact_ids: list[str]
    ) -> str: ...
    
    async def mark_belief_stale(
        self, silo_id: str, belief_id: str, reason: str
    ) -> None: ...
```

**`engine/epistemic_store.py`** - implementation:
```python
from __future__ import annotations
from typing import Any
import structlog

from context_service.engine import queries
from context_service.engine.protocols import HyperGraphStore

log = structlog.get_logger(__name__)

class MemgraphEpistemicStore:
    """EpistemicStore implementation backed by Memgraph via HyperGraphStore."""
    
    def __init__(self, graph_store: HyperGraphStore):
        self._store = graph_store
    
    async def get_fact_cluster(self, silo_id: str, cluster_id: str) -> list[dict]:
        return await self._store.execute_query(
            queries.EPISTEMIC_GET_FACT_CLUSTER,
            {"silo_id": silo_id, "cluster_id": cluster_id}
        )
    
    async def get_unclustered_facts(self, silo_id: str, limit: int = 100) -> list[dict]:
        return await self._store.execute_query(
            queries.EPISTEMIC_GET_UNCLUSTERED_FACTS,
            {"silo_id": silo_id, "limit": limit}
        )
    
    async def create_belief_with_links(
        self, silo_id: str, content: str, fact_ids: list[str],
        confidence: float, reasoning: str | None = None
    ) -> str:
        """Atomic: create belief and link to facts."""
        async with self._store.transaction() as tx:
            # Create belief node
            result = await tx.execute_write(
                queries.EPISTEMIC_CREATE_BELIEF,
                {"silo_id": silo_id, "content": content, 
                 "confidence": confidence, "reasoning": reasoning}
            )
            belief_id = result[0]["id"]
            
            # Link to facts
            await tx.execute_write(
                queries.EPISTEMIC_LINK_BELIEF_TO_FACTS,
                {"belief_id": belief_id, "fact_ids": fact_ids, "silo_id": silo_id}
            )
            return belief_id
    
    async def update_belief_centroid(
        self, silo_id: str, belief_id: str,
        embedding_client: Any | None = None
    ) -> None:
        """Update belief centroid embedding. No-op if embedding_client is None."""
        if embedding_client is None:
            return
        # Fetch belief content, compute embedding, store
        belief = await self._store.execute_query(
            queries.EPISTEMIC_GET_BELIEF,
            {"silo_id": silo_id, "belief_id": belief_id}
        )
        if not belief:
            return
        embedding = await embedding_client.embed(belief[0]["content"])
        await self._store.execute_write(
            queries.EPISTEMIC_UPDATE_BELIEF_CENTROID,
            {"belief_id": belief_id, "centroid": embedding}
        )
    
    async def find_similar_beliefs(
        self, silo_id: str, content: str, threshold: float = 0.8
    ) -> list[dict]:
        return await self._store.execute_query(
            queries.EPISTEMIC_FIND_SIMILAR_BELIEFS,
            {"silo_id": silo_id, "content": content, "threshold": threshold}
        )
    
    async def check_belief_coverage(
        self, silo_id: str, fact_ids: list[str]
    ) -> dict[str, Any]:
        return await self._store.execute_query(
            queries.EPISTEMIC_CHECK_BELIEF_COVERAGE,
            {"silo_id": silo_id, "fact_ids": fact_ids}
        )
    
    async def merge_beliefs(
        self, silo_id: str, source_belief_ids: list[str],
        merged_content: str, fact_ids: list[str]
    ) -> str:
        """Atomic: create merged belief, link to facts, link to sources, mark sources stale."""
        async with self._store.transaction() as tx:
            # Create merged belief
            result = await tx.execute_write(
                queries.EPISTEMIC_CREATE_MERGED_BELIEF,
                {"silo_id": silo_id, "content": merged_content}
            )
            merged_id = result[0]["id"]
            
            # Link to facts
            await tx.execute_write(
                queries.EPISTEMIC_LINK_BELIEF_TO_FACTS,
                {"belief_id": merged_id, "fact_ids": fact_ids, "silo_id": silo_id}
            )
            
            # Link to source beliefs
            await tx.execute_write(
                queries.EPISTEMIC_LINK_MERGED_FROM_SOURCES,
                {"merged_id": merged_id, "source_ids": source_belief_ids}
            )
            
            # Mark source beliefs as stale
            for source_id in source_belief_ids:
                await tx.execute_write(
                    queries.EPISTEMIC_MARK_BELIEF_STALE,
                    {"belief_id": source_id, "reason": f"merged_into:{merged_id}"}
                )
            
            return merged_id
    
    async def mark_belief_stale(
        self, silo_id: str, belief_id: str, reason: str
    ) -> None:
        await self._store.execute_write(
            queries.EPISTEMIC_MARK_BELIEF_STALE,
            {"silo_id": silo_id, "belief_id": belief_id, "reason": reason}
        )
```

**`engine/queries.py`** - add queries (prefix with EPISTEMIC_ for clarity):
```python
# --- EpistemicStore queries (extracted from synthesis.py) ---

EPISTEMIC_GET_FACT_CLUSTER = """
MATCH (f:Fact {silo_id: $silo_id})-[:IN_CLUSTER]->(c:Cluster {id: $cluster_id})
RETURN f.id AS id, f.content AS content, f.confidence AS confidence
"""

EPISTEMIC_GET_UNCLUSTERED_FACTS = """
MATCH (f:Fact {silo_id: $silo_id})
WHERE NOT (f)-[:IN_CLUSTER]->()
RETURN f.id AS id, f.content AS content, f.confidence AS confidence
LIMIT $limit
"""

EPISTEMIC_CREATE_BELIEF = """
CREATE (b:Belief:Node {
    id: randomUUID(),
    silo_id: $silo_id,
    content: $content,
    confidence: $confidence,
    reasoning: $reasoning,
    created_at: timestamp(),
    committed: false
})
RETURN b.id AS id
"""

EPISTEMIC_LINK_BELIEF_TO_FACTS = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
UNWIND $fact_ids AS fact_id
MATCH (f:Fact {id: fact_id, silo_id: $silo_id})
CREATE (b)-[:SYNTHESIZED_FROM]->(f)
"""

EPISTEMIC_GET_BELIEF = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
RETURN b.content AS content, b.confidence AS confidence
"""

EPISTEMIC_UPDATE_BELIEF_CENTROID = """
MATCH (b:Belief {id: $belief_id})
SET b.centroid = $centroid
"""

EPISTEMIC_FIND_SIMILAR_BELIEFS = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE b.committed = true
// Similarity check via centroid - implementation depends on vector index
RETURN b.id AS id, b.content AS content, b.confidence AS confidence
"""

EPISTEMIC_CHECK_BELIEF_COVERAGE = """
MATCH (f:Fact {silo_id: $silo_id})
WHERE f.id IN $fact_ids
OPTIONAL MATCH (f)<-[:SYNTHESIZED_FROM]-(b:Belief {committed: true})
RETURN f.id AS fact_id, collect(b.id) AS covering_beliefs
"""

EPISTEMIC_CREATE_MERGED_BELIEF = """
CREATE (b:Belief:Node {
    id: randomUUID(),
    silo_id: $silo_id,
    content: $content,
    created_at: timestamp(),
    committed: false,
    is_merged: true
})
RETURN b.id AS id
"""

EPISTEMIC_LINK_MERGED_FROM_SOURCES = """
MATCH (merged:Belief {id: $merged_id})
UNWIND $source_ids AS source_id
MATCH (source:Belief {id: source_id})
CREATE (merged)-[:MERGED_FROM]->(source)
"""

EPISTEMIC_MARK_BELIEF_STALE = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
SET b.stale = true, b.stale_reason = $reason, b.stale_at = timestamp()
"""
```

### Done criteria

- [ ] EpistemicStore protocol defined in protocols.py
- [ ] MemgraphEpistemicStore implementation complete with all 10 methods
- [ ] All synthesis.py Cypher calls migrated to protocol methods
- [ ] Queries extracted to queries.py with EPISTEMIC_ prefix
- [ ] synthesis.py has zero direct execute_query/execute_write calls
- [ ] Feature flag for rollback (default off, enable in staging first)
- [ ] Transaction semantics for multi-step operations
- [ ] Tests pass with new abstraction

---

## Issue 3: Orphan Chain Recovery Job

### Problem

`orphaned_chains` table accumulates during Memgraph issues. No recovery mechanism - chains exist in Postgres but are invisible to graph traversal, evidence linking, and session history.

### Solution

Dagster scheduled job with exponential backoff.

### Schema Note

**`retry_count` already exists** in the current schema. Only `last_retry_at` needs migration.

**Migration** (`alembic/versions/xxx_add_orphan_retry_at.py`):
```python
def upgrade():
    op.add_column('orphaned_chains', 
        sa.Column('last_retry_at', sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column('orphaned_chains', 'last_retry_at')
```

### Telemetry

**`telemetry/metrics.py`** - add counter:
```python
ORPHAN_CHAINS_EXHAUSTED = Counter(
    "context_orphan_chains_exhausted_total",
    "Number of orphan chains that exhausted all retries",
    ["silo_id"]
)

ORPHAN_CHAINS_RECOVERED = Counter(
    "context_orphan_chains_recovered_total", 
    "Number of orphan chains successfully recovered",
    ["silo_id"]
)
```

**`pipelines/jobs/orphan_recovery.py`:**
```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from dagster import job, op, schedule, OpExecutionContext, Out, Output
from sqlalchemy import select, update, delete
import structlog

from context_service.models.postgres.reasoning import OrphanedChain, ReasoningChainSteps
from context_service.telemetry.metrics import ORPHAN_CHAINS_EXHAUSTED, ORPHAN_CHAINS_RECOVERED

log = structlog.get_logger(__name__)

MAX_RETRIES = 5
BASE_BACKOFF_MINUTES = 5


def backoff_elapsed(retry_count: int, last_retry_at: datetime | None) -> bool:
    """Check if enough time has passed for next retry."""
    if last_retry_at is None:
        return True
    wait_minutes = (2 ** retry_count) * BASE_BACKOFF_MINUTES
    return datetime.now(UTC) > last_retry_at + timedelta(minutes=wait_minutes)


async def fetch_chain_from_postgres(chain_id: UUID) -> dict:
    """Fetch full chain data from Postgres for Memgraph projection."""
    from context_service.db.postgres import get_session
    
    async with get_session() as session:
        result = await session.execute(
            select(ReasoningChainSteps).where(ReasoningChainSteps.chain_id == chain_id)
        )
        steps = result.scalars().all()
        if not steps:
            raise ValueError(f"No steps found for chain {chain_id}")
        
        return {
            "chain_id": str(chain_id),
            "silo_id": str(steps[0].silo_id),
            "steps": [{"content": s.content, "step_index": s.step_index} for s in steps],
            "step_count": len(steps),
        }


async def delete_orphan(orphan_id: UUID) -> None:
    """Delete recovered orphan from dead-letter table."""
    from context_service.db.postgres import get_session
    
    async with get_session() as session:
        await session.execute(
            delete(OrphanedChain).where(OrphanedChain.id == orphan_id)
        )
        await session.commit()


async def increment_retry(orphan_id: UUID) -> None:
    """Increment retry count and update last_retry_at."""
    from context_service.db.postgres import get_session
    
    async with get_session() as session:
        await session.execute(
            update(OrphanedChain)
            .where(OrphanedChain.id == orphan_id)
            .values(
                retry_count=OrphanedChain.retry_count + 1,
                last_retry_at=datetime.now(UTC)
            )
        )
        await session.commit()


@op(out={"eligible": Out(), "exhausted": Out()})
def fetch_orphaned_chains(context: OpExecutionContext):
    """Fetch chains eligible for retry and those exhausted."""
    from context_service.db.postgres import get_session
    
    async def _fetch():
        async with get_session() as session:
            # Eligible for retry
            result = await session.execute(
                select(OrphanedChain).where(OrphanedChain.retry_count < MAX_RETRIES)
            )
            chains = result.scalars().all()
            eligible = [c for c in chains if backoff_elapsed(c.retry_count, c.last_retry_at)]
            
            # Exhausted (for alerting)
            exhausted_result = await session.execute(
                select(OrphanedChain).where(OrphanedChain.retry_count >= MAX_RETRIES)
            )
            exhausted = exhausted_result.scalars().all()
            
            return eligible, exhausted
    
    eligible, exhausted = asyncio.run(_fetch())
    context.log.info(f"Found {len(eligible)} eligible orphans, {len(exhausted)} exhausted")
    yield Output(eligible, output_name="eligible")
    yield Output(exhausted, output_name="exhausted")


@op
def retry_chains_to_memgraph(context: OpExecutionContext, eligible: list) -> dict:
    """Attempt to write chain projections to Memgraph."""
    results = {"success": 0, "failed": 0}
    
    async def _retry():
        from context_service.mcp.server import get_context_service
        ctx = get_context_service()
        store = ctx._memgraph
        
        for orphan in eligible:
            try:
                chain_data = await fetch_chain_from_postgres(orphan.chain_id)
                await store.upsert_reasoning_chain_projection(chain_data)
                await delete_orphan(orphan.id)
                results["success"] += 1
                ORPHAN_CHAINS_RECOVERED.labels(silo_id=str(orphan.silo_id)).inc()
                log.info("orphan_chain_recovered", chain_id=str(orphan.chain_id))
            except Exception as e:
                await increment_retry(orphan.id)
                results["failed"] += 1
                log.warning("orphan_chain_retry_failed", 
                           chain_id=str(orphan.chain_id), 
                           retry_count=orphan.retry_count + 1,
                           error=str(e))
        return results
    
    return asyncio.run(_retry())


@op
def alert_exhausted_chains(context: OpExecutionContext, exhausted: list):
    """Alert on chains that hit max retries."""
    if not exhausted:
        return
    
    log.error("orphan_chains_exhausted", 
              count=len(exhausted),
              chain_ids=[str(c.chain_id) for c in exhausted])
    
    for orphan in exhausted:
        ORPHAN_CHAINS_EXHAUSTED.labels(silo_id=str(orphan.silo_id)).inc()


@job
def orphan_chain_recovery_job():
    eligible, exhausted = fetch_orphaned_chains()
    retry_chains_to_memgraph(eligible)
    alert_exhausted_chains(exhausted)


@schedule(
    job=orphan_chain_recovery_job,
    cron_schedule="0 * * * *",  # hourly
)
def orphan_recovery_schedule(context):
    return {}
```

### Backoff schedule

| Retry | Wait before next |
|-------|------------------|
| 0 → 1 | 5 min |
| 1 → 2 | 10 min |
| 2 → 3 | 20 min |
| 3 → 4 | 40 min |
| 4 → 5 | 80 min |
| 5+ | Alert, no more retries |

### Done criteria

- [ ] Schema migration adds `last_retry_at` column (retry_count already exists)
- [ ] Helper functions defined: `fetch_chain_from_postgres`, `delete_orphan`, `increment_retry`
- [ ] Dagster job fetches eligible orphans with backoff logic
- [ ] Successful retry deletes from orphaned_chains
- [ ] Failed retry increments count and updates last_retry_at
- [ ] Exhausted chains trigger alert/metric
- [ ] Metrics added: ORPHAN_CHAINS_EXHAUSTED, ORPHAN_CHAINS_RECOVERED
- [ ] Hourly schedule registered
- [ ] Uses `datetime.now(UTC)` consistently

---

## Bonus: json-repair dependency

Add missing dependency that causes extraction failures:

**`pyproject.toml`:**
```toml
# JSON
"orjson>=3.9",
"json-repair>=0.28",
```

**Status:** Already added.

---

## Out of scope

- Multi-store EpistemicStore implementations (only Memgraph for now)
- Automatic orphan alerting integrations (Slack, PagerDuty) - just metrics/logs
- Session tracking for MCP tools other than recall
- Full transaction support for HyperGraphStore (use existing pattern)

---

## Testing

1. **Evidence accessibility:** 
   - Create chain with evidence, verify it passes Layer 3 after evidence accessed
   - Create chain with no evidence, verify still passes
   - Test fallback when session tracking incomplete
   - Verify ACCESSED_BY edges created (not property overwrites)
   - Test multi-session access to same node

2. **EpistemicStore:**
   - Unit tests for each protocol method
   - Integration test: synthesis produces same results via protocol as direct Cypher
   - Test feature flag toggle
   - Test transaction rollback on partial failure

3. **Orphan recovery:**
   - Mock Memgraph failure, verify chain lands in orphaned_chains
   - Mock recovery success, verify chain deleted from table
   - Verify backoff timing logic
   - Verify exhaustion alert fires
   - Verify metrics increment correctly

---

## Rollout

Single PR, tested incrementally:
1. Evidence fix first (can ship independently if needed)
2. EpistemicStore migration with feature flag (flag off by default)
3. Orphan recovery job (can ship independently)

**Rollback plan:**
- Evidence fix: Revert query changes, stub returns empty set again (safe but re-inverts incentive)
- EpistemicStore: Toggle feature flag off, synthesis uses legacy direct queries
- Orphan recovery: Disable Dagster schedule, orphans accumulate (no worse than status quo)

All three should land together for clean review, but each is independently valuable and reversible.
