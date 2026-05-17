# Epistemic Layer Fixes

**Date:** 2026-05-17
**Status:** Draft
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

## Issue 1: Evidence Accessibility Fix

### Problem

`get_accessible_evidence()` in `chain_applicability.py` returns empty set. The logic `evidence_used.issubset(accessible)` means only chains with NO evidence pass Layer 3. This inverts the incentive - agents who correctly ground reasoning in evidence get penalized with no chain reuse.

### Solution

Implement session-scoped evidence accessibility.

**`engine/queries.py`** - add query:
```python
GET_SESSION_ACCESSIBLE_EVIDENCE = """
MATCH (n:Node {silo_id: $silo_id})
WHERE n.session_id = $session_id 
   OR n.accessed_by_session = $session_id
RETURN n.id AS node_id
"""

MARK_NODE_ACCESSED = """
MATCH (n:Node {id: $node_id, silo_id: $silo_id})
SET n.accessed_by_session = $session_id
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

async def get_accessible_evidence(silo_id: str, session_id: str) -> set[str]:
    """Return evidence node IDs accessible within this session context.
    
    Queries nodes that were:
    1. Created by this session (agent authored)
    2. Retrieved/accessed during this session (tracked via recall)
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
# After retrieving nodes, mark them as accessed by this session
for node in retrieved_nodes:
    await store.execute_write(
        queries.MARK_NODE_ACCESSED,
        {"node_id": str(node.id), "silo_id": silo_id, "session_id": session_id}
    )
```

### Done criteria

- [ ] Chains WITH evidence can pass Layer 3 when evidence was accessed in session
- [ ] Chains WITHOUT evidence still pass (unchanged behavior)
- [ ] Recall marks nodes as accessed
- [ ] Fallback to silo-wide on session tracking gaps

## Issue 2: EpistemicStore Abstraction

### Problem

`synthesis.py` has ~10 direct `execute_query`/`execute_write` calls bypassing `HyperGraphStore` protocol. This couples synthesis to Memgraph's Cypher dialect - swapping graph stores requires rewriting synthesis.

### Solution

New protocol layer for CITE-domain operations.

**`engine/protocols.py`** - add protocol:
```python
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
    
    async def assign_facts_to_cluster(
        self, silo_id: str, fact_ids: list[str], cluster_id: str
    ) -> None: ...
    
    # Belief synthesis
    async def create_proposed_belief(
        self, silo_id: str, content: str, about_ids: list[str], 
        confidence: float, reasoning: str | None
    ) -> str: ...
    
    async def link_synthesis_edge(
        self, from_id: str, to_id: str, edge_type: str, silo_id: str
    ) -> None: ...
    
    # Commitment operations
    async def get_commitments_about(
        self, silo_id: str, node_ids: list[str]
    ) -> list[dict[str, Any]]: ...
    
    async def promote_to_commitment(
        self, silo_id: str, belief_id: str
    ) -> None: ...
    
    # Contradiction detection
    async def find_contradicting_beliefs(
        self, silo_id: str, content: str, threshold: float = 0.8
    ) -> list[dict[str, Any]]: ...
```

**`engine/epistemic_store.py`** - implementation:
```python
class MemgraphEpistemicStore:
    """EpistemicStore implementation backed by Memgraph via HyperGraphStore."""
    
    def __init__(self, graph_store: HyperGraphStore):
        self._store = graph_store
    
    async def get_fact_cluster(self, silo_id: str, cluster_id: str) -> list[dict]:
        return await self._store.execute_query(
            queries.GET_FACT_CLUSTER,
            {"silo_id": silo_id, "cluster_id": cluster_id}
        )
    
    async def get_unclustered_facts(self, silo_id: str, limit: int = 100) -> list[dict]:
        return await self._store.execute_query(
            queries.GET_UNCLUSTERED_FACTS,
            {"silo_id": silo_id, "limit": limit}
        )
    
    # ... remaining methods follow same pattern
```

**`engine/queries.py`** - add queries (extract from synthesis.py):
```python
GET_FACT_CLUSTER = """
MATCH (f:Fact {silo_id: $silo_id})-[:IN_CLUSTER]->(c:Cluster {id: $cluster_id})
RETURN f.id, f.content, f.confidence
"""

GET_UNCLUSTERED_FACTS = """
MATCH (f:Fact {silo_id: $silo_id})
WHERE NOT (f)-[:IN_CLUSTER]->()
RETURN f.id, f.content, f.confidence
LIMIT $limit
"""

# ... ~8 more queries extracted from synthesis.py
```

**Migration in `synthesis.py`:**
```python
# Before
rows = await store.execute_query("""
    MATCH (f:Fact {silo_id: $silo_id})-[:IN_CLUSTER]->(c:Cluster {id: $cluster_id})
    RETURN f.id, f.content, f.confidence
""", {"silo_id": silo_id, "cluster_id": cluster_id})

# After  
rows = await epistemic_store.get_fact_cluster(silo_id, cluster_id)
```

### Done criteria

- [ ] EpistemicStore protocol defined in protocols.py
- [ ] MemgraphEpistemicStore implementation complete
- [ ] All ~10 synthesis.py Cypher calls migrated to protocol methods
- [ ] Queries extracted to queries.py
- [ ] synthesis.py has zero direct execute_query/execute_write calls
- [ ] Tests pass with new abstraction

