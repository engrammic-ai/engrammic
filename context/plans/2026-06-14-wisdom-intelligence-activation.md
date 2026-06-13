# Wisdom/Intelligence Layer Activation

**Date:** 2026-06-14
**Scope:** Improve agent utilization of Wisdom and Intelligence layers
**Effort:** ~2.5 days

## Problem

Wisdom and Intelligence layers are implemented but underutilized:
- Agents default to `remember`/`learn`, rarely use `decide`/`hypothesize`/`reason`
- SAGE synthesizer runs every 30 min - too slow for interactive sessions
- Reasoning chains stored but not surfaced at recall time
- No signals telling agents "now is a good time to form a belief"

## Solution: Four-Part Activation

### Part 1: Synthesis Hints in Recall (Option A)

Add `hints` field to recall response when conditions suggest higher-layer operations.

**File:** `src/context_service/sage/recall.py`

**New dataclass:**
```python
@dataclass
class RecallHint:
    """Hint suggesting an action based on recall results."""
    
    hint_type: str  # "belief_candidate" | "chain_continuation" | "stale_commitment"
    message: str
    node_ids: list[str] = field(default_factory=list)
    suggested_action: str | None = None  # e.g. "decide(about=[...])"


@dataclass 
class RecallResponse:
    """Extended recall response with hints."""
    
    results: list[RecallResultItem]
    hints: list[RecallHint] = field(default_factory=list)
```

**Extend existing query in `db/queries.py`:**
```python
# Existing GET_CLUSTERS_FOR_NODES needs fact_count and fact_ids for hints
GET_CLUSTERS_FOR_NODES_WITH_FACTS = """
MATCH (n {silo_id: $silo_id})-[:MEMBER_OF]->(cluster:Cluster)
WHERE n.id IN $node_ids
WITH cluster, collect(n.id) AS matching_ids
OPTIONAL MATCH (f:Fact {silo_id: $silo_id})-[:MEMBER_OF]->(cluster)
WITH cluster, matching_ids, collect(f.id) AS all_fact_ids
RETURN cluster.id AS cluster_id,
       cluster.state AS state,
       cluster.current_belief_id AS current_belief_id,
       size(all_fact_ids) AS fact_count,
       all_fact_ids[0..5] AS fact_ids
"""
```

**Detection logic (add to `recall()`):**
```python
async def _detect_belief_candidates(
    store: HyperGraphStore,
    results: list[RecallResultItem],
    silo_id: str,
) -> list[RecallHint]:
    """Detect when facts cluster enough to suggest belief formation."""
    hints = []
    
    # Group knowledge-layer results by cluster
    knowledge_results = [r for r in results if r.layer == Layer.KNOWLEDGE]
    if len(knowledge_results) < 3:
        return hints
    
    # Check if 3+ facts share a cluster without existing belief
    cluster_result = await store.execute_query(
        q.GET_CLUSTERS_FOR_NODES_WITH_FACTS,
        {"silo_id": silo_id, "node_ids": [r.node_id for r in knowledge_results]},
    )
    
    for cluster in cluster_result:
        fact_count = cluster.get("fact_count", 0)
        has_belief = cluster.get("current_belief_id") is not None
        
        # Skip if cluster will be lazily synthesized (READY/STALE state)
        # to avoid redundant "form a belief" + inline synthesis
        cluster_state = cluster.get("state")
        if cluster_state in ("READY", "STALE"):
            continue
            
        if fact_count >= 3 and not has_belief:
            fact_ids = cluster.get("fact_ids", [])[:5]
            hints.append(RecallHint(
                hint_type="belief_candidate",
                message=f"{fact_count} corroborating facts found. Consider forming a belief.",
                node_ids=fact_ids,
                suggested_action=f"decide(decision='...', about={fact_ids[:3]})",
            ))
    
    return hints
```

**Wire into recall response (parallel detection):**
```python
# At end of recall(), before return:
from context_service.config.settings import get_settings
from context_service.mcp.server import get_qdrant_client

hints: list[RecallHint] = []
if get_settings().recall_hints_enabled:
    qdrant = get_qdrant_client()
    
    # Run detection in parallel (chain detection uses threadpool for sync qdrant)
    belief_hints, chain_hints = await asyncio.gather(
        _detect_belief_candidates(store, results, silo_id),
        asyncio.to_thread(_detect_chain_continuations, qdrant, query_embedding, silo_id),
    )
    hints = belief_hints + chain_hints

return RecallResponse(results=results, hints=hints)
```

**Add to settings.py:**
```python
recall_hints_enabled: bool = Field(
    default=False,  # Start disabled for safe rollout
    description="Enable recall hints for wisdom/intelligence layer suggestions"
)
```

### Part 2: Chain Continuation Hints (Option C)

Surface relevant prior reasoning chains at recall time.

**Note:** ReasoningChain nodes don't store embeddings directly. Use Qdrant to find chains by conclusion similarity, then fetch metadata from graph.

