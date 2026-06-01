# CITE v2: Epistemology Specification

**Status:** DRAFT  
**Date:** 2026-06-01  
**Supersedes:** `primitives/docs/06-epistemology.md` (deterministic primitives)

## Overview

CITE v2 integrates graph-based confidence propagation, weighted evidence relationships, and subagent-driven consolidation while preserving CITE v1's unique strengths: the four-layer model, provenance invariants, and supersession chains.

### What changes

| Aspect | CITE v1 | CITE v2 |
|--------|---------|---------|
| Confidence | Static formula at write time | Two-factor: credibility (static) + confidence (propagated) |
| Contradiction | Structural detection, binary | Weighted contradiction edges, propagated effects |
| Corroboration | `count(distinct sources)` | Independence-weighted support edges |
| Transitivity | Not modeled | Damped matrix propagation + PPR |
| Conflict resolution | Hardcoded rules | Subagent consolidation with implicit signals |
| Staleness | Binary cascade | Continuous confidence degradation |

### What stays

- Four-layer model (KMWI) with distinct semantics
- Provenance invariants (I1-I6)
- Supersession chains with temporal queries
- Layer-specific decay/persistence rules
- Deterministic primitives where possible (LLM only for consolidation)

---

## 1. Two-Factor Confidence Model

### 1.1 Credibility (source-based, static)

Credibility reflects trust in the source at write time. Computed once, stored on node.

```python
credibility = source_tier * method_weight * raw_confidence
```

| Factor | Values | Source |
|--------|--------|--------|
| `source_tier` | 1.0 authoritative, 0.85 validated, 0.6 community, 0.4 unknown | Agent trust tier, document type |
| `method_weight` | 0.85 validated extractor, 0.75 standard, 0.6 experimental | Extraction method |
| `raw_confidence` | 0.0-1.0 | LLM self-reported score |

### 1.2 Confidence (graph-based, dynamic)

Confidence reflects structural support/contradiction in the graph. Computed via damped iterative propagation.

**Algorithm** (adapted from Belief Graphs):

```python
def propagate_confidence(
    nodes: list[Node],
    support_matrix: np.ndarray,      # A+ (row-normalized)
    contradiction_matrix: np.ndarray, # A- (row-normalized)
    alpha: float = 0.8,               # mixing: prior vs structure
    eta: float = 1.0,                 # contradiction penalty weight
    max_iter: int = 100,
    epsilon: float = 1e-6,
) -> np.ndarray:
    """
    Propagate confidence through graph.
    
    Returns confidence scores for all nodes.
    """
    # Prior is credibility scores
    prior = np.array([n.credibility for n in nodes])
    
    # Initialize confidence to prior
    x = prior.copy()
    
    # Combined matrix: support minus penalized contradiction
    M = support_matrix - eta * contradiction_matrix
    
    for _ in range(max_iter):
        # Damped update: mix prior with propagated scores
        x_new = np.clip((1 - alpha) * prior + alpha * M @ x, 0, 1)
        
        # Convergence check
        if np.max(np.abs(x_new - x)) < epsilon:
            break
        x = x_new
    
    return x
```

**Parameters:**

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `alpha` | 0.8 | How much graph structure vs source credibility matters |
| `eta` | 1.0 | How much contradictions hurt (higher = harsher penalty) |
| `max_iter` | 100 | Convergence limit |
| `epsilon` | 1e-6 | Convergence threshold |

**When to recompute:**

- On write: new node, new edge, node superseded
- Lazy: on query if `confidence_stale` flag set
- Batch: periodic full recomputation (groundskeeper)

### 1.3 Combined Score

For retrieval ranking:

```python
score = similarity * confidence * layer_factor * proximity
```

Where `confidence` is the propagated value, not raw credibility.

---

## 2. Evidence Relationships

### 2.1 Edge Types

| Edge | Direction | Weight | Meaning |
|------|-----------|--------|---------|
| `SUPPORTS` | A -> B | 0.0-1.0 | A provides evidence for B |
| `CONTRADICTS` | A -> B | 0.0-1.0 | A contradicts B |
| `DERIVED_FROM` | B -> A | 1.0 | B is derived from A (provenance) |
| `SYNTHESIZED_FROM` | Belief -> Facts | 1.0 | Belief synthesized from facts |
| `SUPERSEDES` | new -> old | 1.0 | Version chain. Reason: `contradiction`, `evidence_shift`, `author_update`, `evidence_erased`, `resolves_contradiction` |
| `CORROBORATES` | A -> B | weighted | A corroborates B (independence-weighted) |

