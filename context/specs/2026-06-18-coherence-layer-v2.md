# Coherence Layer v2 Specification

Date: 2026-06-18
Status: Ready for implementation
Related: 
- [Schema Simplification](../brainstorm/2026-06-18-schema-simplification.md)
- [Coherence Layer Pivot](../brainstorm/2026-06-18-coherence-layer-pivot.md)
- [Benchmark Strategy](../brainstorm/2026-06-18-benchmark-strategy.md)

## Executive Summary

Engrammic pivots from SAGE batch pipeline to real-time write-gating coherence layer. Schema pruned from 15+ nodes/23 edges to 5 nodes/6 edges. Intelligence layer becomes passive observation. MCP surface reduced to 5 tools.

## Architecture Overview

```
Agent (Claude Code, Gemini CLI, etc.)
    │
    ▼
┌─────────────────────────────────────┐
│         MCP Tool Surface            │
│  remember, learn, recall, trace, tick│
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│         Write Gate (real-time)      │
│  - Epistemic routing (Memory/Know)  │
│  - Contradiction detection          │
│  - Evidence validation              │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│         Coherence Graph             │
│  Postgres + pgvector                │
│  5 nodes, 6 edges                   │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│         SAGE Dreaming (async)       │
│  - Claim → Fact promotion           │
│  - Fact → Belief synthesis          │
│  - Passive Intelligence observation │
└─────────────────────────────────────┘
```

## Schema

### Nodes (5)

| Label | Layer | Purpose | Created by |
|-------|-------|---------|------------|
| Memory | Memory | Raw observations, preferences | Agent via `remember` |
| Claim | Knowledge | Evidence-backed assertions | Agent via `learn` |
| Fact | Knowledge | Corroborated claims | SAGE promotes |
| Belief | Wisdom | Synthesized conclusions | SAGE synthesizes |
| Commitment | Wisdom | Agent decisions | Agent via `decide` |

### Node Properties (common)

```python
class BaseNode:
    id: UUID
    silo_id: str
    content: str
    embedding: list[float]
    confidence: float  # 0.0-1.0
    created_at: datetime
    updated_at: datetime
    valid_from: datetime
    valid_to: datetime | None  # null = current
    metadata: dict
```

### Layer-specific properties

```python
class Memory(BaseNode):
    memory_type: Literal["observation", "preference", "event"]
    decay_rate: float  # how fast confidence drops

class Claim(BaseNode):
    evidence_uri: str  # required
    evidence_hash: str | None  # content verification
    verified: bool  # false until promoted to Fact

class Fact(BaseNode):
    corroboration_count: int
    promoted_from: UUID  # original Claim ID
    
class Belief(BaseNode):
    synthesis_chain: list[UUID]  # Fact IDs
    
class Commitment(BaseNode):
    source: Literal["agent", "crystallized"]  # direct decide vs from hypothesis
    about_nodes: list[UUID]  # what this decision concerns
    stale: bool  # engagement surface flag
```

### Edges (6)

| Edge | From → To | Purpose | Created by |
|------|-----------|---------|------------|
| DERIVED_FROM | Claim → Memory, Fact → Claim | Provenance chain | Agent or SAGE |
| SYNTHESIZED_FROM | Belief → Fact | Synthesis lineage | SAGE |
| SUPERSEDES | Any → Any (same type) | Version chain | Agent or SAGE |
| SUPPORTS | Any → Any | Positive epistemology | SAGE |
| CONTRADICTS | Any → Any | Negative epistemology | SAGE |
| ABOUT | Commitment → Any | Decision targeting | Agent |

### Edge Properties

```python
class Edge:
    id: UUID
    source_id: UUID
    target_id: UUID
    edge_type: EdgeType
    weight: float  # for confidence propagation
    created_at: datetime
    metadata: dict
```

### Confidence Propagation Weights

From existing diffusion.py:
```python
EDGE_WEIGHTS = {
    "SUPPORTS": 0.90,
    "CONTRADICTS": -0.95,
    "DERIVED_FROM": 0.85,
    "SYNTHESIZED_FROM": 0.80,
    "SUPERSEDES": 0.0,  # doesn't propagate, replaces
    "ABOUT": 0.0,  # structural, not epistemic
}
```

## MCP Tool Surface

### Tools (5)