**Qdrant collection:** `reasoning_chains` (already exists per context_store.py line 50)

**Detection logic:**
```python
def _detect_chain_continuations(
    qdrant: QdrantClient,  # Sync wrapper from context_service.stores
    query_embedding: list[float],
    silo_id: str,
) -> list[RecallHint]:
    """Find reasoning chains whose conclusions are relevant to this query."""
    if not query_embedding:
        return []
    
    # Search Qdrant for similar chain conclusions (sync call, runs in threadpool)
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    
    results = qdrant.search(
        collection_name="reasoning_chains",
        query_vector=query_embedding,
        query_filter=Filter(
            must=[FieldCondition(key="silo_id", match=MatchValue(value=silo_id))]
        ),
        limit=3,
        score_threshold=0.7,
    )
    
    hints = []
    for point in results:
        chain_id = point.payload.get("chain_id")
        conclusion = point.payload.get("conclusion", "")[:100]
        
        hints.append(RecallHint(
            hint_type="chain_continuation",
            message=f"Prior reasoning: \"{conclusion}...\"",
            node_ids=[chain_id],
            suggested_action=f"reason(steps=[...], parent_chain_id='{chain_id}')",
        ))
    
    return hints
```

**Note:** MCP server uses sync QdrantClient wrapper. For async, wrap in `asyncio.to_thread()` or use `run_in_executor`.

### Part 3: Skill Guidance Update (Option E)

Update EAG agent instructions with explicit triggers.

**File:** `context/brainstorm/2026-05-10-eag-agent-instructions.md`

**Add new section after "Part 2: The Four Layers":**

```markdown
---

## Part 2.5: When to Level Up

### Memory -> Knowledge

**Trigger:** You have a claim with evidence.

```
# Instead of:
remember("The API uses OAuth2")

# Do:
learn("The API uses OAuth2", evidence=["file://src/auth/config.py:15"])
```

### Knowledge -> Wisdom

**Trigger:** You've stored 2+ related facts and see a pattern.

```
# After storing facts about API auth:
recall("API authentication")
# Response shows 3 facts about OAuth2 + PKCE

# Form the belief:
decide(
    decision="Our API authentication uses OAuth2 with PKCE for all client types",
    about=["fact-id-1", "fact-id-2", "fact-id-3"]
)
```

**Watch for hints:** Recall may return `hints.belief_candidate` suggesting this.

### Working Through Problems -> Intelligence

**Trigger:** Multi-step reasoning where you want to preserve the chain.

```
reason(
    steps=[
        {"step": 1, "reasoning": "User reports 500 errors on /api/users"},
        {"step": 2, "reasoning": "Logs show DB connection timeout"},
        {"step": 3, "reasoning": "Connection pool exhausted - max_connections=10"},
    ],
    conclusion="Need to increase DB connection pool size",
    evidence_used=["memory-id-logs", "fact-id-config"]
)
```

**Continue prior chains:** If recall returns `hints.chain_continuation`, you can extend it:
```
reason(
    steps=[{"step": 4, "reasoning": "Increased pool to 50, errors resolved"}],
    parent_chain_id="prior-chain-id"
)
```

### Tentative -> Committed

**Trigger:** Uncertain conclusion that may change.

```
# Form tentative belief:
hypothesize(
    hypothesis="The memory leak is in the event handler",
    about=["fact-id-heap-dump"]
)
# Returns: {belief_id: "hyp-123", session_id: "..."}

# Later, after confirming:
commit(belief_ids=["hyp-123"])
```

Hypotheses expire with the session. Commit before ending if you want them to persist.
```

**Also update the MCP server instructions in `src/context_service/config/mcp_tools.yaml`:**

Add hints to tool descriptions where relevant.

### Part 4: Response Format Changes

**File:** `src/context_service/mcp/tools/recall.py`

Update return format to include hints:

```python
response = {
    "results": [...],
    "total_results": len(results),
    # New field:
    "hints": [
        {
            "type": h.hint_type,
            "message": h.message,
            "node_ids": h.node_ids,
            "action": h.suggested_action,
        }
        for h in hints
    ] if hints else None,
}
```

### Part 5: Auto-Capture Reasoning from decide()

When `decide()` is called with a `reasoning` parameter, automatically create a ReasoningChain and link it to the Commitment.

**File:** `src/context_service/mcp/tools/decide.py`