### 2.2 Support Edge Creation

Support edges are created:
- Explicitly via `link(type='supports', weight=w)`
- Implicitly when facts share evidence sources
- By synthesis (belief supports its source facts transitively)

Weight reflects strength of support (default 1.0).

### 2.3 Contradiction Edge Creation

Contradiction edges are created:
- On structural conflict detection (same s,p different o)
- Explicitly via `link(type='contradicts', weight=w)`
- By consolidation subagent (semantic conflicts)

Weight reflects severity (default 1.0, can be reduced for partial contradictions).

### 2.4 Independence-Weighted Corroboration

Corroboration from the same source tree doesn't count as independent.

```python
def compute_corroboration_weight(
    claim: Node,
    corroborating_claims: list[Node],
) -> float:
    """
    Weight corroboration by source independence.
    
    Same agent, same document, or same evidence chain = not independent.
    """
    sources = defaultdict(list)
    
    for c in corroborating_claims:
        # Group by root source (agent + document + evidence chain root)
        root = get_source_root(c)
        sources[root].append(c)
    
    # Each independent source contributes, diminishing returns within source
    weight = 0.0
    for root, claims in sources.items():
        # First claim from source: full weight
        # Additional claims from same source: diminishing (sqrt)
        source_weight = 1.0 + 0.5 * (math.sqrt(len(claims)) - 1)
        weight += source_weight
    
    # Normalize to 0-1 range with saturation
    return 1 - math.exp(-0.5 * weight)
```

---

## 3. Transitivity

### 3.1 PPR-Based Traversal

For query-time relevance, use Personalized PageRank from query anchors.

```python
def personalized_pagerank(
    graph: Graph,
    query_nodes: list[NodeId],
    alpha: float = 0.85,
    max_iter: int = 100,
) -> dict[NodeId, float]:
    """
    Compute PPR scores from query anchor nodes.
    
    alpha: damping factor (probability of following edges vs teleporting back)
    """
    n = len(graph.nodes)
    
    # Teleport distribution: uniform over query nodes
    teleport = np.zeros(n)
    for qn in query_nodes:
        teleport[graph.node_index(qn)] = 1.0 / len(query_nodes)
    
    # Adjacency matrix (row-normalized)
    adj = graph.normalized_adjacency()
    
    scores = teleport.copy()
    for _ in range(max_iter):
        scores_new = alpha * adj.T @ scores + (1 - alpha) * teleport
        if np.max(np.abs(scores_new - scores)) < 1e-6:
            break
        scores = scores_new
    
    return {graph.nodes[i].id: scores[i] for i in range(n)}
```

### 3.2 Transitive Confidence

Confidence propagation (Section 1.2) handles transitivity implicitly:
- If A supports B and B supports C, A's confidence affects C's
- Damping factor attenuates effect with distance
- Contradictions also propagate (if A contradicts B, and B supports C, C is weakened)

### 3.3 Depth Limiting

For performance:
- Direct edges (depth 1): full weight
- Depth 2-3: attenuated by `alpha^depth`
- Depth 4+: not computed (approximated by PPR cache)

---

## 4. Conflict Detection and Consolidation

### 4.1 Conflict Detection (Write-Time)

On every write, check for conflicts:

```python
def detect_conflicts(
    new_claim: Node,
    silo_id: str,
) -> list[Conflict]:
    """
    Detect structural and semantic conflicts with existing claims.
    """
    conflicts = []
    
    # 1. Structural: same (subject, predicate), different object
    existing = query_by_subject_predicate(new_claim.subject, new_claim.predicate, silo_id)
    for e in existing:
        if e.object != new_claim.object and e.state == 'ACTIVE':
            conflicts.append(Conflict(
                new=new_claim.id,
                existing=e.id,
                type='structural',
                confidence=1.0,  # certain
            ))
    
    # 2. Semantic: high similarity but different assertion (optional, expensive)
    if settings.enable_semantic_conflict_detection:
        similar = query_by_embedding(new_claim.embedding, threshold=0.9, silo_id)
        for s in similar:
            if is_semantically_contradictory(new_claim, s):  # LLM call
                conflicts.append(Conflict(
                    new=new_claim.id,
                    existing=s.id,
                    type='semantic',
                    confidence=0.8,  # uncertain
                ))
    
    return conflicts
```