## Issue 3: Orphan Chain Recovery Job

### Problem

`orphaned_chains` table accumulates during Memgraph issues. No recovery mechanism - chains exist in Postgres but are invisible to graph traversal, evidence linking, and session history.

### Solution

Dagster scheduled job with exponential backoff.

**Schema addition** (`models/postgres/reasoning.py`):
```python
class OrphanedChain(Base):
    __tablename__ = "orphaned_chains"
    
    id: Mapped[UUID] = mapped_column(primary_key=True)
    chain_id: Mapped[UUID] = mapped_column(index=True)
    silo_id: Mapped[UUID]
    error: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    # New fields
    retry_count: Mapped[int] = mapped_column(default=0)
    last_retry_at: Mapped[datetime | None] = mapped_column(default=None)
```

**Migration:** Add `retry_count` and `last_retry_at` columns.

**`pipelines/jobs/orphan_recovery.py`:**
```python
from dagster import job, op, schedule, OpExecutionContext, Out, Output
from datetime import datetime, timedelta
import structlog

log = structlog.get_logger(__name__)

MAX_RETRIES = 5
BASE_BACKOFF_MINUTES = 5

def backoff_elapsed(retry_count: int, last_retry_at: datetime | None) -> bool:
    """Check if enough time has passed for next retry."""
    if last_retry_at is None:
        return True
    wait_minutes = (2 ** retry_count) * BASE_BACKOFF_MINUTES
    return datetime.utcnow() > last_retry_at + timedelta(minutes=wait_minutes)

@op(out={"eligible": Out(), "exhausted": Out()})
def fetch_orphaned_chains(context: OpExecutionContext):
    """Fetch chains eligible for retry and those exhausted."""
    from context_service.db.postgres import get_session
    
    async def _fetch():
        async with get_session() as session:
            result = await session.execute(
                select(OrphanedChain).where(OrphanedChain.retry_count < MAX_RETRIES)
            )
            chains = result.scalars().all()
            
            eligible = [c for c in chains if backoff_elapsed(c.retry_count, c.last_retry_at)]
            
            exhausted_result = await session.execute(
                select(OrphanedChain).where(OrphanedChain.retry_count >= MAX_RETRIES)
            )
            exhausted = exhausted_result.scalars().all()
            
            return eligible, exhausted
    
    eligible, exhausted = asyncio.run(_fetch())
    yield Output(eligible, output_name="eligible")
    yield Output(exhausted, output_name="exhausted")

@op
def retry_chains_to_memgraph(context: OpExecutionContext, eligible: list) -> dict:
    """Attempt to write chain projections to Memgraph."""
    from context_service.engine.memgraph_store import MemgraphStore
    
    results = {"success": 0, "failed": 0}
    
    async def _retry():
        from context_service.mcp.server import get_context_service
        ctx = get_context_service()
        store = ctx._memgraph
        
        for orphan in eligible:
            try:
                # Fetch full chain from Postgres
                chain_data = await fetch_chain_from_postgres(orphan.chain_id)
                # Write projection to Memgraph
                await store.upsert_reasoning_chain_projection(chain_data)
                # Success - delete from orphaned_chains
                await delete_orphan(orphan.id)
                results["success"] += 1
                log.info("orphan_chain_recovered", chain_id=str(orphan.chain_id))
            except Exception as e:
                # Failure - increment retry count
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
    
    # Metric for alerting
    from context_service.telemetry.metrics import ORPHAN_CHAINS_EXHAUSTED
    ORPHAN_CHAINS_EXHAUSTED.inc(len(exhausted))

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

- [ ] Schema migration adds retry_count, last_retry_at columns
- [ ] Dagster job fetches eligible orphans with backoff logic
- [ ] Successful retry deletes from orphaned_chains
- [ ] Failed retry increments count
- [ ] Exhausted chains trigger alert/metric
- [ ] Hourly schedule registered

## Bonus: json-repair dependency

Add missing dependency that causes extraction failures:

**`pyproject.toml`:**
```toml
# JSON
"orjson>=3.9",
"json-repair>=0.28",
```

## Out of scope

- Multi-store EpistemicStore implementations (only Memgraph for now)
- Automatic orphan alerting integrations (Slack, PagerDuty) - just metrics/logs
- Session tracking for MCP tools other than recall

## Testing

1. **Evidence accessibility:** 
   - Create chain with evidence, verify it passes Layer 3 after evidence accessed
   - Create chain with no evidence, verify still passes
   - Test fallback when session tracking incomplete

2. **EpistemicStore:**
   - Unit tests for each protocol method
   - Integration test: synthesis produces same results via protocol as direct Cypher

3. **Orphan recovery:**
   - Mock Memgraph failure, verify chain lands in orphaned_chains
   - Mock recovery success, verify chain deleted from table
   - Verify backoff timing logic
   - Verify exhaustion alert fires

## Rollout

Single PR, tested incrementally:
1. Evidence fix first (can ship independently if needed)
2. EpistemicStore migration (all or nothing)
3. Orphan recovery job (can ship independently)

All three should land together for clean review, but each is independently valuable.