**Changes to `_decide_impl()`:**
```python
async def _decide_impl(
    decision: str,
    about: list[str],
    confidence: float = 0.8,
    reasoning: str | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    # ... existing validation ...
    
    silo_uuid = derive_silo_id(auth.org_id)
    silo_id = str(silo_uuid)
    
    # Create commitment FIRST (primary artifact)
    result, events = await tx_commit(...)
    
    # Auto-create reasoning chain if reasoning provided (supplementary)
    chain_id: uuid.UUID | None = None
    if reasoning:
        from context_service.engine.chain_saga import ChainSagaWriter
        from context_service.models.inference import ChainStep
        
        chain_id = uuid.uuid4()
        saga = ChainSagaWriter(ctx_svc.postgres_store, ctx_svc.graph_store)
        
        try:
            await saga.write_chain(
                chain_id=chain_id,
                silo_id=silo_uuid,
                steps=[
                    ChainStep(
                        step_index=0,
                        operation="decide",
                        conclusion=reasoning,
                        confidence=confidence,
                        premise_refs=about,  # Link to evidence
                    )
                ],
                produced_by_model="agent",
                produced_by_agent_id=agent_id,
                status="committed",
                source="decide_reasoning",
                conclusion=decision,
                evidence_used=about,
            )
            
            # Link chain to commitment
            await ctx_svc.graph_store.execute_write(
                q.LINK_CHAIN_TO_COMMITMENT,
                {
                    "chain_id": str(chain_id),
                    "commitment_id": str(result.commitment_id),
                    "silo_id": silo_id,
                },
            )
            
            # Embed chain conclusion for retrieval (inline, same as _context_reason)
            from context_service.mcp.tools.context_store import _upsert_chain_embedding, embed
            
            try:
                conclusion_embedding = await embed(decision)
                await _upsert_chain_embedding(
                    chain_id,
                    silo_id,
                    conclusion_embedding,
                    evidence_used=about,
                )
            except Exception:
                logger.warning("decide_chain_embedding_failed", chain_id=str(chain_id))
        except Exception as exc:
            # Chain write failed - commitment still valid, log and continue
            logger.warning("decide_chain_write_failed", error=str(exc))
            chain_id = None
    
    response = {
        "commitment_id": str(result.commitment_id),
        ...
    }
    if chain_id:
        response["chain_id"] = str(chain_id)
    
    return response
```

**Note:** Commitment-first ordering ensures the primary artifact is created even if chain write fails. Chain is supplementary provenance.

**New query in `db/queries.py`:**
```python
LINK_CHAIN_TO_COMMITMENT = """
MATCH (chain:ReasoningChain {id: $chain_id, silo_id: $silo_id})
MATCH (c:Commitment {id: $commitment_id, silo_id: $silo_id})
MERGE (chain)-[:CRYSTALLIZED_INTO]->(c)
"""
```

**Effort:** 2 hours

## Implementation Order

1. **Part 3 first** (30 min) - Update skill docs, immediate impact, no code risk
2. **Part 5 next** (2 hrs) - Auto-capture reasoning from decide() - quick win, populates Intelligence layer
3. **Part 4** (1 hr) - Wire response format with hints array
4. **Part 1** (3 hrs) - Add belief candidate detection
5. **Part 2** (2 hrs) - Add chain continuation detection (uses Qdrant reasoning_chains)

**Rationale:** Part 5 early because it populates the Intelligence layer - chain continuation hints (Part 2) are useless without chains to continue. Part 3 first because it's zero-risk docs.

## Testing

```python
# test_recall_hints.py

async def test_belief_candidate_hint_when_cluster_ready():
    """Recall suggests decide() when 3+ facts cluster without belief."""
    # Store 3 related facts
    # Recall with query matching them
    # Assert hints contains belief_candidate

async def test_chain_continuation_hint():
    """Recall suggests continuing prior reasoning chain."""
    # Create chain with conclusion
    # Recall with query similar to conclusion
    # Assert hints contains chain_continuation

async def test_no_hints_when_belief_exists():
    """No belief_candidate hint when cluster already has belief."""
    # Store facts + create belief from them
    # Recall
    # Assert no belief_candidate hint

# test_decide_reasoning_capture.py

async def test_decide_with_reasoning_creates_chain():
    """decide(reasoning=...) auto-creates linked ReasoningChain."""
    result = await decide(
        decision="Use React for frontend",
        about=["fact-1", "fact-2"],
        reasoning="Benchmarks show React 19 is faster, team has experience"
    )
    assert "chain_id" in result
    # Verify chain exists and links to commitment
    
async def test_decide_without_reasoning_no_chain():
    """decide() without reasoning doesn't create chain."""
    result = await decide(decision="...", about=["..."])
    assert "chain_id" not in result
```

## Success Criteria

1. Recall response includes `hints` when conditions are met
2. Agents see actionable suggestions in recall results
3. Skill docs provide clear "when to use" guidance
4. No recall latency regression >50ms from hint detection
5. `decide(reasoning="...")` auto-creates linked ReasoningChain
6. Chain continuation hints surface prior reasoning in recall

## Future (Phase 2)

Once we validate agents use hints:
- **Reactive synthesis** - Create ProposedBelief inline when cluster reaches threshold
- **Auto-hypothesis from chains** - Create WorkingHypothesis when chain has conclusion
- **Confidence decay prompts** - "Your belief X hasn't been reinforced in 30 days"
- **TaskIQ chain embedding** - Extend COMPUTE_EMBEDDING handler to support `reasoning_chains` collection for async embedding (currently inline)