### 4.2 Optimistic Write + Conflict Flagging

Writes are not blocked by conflicts. Instead:

1. Accept write immediately
2. Create `CONTRADICTS` edge with weight
3. Set `conflict_status='unresolved'` on both nodes
4. Emit `ConflictDetected` event for consolidation queue

### 4.3 Consolidation Subagent

Asynchronous consolidation via LLM subagent:

**Input signals:**

| Signal | How computed |
|--------|--------------|
| `ppr_scores` | PPR centrality of both nodes |
| `confidence` | Propagated confidence of both |
| `credibility` | Source-based credibility of both |
| `recency` | Timestamps |
| `corroboration_count` | Independence-weighted |
| `usage_heat` | Access patterns |
| `agent_track_record` | Historical accuracy of authoring agent |
| `evidence_chain_depth` | How much scrutiny went into each |

**Subagent prompt:**

```
You are resolving a conflict between two claims in an epistemic memory system.

Claim A: {claim_a.content}
  - Credibility: {claim_a.credibility}
  - Confidence: {claim_a.confidence}
  - Recency: {claim_a.created_at}
  - Corroboration: {claim_a.corroboration}
  - Agent: {claim_a.agent_id} (track record: {agent_a.accuracy})

Claim B: {claim_b.content}
  - Credibility: {claim_b.credibility}
  - Confidence: {claim_b.confidence}
  - Recency: {claim_b.created_at}
  - Corroboration: {claim_b.corroboration}
  - Agent: {claim_b.agent_id} (track record: {agent_b.accuracy})

Context: {surrounding_context}

Decide:
1. Which claim should be the winner (if either)?
2. Should they be merged (both partially true)?
3. Should they coexist (different scopes/contexts)?

Return JSON:
{
  "action": "supersede" | "merge" | "coexist" | "defer",
  "winner": "a" | "b" | null,
  "rationale": "...",
  "merged_content": "..." // if action=merge
}
```

**Output handling:**

| Action | Effect |
|--------|--------|
| `supersede` | Winner supersedes loser: `(:winner)-[:SUPERSEDES {reason: 'resolves_contradiction'}]->(:loser)` |
| `merge` | New claim created with merged content, supersedes both: `(:merged)-[:SUPERSEDES {reason: 'resolves_contradiction'}]->(:a)`, same for b |
| `coexist` | Both marked `conflict_status='resolved_coexist'`, `CONTRADICTS` edge weight reduced to 0.3, no supersession |
| `retry` | Stays unresolved, re-queue for consolidation when new evidence arrives |

### 4.4 Recency Handling

Recency is a signal, not a rule. The subagent weighs it contextually:

| Content type | Recency weight |
|--------------|----------------|
| Project state, preferences | High (recent = more likely correct) |
| Factual claims | Low (unless explicitly corrected) |
| Time-scoped assertions | Depends on scope overlap |

---

## 5. Retrieval with Epistemic Awareness

### 5.1 Recall Query

```python
def recall(
    query: str,
    silo_id: str,
    include_conflicts: bool = False,
    confidence_threshold: float = 0.3,
) -> RecallResult:
    """
    Epistemic-aware retrieval.
    """
    # 1. Semantic search
    candidates = vector_search(query, silo_id)
    
    # 2. Expand via PPR
    anchors = [c.id for c in candidates[:5]]
    ppr_scores = personalized_pagerank(graph, anchors)
    expanded = [n for n, score in ppr_scores.items() if score > 0.1]
    
    # 3. Score with propagated confidence
    scored = []
    for node_id in set([c.id for c in candidates] + expanded):
        node = get_node(node_id)
        score = (
            node.similarity * 
            node.confidence *  # propagated, not raw
            layer_factor(node.layer) *
            ppr_scores.get(node_id, 0.1)
        )
        if score >= confidence_threshold:
            scored.append((node, score))
    
    # 4. Filter superseded
    scored = filter_superseded(scored)
    
    # 5. Surface conflict status
    results = []
    for node, score in sorted(scored, key=lambda x: -x[1]):
        results.append(RecallItem(
            node=node,
            score=score,
            conflict_status=node.conflict_status,  # 'none', 'unresolved', 'resolved_*'
            confidence=node.confidence,
            confidence_factors=get_confidence_breakdown(node),  # for transparency
        ))
    
    return RecallResult(
        items=results,
        has_unresolved_conflicts=any(r.conflict_status == 'unresolved' for r in results),
    )
```