| Tool | Creates | Edges | Description |
|------|---------|-------|-------------|
| `remember` | Memory | optional DERIVED_FROM | Store observation |
| `learn` | Claim | DERIVED_FROM to evidence | Store claim with evidence |
| `decide` | Commitment | ABOUT to target nodes | Record agent decision |
| `recall` | - | - | Query with coherent view |
| `trace` | - | - | Walk provenance chain |
| `tick` | - | - | Engagement acknowledgment |

Wait - that's 6 tools. Let me reconsider.

### Revised Tools (5)

| Tool | Creates | Description |
|------|---------|-------------|
| `remember` | Memory | Store observation, preference, or event |
| `learn` | Claim | Store claim with evidence URI |
| `recall` | - | Query (vector + graph), returns coherent view |
| `trace` | - | Walk DERIVED_FROM/SYNTHESIZED_FROM/SUPERSEDES chains |
| `tick` | - | Acknowledge engagement, reset decay |

**Note:** `decide` is deferred to Phase 2. For MVP, agents can only observe and claim. Decisions are implicit in actions.

### Tool Signatures

```python
# remember
def remember(
    content: str,
    memory_type: Literal["observation", "preference", "event"] = "observation",
    references: list[str] | None = None,  # node IDs to link via DERIVED_FROM
    metadata: dict | None = None,
) -> MemoryNode

# learn  
def learn(
    content: str,
    evidence: str,  # URI (file://, https://)
    references: list[str] | None = None,
    metadata: dict | None = None,
) -> ClaimNode

# recall
def recall(
    query: str | None = None,
    node_id: str | None = None,  # direct lookup
    scope: list[Literal["memory", "knowledge", "wisdom"]] | None = None,
    limit: int = 10,
    min_confidence: float = 0.3,
    include_contradictions: bool = False,
) -> RecallResult

# trace
def trace(
    node_id: str,
    direction: Literal["up", "down"] = "up",  # up = sources, down = derived
    max_depth: int = 5,
    edge_types: list[str] | None = None,
) -> TraceResult

# tick
def tick(
    node_ids: list[str],
    engagement_type: Literal["viewed", "used", "confirmed"] = "viewed",
) -> None
```

## Write Gate

Real-time validation on every write. No LLM calls in hot path. Never blocks writes - flags for async review.

### Design Principles

1. **Never block** - writes always succeed (unless malformed)
2. **Flag, don't reject** - suspicious writes get flagged for SAGE review
3. **Deterministic only** - no LLM inference in write path
4. **Embed once** - embedding happens at write time, not recall time

### Gate Pipeline

```
Agent write (remember/learn)
    │
    ▼
┌─────────────────────────────────────┐
│  1. Validate & Classify             │
│     - Parse input, validate schema  │
│     - Has evidence URI? → Claim     │
│     - No evidence? → Memory         │
│     ~1ms                            │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  2. Evidence Format (Claims only)   │
│     - Valid URI syntax?             │
│     - Recognized scheme?            │
│       (file://, https://, git://)   │
│     ~1ms                            │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  3. Embed Content                   │
│     - TEI/local embedding model     │
│     - Cache check first             │
│     ~8-15ms                         │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  4. Similarity Search               │
│     - pgvector: top-5 similar nodes │
│     - Check for high similarity     │
│       (>0.92 = potential duplicate) │
│     ~10-20ms                        │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  5. Supersession Resolution         │
│     - Agent provided supersedes?    │
│       → Create SUPERSEDES edge      │
│     - High similarity found?        │
│       → Flag for SAGE review        │
│     ~5ms                            │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  6. Store                           │
│     - Insert node + embedding       │
│     - Insert edges (DERIVED_FROM,   │
│       SUPERSEDES, ABOUT)            │
│     - Set flags (needs_review, etc) │
│     ~10-20ms                        │
└─────────────────────────────────────┘
    │
    ▼
Return node_id + any warnings
```

### Pseudocode

