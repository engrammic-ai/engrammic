# V2 Synthesis Trigger

**Date:** 2026-06-20
**Status:** Spec
**Goal:** Complete the CITE v2 migration by implementing direct fact-to-belief synthesis without clusters
**Depends on:** Recall consolidation (wires this into the read path)

## Background

CITE v2 removed clustering (Leiden, `:Cluster` nodes, `:MEMBER_OF` edges) but left the synthesis trigger unimplemented:

```
v1: Facts → Clusters (Leiden) → Belief (when cluster density threshold met)
v2: Facts → Belief (when corroboration threshold met) [NOT IMPLEMENTED]
```

Current state:
- `synthesize()` in `sage/transactions.py` still expects `cluster_id`
- All cluster queries stubbed to return null
- No trigger for "when should synthesis happen"

## V2 Synthesis Model

### Trigger Condition

Synthesis should trigger when:
1. **N+ Facts** share the same (subject, predicate) pattern
2. **M+ distinct evidence sources** across those Facts (corroboration)
3. **No existing Belief** covers those Facts (via `SYNTHESIZED_FROM`)

Default thresholds:
- `FACT_COUNT_THRESHOLD = 3` — minimum facts to form belief
- `EVIDENCE_THRESHOLD = 3` — minimum distinct evidence sources (already `PROMOTION_THRESHOLD`)

### Entry Points

1. **Custodian batch** — periodic scan for synthesis-ready fact groups
2. **Inline on recall** — when recall returns facts meeting criteria, trigger async
3. **On fact promotion** — when Claim→Fact, check if new group meets threshold

## New Components

### 1. Query: GET_SYNTHESIS_CANDIDATES

Find fact groups ready for synthesis:

```cypher
// Find facts grouped by (subject, predicate) that:
// - Have 3+ facts in the group
// - Have 3+ distinct evidence sources
// - Don't already have a Belief

MATCH (f:Fact {silo_id: $silo_id})
WHERE f.state = 'ACTIVE'
  AND NOT EXISTS {
    MATCH (f)<-[:SYNTHESIZED_FROM]-(b:Belief)
    WHERE b.state = 'ACTIVE'
  }
WITH f.subject AS subject, f.predicate AS predicate, collect(f) AS facts
WHERE size(facts) >= $fact_threshold

// Count distinct evidence sources
UNWIND facts AS fact
UNWIND fact.evidence AS ev
WITH subject, predicate, facts, collect(DISTINCT ev) AS all_evidence
WHERE size(all_evidence) >= $evidence_threshold

RETURN subject, predicate, 
       [f IN facts | f.id] AS fact_ids,
       size(facts) AS fact_count,
       size(all_evidence) AS evidence_count
ORDER BY evidence_count DESC
LIMIT $limit
```

### 2. Query: GET_SYNTHESIS_CANDIDATES_FOR_NODES

Same as above but filtered to specific node_ids (for inline recall trigger):

```cypher
MATCH (f:Fact {silo_id: $silo_id})
WHERE f.id IN $node_ids
  AND f.state = 'ACTIVE'
  AND NOT EXISTS {
    MATCH (f)<-[:SYNTHESIZED_FROM]-(b:Belief)
    WHERE b.state = 'ACTIVE'
  }
WITH f.subject AS subject, f.predicate AS predicate, collect(f) AS facts
WHERE size(facts) >= $fact_threshold

UNWIND facts AS fact
UNWIND fact.evidence AS ev
WITH subject, predicate, facts, collect(DISTINCT ev) AS all_evidence
WHERE size(all_evidence) >= $evidence_threshold

RETURN subject, predicate,
       [f IN facts | f.id] AS fact_ids,
       size(facts) AS fact_count,
       size(all_evidence) AS evidence_count
```

### 3. Function: synthesize_from_facts()

New synthesis function that takes fact_ids directly:

```python
async def synthesize_from_facts(
    store: HyperGraphStore,
    fact_ids: list[str],
    silo_id: str,
    llm: LLMProvider,
    *,
    mode: Literal["async", "sync"] = "async",
    timeout_seconds: float = 30.0,
) -> tuple[SynthesizeResult, list[ReactionEvent]]:
    """Create ProposedBelief from corroborating facts (v2).
    
    Unlike v1 synthesize(), this takes fact_ids directly instead of cluster_id.
    Enforces INV3: Every Belief has >= N SYNTHESIZED_FROM to ACTIVE Facts.
    
    Args:
        fact_ids: List of Fact node IDs to synthesize from.
        silo_id: Tenant isolation ID.
        llm: LLM provider for synthesis.
        mode: "async" (30s timeout) or "sync" (2s for query-time).
        timeout_seconds: Override timeout.
    
    Returns:
        SynthesizeResult with belief_id if successful.
    """
    effective_timeout = 2.0 if mode == "sync" else timeout_seconds
    
    # Validate minimum facts
    if len(fact_ids) < SYNTHESIS_THRESHOLD:
        return SynthesizeResult(
            belief_id=None,
            fact_count=len(fact_ids),
            confidence=None,
        ), []
    
    # Fetch fact content
    facts = await store.execute_query(
        q.GET_FACTS_BY_IDS,
        {"fact_ids": fact_ids, "silo_id": silo_id},
    )
    
    if not facts or len(facts) < SYNTHESIS_THRESHOLD:
        return SynthesizeResult(
            belief_id=None,
            fact_count=len(facts) if facts else 0,
            confidence=None,
        ), []
    
    # Aggregate confidence
    confidences = [f.get("confidence", 1.0) for f in facts]
    aggregate_confidence = sum(confidences) / len(confidences)
    
    # Call LLM
    synthesis_result = await llm_synthesize(llm, facts, effective_timeout)
    
    if synthesis_result.timed_out or not synthesis_result.success:
        return SynthesizeResult(
            belief_id=None,
            fact_count=len(facts),
            confidence=aggregate_confidence,
            timed_out=synthesis_result.timed_out,
        ), []
    
    # Create ProposedBelief with SYNTHESIZED_FROM edges
    belief_id = uuid.uuid4()
    created_at = datetime.now(UTC)
    expires_at = created_at + timedelta(days=7)
    
    await store.execute_write(
        q.CREATE_PROPOSED_BELIEF_V2,
        {
            "id": str(belief_id),
            "silo_id": silo_id,
            "content": synthesis_result.content,
            "confidence": aggregate_confidence,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "fact_ids": fact_ids,
        },
    )
    
    events = [
        ReactionEvent(
            event_type=ReactionEventType.COMPUTE_EMBEDDING,
            node_id=str(belief_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type=ReactionEventType.PROPOSAL_READY,
            node_id=str(belief_id),
            silo_id=silo_id,
        ),
    ]
    
    return SynthesizeResult(
        belief_id=str(belief_id),
        fact_count=len(facts),
        confidence=aggregate_confidence,
    ), events
```

### 4. Query: CREATE_PROPOSED_BELIEF_V2

```cypher
// Create ProposedBelief and link to Facts via SYNTHESIZED_FROM
CREATE (pb:Node:ProposedBelief {
    id: $id,
    silo_id: $silo_id,
    content: $content,
    confidence: $confidence,
    status: 'pending',
    created_at: datetime($created_at),
    expires_at: datetime($expires_at)
})
WITH pb
UNWIND $fact_ids AS fid
MATCH (f:Fact {id: fid, silo_id: $silo_id})
CREATE (pb)-[:SYNTHESIZED_FROM]->(f)
RETURN pb.id AS id
```

### 5. Query: GET_FACTS_BY_IDS

```cypher
MATCH (f:Fact {silo_id: $silo_id})
WHERE f.id IN $fact_ids
  AND f.state = 'ACTIVE'
RETURN f.id AS fact_id,
       f.content AS content,
       f.confidence AS confidence,
       f.subject AS subject,
       f.predicate AS predicate,
       f.object AS object
```

## Integration with Recall

### Lazy Synthesis (in retrieval/epistemic.py)