### 5.2 Confidence Breakdown

For transparency, expose what factors contribute to confidence:

```python
@dataclass
class ConfidenceBreakdown:
    credibility: float          # source-based
    support_contribution: float # from supporting edges
    contradiction_penalty: float # from contradicting edges
    corroboration_boost: float  # from independent corroboration
    final_confidence: float     # propagated result
```

---

## 6. Invariants (updated)

| ID | Invariant | Change from v1 |
|----|-----------|----------------|
| I1 | Every Fact has >= 1 `DERIVED_FROM` to Memory | Unchanged |
| I2 | Every Belief has >= N `SYNTHESIZED_FROM` to Facts | Unchanged |
| I3 | Consensus requires >= K chains from >= J agents | Unchanged |
| I4 | No cycles in provenance edges | Unchanged |
| I5 | `SUPERSEDES` requires non-null reason | Unchanged |
| I6 | ReasoningChain has required edges | Unchanged |
| **I7** | `SUPPORTS` and `CONTRADICTS` edges have weight in [0,1] | **New** |
| **I8** | Contradiction edges are bidirectional (A contradicts B = B contradicts A) | **New** |
| **I9** | Confidence is recomputed after any edge mutation | **New** |

---

## 7. Performance Considerations

### 7.1 Confidence Propagation

Full propagation is O(n * edges * iterations). For large graphs:

- **Incremental**: on write, only propagate from changed node (depth-limited)
- **Lazy**: mark `confidence_stale`, recompute on query
- **Batched**: groundskeeper does full recomputation nightly

### 7.2 PPR Caching

PPR is expensive. Cache strategy:

- Cache PPR vectors for frequent query anchors
- Invalidate on edge changes within 2 hops
- TTL: 5 minutes

### 7.3 Consolidation Throughput

Subagent consolidation is slow (LLM call). Queue management:

- Priority by conflict severity (both high-confidence = urgent)
- Batch similar conflicts
- Rate limit: 10/minute per silo
- Escalate to human if queue backs up

---

## 8. Migration from v1

### 8.1 Schema Changes

```cypher
// Add confidence fields
ALTER NODE Claim ADD confidence FLOAT DEFAULT 1.0;
ALTER NODE Claim ADD conflict_status STRING DEFAULT 'none';

// Add edge weights
ALTER EDGE SUPPORTS ADD weight FLOAT DEFAULT 1.0;
ALTER EDGE CONTRADICTS ADD weight FLOAT DEFAULT 1.0;
```

### 8.2 Backfill

1. Compute credibility for all existing nodes (from existing confidence formula)
2. Create SUPPORTS edges from DERIVED_FROM (weight 1.0)
3. Detect existing conflicts, create CONTRADICTS edges
4. Run initial confidence propagation
5. Flag unresolved conflicts for consolidation queue

---

## 9. Design Decisions (resolved)

1. **Contradiction symmetry:** Bidirectional. If A contradicts B, B contradicts A. Both edges created.

2. **Contradiction resolution:** No new node type. Consolidation creates a regular Claim/Fact that supersedes both contradicting nodes with `reason='resolves_contradiction'`. Preserves history, stays within existing type system.

3. **Propagation frequency:** Hybrid. Depth-1 (direct edges) computed eagerly on write. Deeper transitive effects computed lazily on query or batched by groundskeeper. Fits 2s query timeout.

4. **Consolidation model:** Configurable via `config/settings.py` / yaml. Default to cost-effective model, allow override per silo.

5. **Human escalation:** None. Self-governing system. Unresolvable conflicts either:
   - Coexist with low confidence (both penalized, agent sees "unresolved" status)
   - Retry with more context when new evidence arrives
   - Age out if unresolved for N days and neither accessed

6. **Confidence floor:** Layer-dependent.
   - Memory: 0 (can fully decay)
   - Knowledge/Wisdom: 0.1 (retain trace unless explicitly deleted)

---

## 10. References

- Belief Graphs with Reasoning Zones (arXiv 2510.10042) - confidence propagation algorithm
- HippoRAG (OSU-NLP-Group) - PPR for traversal
- TruthfulRAG (STAIR-BUPT) - entropy-based conflict detection
- T-GRAG - temporal conflict handling
- CITE v1: `primitives/docs/06-epistemology.md`