```python
@dataclass
class WriteResult:
    node_id: str
    warnings: list[str]
    flags: list[str]  # needs_contradiction_check, needs_supersession_review

async def write_gate(
    content: str,
    evidence_uri: str | None,
    supersedes: str | None,
    references: list[str] | None,
    metadata: dict | None,
    silo_id: str,
) -> WriteResult:
    warnings = []
    flags = []
    
    # 1. Classify
    if evidence_uri:
        label = "Claim"
        # 2. Validate URI format only (no fetch - can't access auth-gated/private)
        if not is_valid_uri(evidence_uri):
            warnings.append(f"Invalid evidence URI format: {evidence_uri}")
    else:
        label = "Memory"
    
    # 3. Embed
    embedding = await embed(content)
    
    # 4. Similarity search
    similar = await vector_search(embedding, silo_id, top_k=5, threshold=0.85)
    
    # 5. Supersession
    if supersedes:
        # Agent explicitly said this supersedes something
        edges = [("SUPERSEDES", supersedes)]
    elif similar and similar[0].score > 0.92:
        # Very high similarity - might be duplicate or update
        flags.append("needs_supersession_review")
        warnings.append(f"High similarity to {similar[0].node_id} ({similar[0].score:.2f})")
        edges = []
    else:
        edges = []
    
    # Add reference edges
    if references:
        edges.extend([("DERIVED_FROM", ref) for ref in references])
    
    # 6. Store
    node_id = await store_node(
        label=label,
        content=content,
        embedding=embedding,
        evidence_uri=evidence_uri,
        silo_id=silo_id,
        metadata=metadata,
        flags=flags,
    )
    
    await store_edges(node_id, edges)
    
    return WriteResult(node_id=node_id, warnings=warnings, flags=flags)
```

### What Write Gate Does NOT Do

1. **Contradiction detection** - SAGE does this async (requires semantic understanding)
2. **Duplicate merging** - flags for review, doesn't auto-merge
3. **Content validation** - doesn't check if claim is "true"
4. **Evidence fetching** - can't access auth-gated/private URIs; format validation only
5. **LLM inference** - no model calls in hot path

### Flags for SAGE Review

| Flag | Meaning | SAGE Action |
|------|---------|-------------|
| `needs_supersession_review` | High similarity found | Check if duplicate or update, create SUPERSEDES |
| `needs_contradiction_check` | Multiple similar with different content | Check for CONTRADICTS |

### Total Write Latency Target

| Layer | Operations | Target |
|-------|------------|--------|
| Memory | classify + embed + similarity + store | < 50ms p95 |
| Claim | same (URI format check is ~1ms) | < 50ms p95 |

Embedding is the bottleneck (~8-15ms with TEI on GPU). No evidence fetching in hot path.

## SAGE Dreaming (Async)

Background jobs that run periodically. Not in agent hot path.

### Jobs

| Job | Frequency | Purpose |
|-----|-----------|---------|
| Promoter | 5 min | Claim → Fact when corroborated |
| Synthesizer | 15 min | Facts → Belief when cluster reaches threshold |
| Decayer | 1 hour | Reduce Memory confidence over time |
| Detector | 5 min | Find SUPPORTS/CONTRADICTS edges |
| Observer | 5 min | Create Intelligence nodes from behavior (Phase 2) |

### Promotion Criteria (Claim → Fact)

```python
def should_promote(claim: Claim) -> bool:
    # Multiple claims saying same thing
    similar = find_similar_claims(claim, threshold=0.85)
    if len(similar) >= 2:
        return True
    
    # Evidence verified
    if claim.evidence_hash and verify_evidence(claim):
        return True
    
    # High confidence from trusted source
    if claim.confidence >= 0.9 and claim.metadata.get("source_tier") == "authoritative":
        return True
    
    return False
```

### Synthesis Criteria (Facts → Belief)

```python
def should_synthesize(facts: list[Fact]) -> bool:
    # Cluster of related facts
    if len(facts) >= 3:
        # Check they support each other (no contradictions)
        if all_mutually_supporting(facts):
            return True
    return False
```

## Intelligence Layer (Phase 2)

Passive observation of agent behavior. No agent writes.

### Signals to Track

| Signal | Detection | Node Created |
|--------|-----------|--------------|
| Confidence drift | Rolling avg of claim confidence | EpistemicState |
| Action repetition | Same tool calls in sequence | StuckIndicator |
| Contradiction rate | CONTRADICTS edges per session | ConflictCluster |
| Resolution pattern | Confidence spike after struggle | Breakthrough |

### Intelligence Nodes

```python
class EpistemicState(BaseNode):
    session_id: str
    state_type: Literal["confident", "uncertain", "confused", "stuck"]
    confidence_trajectory: list[float]
    
class Breakthrough(BaseNode):
    stuck_indicator_id: UUID
    resolution_action: str  # what unblocked
    session_id: str
```

### Surfacing via Recall

When agent is stuck (detected via action repetition), recall can return:

```python
# Pseudocode for enhanced recall
def recall_with_epistemic_context(query: str, session: Session) -> RecallResult:
    results = standard_recall(query)
    
    # Check if agent is in similar epistemic state
    current_state = detect_epistemic_state(session)
    if current_state.state_type == "stuck":
        # Find past breakthroughs from similar states
        breakthroughs = find_similar_breakthroughs(current_state)
        results.epistemic_hints = breakthroughs
    
    return results
```