```python
async def maybe_trigger_synthesis(
    results: list[FusedResult],
    silo_id: str,
    store: HyperGraphStore,
    llm: Any,
) -> bool:
    """Check if recall results contain synthesis-ready fact groups."""
    
    # Filter to Facts only
    fact_ids = [
        r.node_id for r in results
        if r.layer and r.layer.upper() == "KNOWLEDGE"
    ]
    
    if len(fact_ids) < SYNTHESIS_THRESHOLD:
        return False
    
    # Find synthesis candidates among these facts
    candidates = await store.execute_query(
        q.GET_SYNTHESIS_CANDIDATES_FOR_NODES,
        {
            "silo_id": silo_id,
            "node_ids": fact_ids,
            "fact_threshold": SYNTHESIS_THRESHOLD,
            "evidence_threshold": PROMOTION_THRESHOLD,
        },
    )
    
    if not candidates:
        return False
    
    # Fire-and-forget synthesis for each candidate group
    synthesis_pending = False
    for candidate in candidates:
        candidate_fact_ids = candidate.get("fact_ids", [])
        if len(candidate_fact_ids) >= SYNTHESIS_THRESHOLD:
            _fire_and_forget(
                synthesize_from_facts(store, candidate_fact_ids, silo_id, llm)
            )
            synthesis_pending = True
    
    return synthesis_pending
```

### Belief Candidate Hints

```python
async def _detect_belief_candidates(
    store: HyperGraphStore,
    results: list[FusedResult],
    silo_id: str,
) -> list[RecallHint]:
    """Detect when recalled facts could form a belief."""
    
    fact_ids = [
        r.node_id for r in results
        if r.layer and r.layer.upper() == "KNOWLEDGE"
    ]
    
    if len(fact_ids) < 3:
        return []
    
    # Find corroborating groups
    candidates = await store.execute_query(
        q.GET_SYNTHESIS_CANDIDATES_FOR_NODES,
        {
            "silo_id": silo_id,
            "node_ids": fact_ids,
            "fact_threshold": 3,
            "evidence_threshold": 3,
        },
    )
    
    hints = []
    for candidate in candidates:
        hints.append(RecallHint(
            hint_type="belief_candidate",
            message=f"{candidate['fact_count']} corroborating facts about '{candidate['predicate']}'. Consider forming a belief.",
            node_ids=candidate["fact_ids"][:5],
            suggested_action=f"decide(decision='...', about={candidate['fact_ids'][:3]})",
        ))
    
    return hints
```

## Migration Steps

### Step 1: Add v2 queries (30m)

Add to `db/queries.py`:
- `GET_SYNTHESIS_CANDIDATES`
- `GET_SYNTHESIS_CANDIDATES_FOR_NODES`
- `GET_FACTS_BY_IDS`
- `CREATE_PROPOSED_BELIEF_V2`

### Step 2: Add synthesize_from_facts() (1h)

Add to `sage/transactions.py`:
- New `synthesize_from_facts()` function
- Keep old `synthesize()` for backwards compat (deprecation warning)

### Step 3: Update SynthesizeResult (15m)

Remove `cluster_id` and `cluster_state` fields (or make optional with deprecation).

### Step 4: Wire into recall pipeline (30m)

Update `retrieval/epistemic.py`:
- `maybe_trigger_synthesis()` uses new queries
- `_detect_belief_candidates()` uses new queries

### Step 5: Update Custodian batch (1h)

Update `custodian/proposal_worker.py` or Dagster asset:
- Replace cluster-based candidate detection with `GET_SYNTHESIS_CANDIDATES`
- Call `synthesize_from_facts()` instead of `synthesize()`

### Step 6: Cleanup old code (30m)

- Remove stubbed cluster queries
- Deprecate old `synthesize()` 
- Remove `cluster_id` from `SynthesizeResult`

### Step 7: Tests (1.5h)

- `test_synthesize_from_facts` — creates ProposedBelief with SYNTHESIZED_FROM edges
- `test_get_synthesis_candidates` — finds corroborating fact groups
- `test_lazy_synthesis_trigger` — fires on recall with synthesis-ready facts
- `test_belief_candidate_hints` — surfaces hints for corroborating facts

**Total: ~5-6 hours**

## Combined Effort with Recall Consolidation

| Task | Effort |
|------|--------|
| Recall consolidation (as_of, layer scoring, wiring) | 3h |
| V2 synthesis queries | 30m |
| synthesize_from_facts() | 1h |
| Wire into recall (synthesis + hints) | 1h |
| Custodian update | 1h |
| Cleanup + tests | 2h |
| **Total** | **8-9h** |

## Success Criteria

- `recall()` with 3+ corroborating Facts triggers background synthesis
- `recall(include_hints=True)` surfaces belief candidate hints
- `synthesize_from_facts([fact_ids])` creates ProposedBelief without cluster_id
- Custodian batch finds and synthesizes unsynthesized fact groups
- No references to `:Cluster` or `cluster_id` in active code paths