## Recall (Coherent View)

Recall returns a coherent worldview, not raw nodes. Key principle: **filter contradictions, surface provenance, rank by confidence**.

### Design Principles

1. **Coherent, not comprehensive** - better to return 5 coherent facts than 10 contradictory ones
2. **Provenance on demand** - include "why I believe this" when asked
3. **Layer-aware** - respect epistemic hierarchy (Belief > Fact > Claim > Memory)
4. **Fresh over stale** - recent supersedes old (via SUPERSEDES chains)

### Pipeline

```
Query (text or node_id)
    │
    ▼
┌─────────────────────────────────────┐
│  1. Parse & Route                   │
│     - Direct lookup (node_id)?      │
│       → Fetch node + expand         │
│     - Text query?                   │
│       → Embed + vector search       │
│     ~1-10ms                         │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  2. Vector Search                   │
│     - pgvector similarity search    │
│     - top-k candidates (k=20)       │
│     - filter by scope (layers)      │
│     - filter by min_confidence      │
│     ~15-25ms                        │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  3. Supersession Resolution         │
│     - Walk SUPERSEDES chains        │
│     - Keep only current versions    │
│     - (head of chain, valid_to=null)│
│     ~10-20ms                        │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  4. Contradiction Resolution        │
│     - Check CONTRADICTS edges       │
│     - If A contradicts B:           │
│       - Keep higher confidence      │
│       - Or keep higher layer        │
│         (Belief > Fact > Claim)     │
│       - Note contradiction in meta  │
│     ~10-15ms                        │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  5. Graph Expansion (optional)      │
│     - Walk SUPPORTS edges (depth 1) │
│     - Walk DERIVED_FROM (depth 2)   │
│     - Add supporting evidence       │
│     ~20-40ms if requested           │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  6. Rank & Format                   │
│     - Sort by relevance * confidence│
│     - Apply limit                   │
│     - Format response               │
│     ~5ms                            │
└─────────────────────────────────────┘
    │
    ▼
Coherent result set
```

### Pseudocode

```python
@dataclass
class RecallNode:
    id: str
    content: str
    label: str  # Memory, Claim, Fact, Belief, Commitment
    confidence: float
    created_at: datetime
    evidence_uri: str | None
    supports: list[str] | None  # node IDs if expanded
    derived_from: list[str] | None
    superseded_by: str | None  # if not current
    contradicts: list[str] | None  # noted but filtered

@dataclass  
class RecallResult:
    nodes: list[RecallNode]
    query: str
    total_candidates: int
    filtered_contradictions: int
    filtered_superseded: int

async def recall(
    query: str | None = None,
    node_id: str | None = None,
    scope: list[str] | None = None,  # ["memory", "knowledge", "wisdom"]
    limit: int = 10,
    min_confidence: float = 0.3,
    expand_provenance: bool = False,
    include_contradictions: bool = False,
    silo_id: str,
) -> RecallResult:
    
    # 1. Route
    if node_id:
        candidates = [await fetch_node(node_id, silo_id)]
    else:
        embedding = await embed(query)
        candidates = await vector_search(
            embedding, 
            silo_id, 
            top_k=limit * 2,  # over-fetch for filtering
            scope=scope,
            min_confidence=min_confidence,
        )
    
    # 2. Supersession resolution
    current_nodes = []
    filtered_superseded = 0
    for node in candidates:
        current = await get_current_version(node)
        if current.id != node.id:
            filtered_superseded += 1
        if current not in current_nodes:
            current_nodes.append(current)
    
    # 3. Contradiction resolution
    coherent_nodes = []
    filtered_contradictions = 0
    contradictions = await get_contradiction_edges(current_nodes)
    
    for node in current_nodes:
        dominated = False
        for other in current_nodes:
            if (node.id, other.id) in contradictions:
                # node contradicts other - who wins?
                if dominates(other, node):  # other has higher confidence/layer
                    dominated = True
                    filtered_contradictions += 1
                    break
        
        if not dominated or include_contradictions:
            coherent_nodes.append(node)
    
    # 4. Expansion (optional)
    if expand_provenance:
        for node in coherent_nodes:
            node.supports = await get_supports(node.id, depth=1)
            node.derived_from = await get_derived_from(node.id, depth=2)
    
    # 5. Rank & limit
    coherent_nodes.sort(key=lambda n: n.relevance * n.confidence, reverse=True)
    coherent_nodes = coherent_nodes[:limit]
    
    return RecallResult(
        nodes=coherent_nodes,
        query=query or f"lookup:{node_id}",
        total_candidates=len(candidates),
        filtered_contradictions=filtered_contradictions,
        filtered_superseded=filtered_superseded,
    )

def dominates(a: RecallNode, b: RecallNode) -> bool:
    """Does node A dominate node B in epistemic hierarchy?"""
    layer_order = {"Belief": 4, "Commitment": 4, "Fact": 3, "Claim": 2, "Memory": 1}
    
    # Higher layer wins
    if layer_order[a.label] > layer_order[b.label]:
        return True
    if layer_order[a.label] < layer_order[b.label]:
        return False
    
    # Same layer: higher confidence wins
    return a.confidence > b.confidence
```

### Contradiction Resolution Rules

| Scenario | Winner | Rationale |
|----------|--------|-----------|
| Belief vs Claim | Belief | Synthesized from multiple facts |
| Fact vs Claim | Fact | Promoted/corroborated |
| Same layer, diff confidence | Higher confidence | More corroborated |
| Same layer, same confidence | More recent | Fresh information |
| Agent Commitment vs SAGE Belief | Commitment | Agent authority over own decisions |

### Response Format

```json
{
  "nodes": [
    {
      "id": "abc123",
      "content": "The API uses OAuth2 with PKCE",
      "label": "Fact",
      "confidence": 0.92,
      "created_at": "2026-06-18T10:30:00Z",
      "evidence_uri": "file:///src/auth/config.py",
      "derived_from": ["def456"]
    }
  ],
  "meta": {
    "query": "API authentication method",
    "total_candidates": 15,
    "filtered_contradictions": 2,
    "filtered_superseded": 3,
    "latency_ms": 67
  }
}
```

### Recall Latency Target

| Operation | Target |
|-----------|--------|
| Parse & route | < 5ms |
| Vector search | < 25ms |
| Supersession resolution | < 20ms |
| Contradiction resolution | < 15ms |
| Graph expansion (optional) | < 40ms |
| **Total (without expansion)** | **< 70ms p95** |
| **Total (with expansion)** | **< 110ms p95** |

## Migration Plan

### Phase 1: Primitives Update

1. Update `primitives/schema/labels.py`:
   - Rename/consolidate Memory layer labels
   - Remove Entity, Cluster, Pattern, etc.
   - Keep only: Memory, Claim, Fact, Belief, Commitment

2. Update `primitives/schema/edges.py`:
   - Remove MEMBER_OF, EXTRACTED_FROM, MENTIONS, etc.
   - Keep only: DERIVED_FROM, SYNTHESIZED_FROM, SUPERSEDES, SUPPORTS, CONTRADICTS, ABOUT

3. Update `primitives/protocols.py`:
   - Simplify Layer enum if needed

### Phase 2: Context-Service Update

1. Update MCP tools:
   - Remove: decide, accept, dismiss, hypothesize, commit, revise, reason, link, reflect, history, forget, patterns
   - Keep: remember, learn, recall, trace, tick

2. Update write path:
   - Add write-gate pipeline
   - Remove batch extraction dependencies

3. Update SAGE jobs:
   - Remove clustering (no MEMBER_OF)
   - Simplify to: Promoter, Synthesizer, Decayer, Detector

### Phase 3: Intelligence Layer

1. Add behavior tracking
2. Add EpistemicState/Breakthrough nodes
3. Enhance recall with epistemic context

## Benchmark Targets

### Primary: BEAM
- Contradiction resolution
- Belief updates
- Temporal reasoning

### Secondary: LongMemEval-V2
- Empty leaderboard (first-mover)
- Gotcha detection (hard)
- Requires multi-pool retrieval

### Supporting
- LoCoMo: timeline ordering
- MEME: cascade updates (mem0 "near floor")
- MemoryArena: agentic task coherence

## Success Metrics

| Metric | Target | How measured |
|--------|--------|--------------|
| Write latency (Memory) | < 50ms p95 | OTEL traces |
| Write latency (Knowledge) | < 100ms p95 | OTEL traces |
| Recall latency | < 100ms p95 | OTEL traces |
| Contradiction detection | > 90% | BEAM benchmark |
| Belief update propagation | > 80% | MEME benchmark |

## Open Questions

1. Should `decide` be in MVP or deferred?
2. How to handle existing data with old schema?
3. What's the migration path for existing SAGE jobs?
4. Should we keep `link` for explicit edge creation?
