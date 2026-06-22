# Multi-Agent Coherence Design

Date: 2026-06-21
Status: Approved
Author: Aliasgar Khimani

## Problem Statement

Engrammic currently supports single-agent workflows. Multi-agent coherence is untested and unsupported. To be a "contextual substrate" rather than just a memory layer, we need agents to coordinate through the medium without Engrammic prescribing coordination policy.

### The Gap

From eval findings:
> "Single-agent evaluation (multi-agent coherence untested)"

Current EAG stack has no concept of "who" wrote a belief. Agent nodes exist in Registry but aren't wired to content. Conflicts don't track which agents disagree.

## Goals

1. Any agent can see what other agents believe
2. Conflicts between agents are detected and surfaced in real-time
3. Accountability is built-in: every belief has an author and owner
4. Trust is earned from track record, confidence computed from signals
5. Harnesses decide resolution policy, substrate provides primitives
6. Works for all scenarios: fleet coordination, specialized collaboration, adversarial verification, cross-session continuity

## Non-Goals

- Consensus mechanisms (harness builds on query surface)
- Turn-taking / locking (harness-side)
- Conflict resolution logic (harness decides policy)

## Design Principles

### Memory as Medium, Not Mechanism

Engrammic is the coordination medium, not the coordination mechanism. The memory layer is expressive enough that coordination patterns emerge from how agents read and write.

Instead of building coordination into the memory layer, we make the memory layer expressive enough that coordination emerges from how agents use it.

### Identity as Metadata, Not Structure

No Agent nodes or edges for identity. Agent identity is metadata on content nodes that the harness provides.

Why metadata, not graph structure:
- No Agent node management overhead
- No edge traversal for "who wrote this"
- Harness provides identity at write time, we just store it
- Queries filter on metadata, not graph joins
- Simpler migration: just add fields

### Confidence Computed, Not Declared

Agents don't get to say "I'm 90% sure." Self-reported confidence is unreliable. Instead, confidence is derived from observable signals stored on the node. The substrate computes confidence; harnesses can override with their own policies.

### Trust Earned from Track Record

Trust is per-agent, computed from historical accuracy. The substrate tracks beliefs_validated vs beliefs_contradicted. Harnesses use trust scores in their resolution policies.

## Grounding in EAG

### Current CITE v2 Schema

**Nodes:** Memory, Claim, Fact, Belief, Commitment, Agent (registry)

**Edges:** DERIVED_FROM, SYNTHESIZED_FROM, SUPERSEDES, SUPPORTS, CONTRADICTS, ABOUT

### Multi-Agent Gap by Layer

| Layer | Agent writes | System creates | Gap |
|-------|--------------|----------------|-----|
| Memory | `remember()` -> Memory | - | Who observed this? |
| Knowledge | `learn()` -> Claim | SAGE -> Fact | Who claimed this? Whose evidence? |
| Wisdom | - | SAGE -> Belief | Who believes? |
| Intelligence | - | EpistemicState | Whose reasoning? |
| Registry | - | Agent (exists!) | Not linked to content |

### Multi-Agent Semantics by Layer

- **Memory layer:** Multiple agents can observe different things. Not conflicts, just different perspectives. Track who observed what.

- **Knowledge layer:** Agents may claim contradictory facts. CONTRADICTS edge surfaces "Agent A's Claim vs Agent B's Claim."

- **Wisdom layer:** Where real disagreement lives. Beliefs synthesized from different agents' facts may diverge.

- **Cross-layer:** When Belief B is SYNTHESIZED_FROM Facts that came from Agent A's Claims, that provenance chain is traceable.

## Data Model Changes

### Agent Entity (new)

```python
class Agent:
    id: str                     # unique identifier
    trust_score: float          # 0-1, computed from track record
    role: str                   # "researcher", "reviewer", "human"
    parent_agent_id: str | None # hierarchy
    scope: list[str]            # write domains
    beliefs_validated: int      # beliefs that held up
    beliefs_contradicted: int   # beliefs that were wrong
    created_at: datetime
```

### Node Metadata Additions

```python
class NodeMetadata:
    # Existing
    content: str
    label: str
    created_at: datetime
    valid_from: datetime | None
    silo_id: str
    
    # New: Identity (resolved via fallback chain)
    tenant_id: str          # isolation scope
    agent_id: str           # who wrote this
    session_id: str         # session scope
    model_id: str | None    # optional: which model
    
    # New: Ownership (defaults to author)
    owner_id: str | None    # who vouches, if different from agent_id
    
    # New: Multi-agent belief tracking
    believers: list[BelieverEntry]  # who believes this (array, not edges)
    
    # New: Confidence signals (raw data for computation)
    confidence_signals: ConfidenceSignals
    cached_confidence: float    # computed from signals, cached on write

class BelieverEntry:
    agent_id: str
    since: datetime
    confidence_at_write: float

class ConfidenceSignals:
    corroboration_count: int    # len(believers)
    contradiction_count: int    # CONTRADICTS edges
    validation_count: int       # VALIDATED_BY edges
    ncb_score: float | None     # neighborhood consistency (expensive)
    evidence_score: float | None # evidence quality (expensive)
```

### Edge Additions

No new edge types. CONTRADICTS edge extended with resolution tracking:

```python
class ContradictsEdge:
    source_id: str          # node A
    target_id: str          # node B
    detected_at: datetime
    detected_by: str        # "system" or agent_id that flagged it
    resolution_status: Literal["unresolved", "superseded", "dismissed", "escalated"]
    resolved_by: str | None # agent_id that resolved, if any
    resolved_at: datetime | None
```

### Indexes

```sql
CREATE INDEX idx_nodes_agent ON nodes(tenant_id, agent_id);
CREATE INDEX idx_nodes_session ON nodes(tenant_id, session_id);
CREATE INDEX idx_conflicts_unresolved ON edges 
    WHERE type = 'CONTRADICTS' AND resolution_status = 'unresolved';
```

### EventLog (append-only audit trail)

```python
class Event:
    id: ULID                    # ordered
    agent_id: str
    action: EventAction         # enum
    target_node_id: str
    payload: dict | None        # action-specific data
    timestamp: datetime

class EventAction(Enum):
    ASSERTED = "asserted"               # remember(), learn()
    RETRACTED = "retracted"             # forget()
    ENDORSED = "endorsed"               # agent joins believers
    CHALLENGED = "challenged"           # CONTRADICTS edge
    TRANSFERRED_OWNERSHIP = "transferred"
    VALIDATED = "validated"             # human/senior confirms
    SUPERSEDED = "superseded"           # update()
```

```sql
CREATE TABLE belief_events (
    id ULID PRIMARY KEY,
    agent_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_events_agent ON belief_events(agent_id, created_at);
CREATE INDEX idx_events_node ON belief_events(target_node_id, created_at);
```

## Confidence Computation

Confidence is computed from signals, not self-declared.

### Cheap signals (always computed)

| Signal | Source | Weight |
|--------|--------|--------|
| Corroboration | `len(believers)` | 0.25 |
| Contradiction | CONTRADICTS edges (negative) | 0.25 |
| Temporal stability | age without supersession | 0.15 |
| Validation | VALIDATED_BY edges | 0.15 |

### Expensive signals (Knowledge/Wisdom only)

| Signal | Source | Weight |
|--------|--------|--------|
| Evidence score | LLM/heuristics on evidence URIs | 0.10 |
| NCB score | neighborhood consistency check | 0.10 |

### Formula

```python
def compute_confidence(node: Node, signals: ConfidenceSignals) -> float:
    cheap = (
        min(1.0, signals.corroboration_count / 5) * 0.25 +
        max(0, 1 - signals.contradiction_count * 0.2) * 0.25 +
        min(1.0, node.age_days / 30) * 0.15 +
        min(1.0, signals.validation_count * 0.2) * 0.15
    )
    
    if node.layer in (Layer.Knowledge, Layer.Wisdom):
        expensive = (
            (signals.evidence_score or 0.5) * 0.10 +
            (signals.ncb_score or 0.5) * 0.10
        )
        return cheap + expensive
    
    # Memory layer: skip expensive, normalize
    return cheap / 0.8

def invalidate_confidence(node_id: str):
    """Recompute when: believer added, CONTRADICTS created, VALIDATED_BY created."""
    node = get_node(node_id)
    signals = gather_signals(node)
    node.cached_confidence = compute_confidence(node, signals)
    save(node)
```

## Trust Scoring

Trust is earned from track record.

### Formula

```python
def compute_trust(agent: Agent) -> float:
    total = agent.beliefs_validated + agent.beliefs_contradicted
    if total < 10:
        return 0.5  # insufficient data, neutral
    return agent.beliefs_validated / total
```

### Scoring events

| Event | Effect |
|-------|--------|
| Node superseded by higher-trust agent | `contradicted += 1` for original owner |
| Node validated by human/senior | `validated += 1` for owner |
| Node survives 30 days without contradiction | `validated += 1` for owner |
| Node explicitly marked wrong | `contradicted += 1` for owner |

### Effective weight (for queries)

```python
def effective_weight(node: Node) -> float:
    author_trust = get_agent(node.agent_id).trust_score
    owner_trust = get_agent(node.owner_id or node.agent_id).trust_score
    
    # Owner vouched for it, so their trust matters more
    trust = owner_trust * 0.7 + author_trust * 0.3
    
    return node.cached_confidence * trust
```

## Time Travel

Reconstruct state at any point using event log.

```python
def state_as_of(node_id: str, timestamp: datetime) -> Node:
    events = query(
        "SELECT * FROM belief_events WHERE target_node_id = %s AND created_at <= %s ORDER BY created_at",
        node_id, timestamp
    )
    return replay(events)
```

## Identity Resolution

### Layered Fallback Chain

Identity always resolves. Quality degrades gracefully.

```
Priority 1: Explicit agent_id (harness provides)
Priority 2: Derived from auth context (WorkOS user_id, API key owner)
Priority 3: Connection fingerprint (deterministic from client info)
Priority 4: Request-scoped anonymous (ephemeral)
```

### Resolution Logic

```python
def resolve_identity(request, explicit_agent_id=None) -> IdentityContext:
    tenant_id = (
        request.auth.org_id          # WorkOS
        or request.api_key.tenant    # API key
        or hash(request.origin)      # fingerprint
        or "default"                 # true fallback
    )
    
    agent_id = (
        explicit_agent_id                          # harness said so
        or request.auth.user_id                    # auth context
        or fingerprint(request.client_info)        # deterministic from connection
        or f"anon-{request.id}"                    # ephemeral
    )
    
    session_id = (
        request.headers.get("X-Session-Id")
        or request.auth.session_id
        or get_or_create_connection_session(request)
    )
    
    return IdentityContext(tenant_id, agent_id, session_id)
```

### Resolution by Scenario

| Scenario | tenant_id | agent_id | Quality |
|----------|-----------|----------|---------|
| Full harness + WorkOS | org_id | explicit | Perfect |
| WorkOS, no harness hint | org_id | user_id | Good |
| API key only | key.tenant | key.owner | Good |
| Local MCP, same client | fingerprint | fingerprint | Stable |
| Raw request, nothing | "default" | ephemeral | Works |

### Collision Safety

Agent IDs are always scoped to tenant:
```
effective_identity = (tenant_id, agent_id)
```

## Query Surface

### Extended recall

```python
recall(
    query: str,
    agent_id: str | None = None,      # filter to specific agent
    exclude_agents: list[str] = [],   # exclude certain agents
    include_conflicts: bool = False,  # return conflicting beliefs too
    session_id: str | None = None,    # scope to session
)
```

### New Tools

```python
# Who's here?
agents(
    silo_id: str | None = None,
) -> list[AgentSummary]
# Returns: [{agent_id, first_seen, last_seen, node_count, primary_layers}]

# What does agent X believe?
beliefs_by(
    agent_id: str,
    topic: str | None = None,
    layer: str | None = None,
) -> list[Node]

# Where do agents disagree?
conflicts(
    agent_id: str | None = None,
    status: str = "unresolved",
    topic: str | None = None,
) -> list[Conflict]
# Returns: [{node_a, node_b, agent_a, agent_b, detected_at, status}]

# Compare two agents
diff(
    agent_a: str,
    agent_b: str,
    topic: str | None = None,
) -> AgentDiff
# Returns: {agreements, disagreements, unique_to_a, unique_to_b}

# Agent's track record
trust_report(
    agent_id: str,
) -> TrustReport
# Returns: {trust_score, beliefs_validated, beliefs_contradicted, recent_beliefs}

# Who believes this?
believers(
    node_id: str,
) -> list[Agent]
```

### Conflict Resolution Tools

```python
dismiss_conflict(
    conflict_id: str,
    reason: str | None = None,
)

escalate_conflict(
    conflict_id: str,
    message: str | None = None,
)

resolve_conflict(
    conflict_id: str,
    winner_id: str,
    supersede: bool = True,
)
```

## Real-Time Conflict Detection

### Write-Time Detection

```python
async def on_write(node: Node, ctx: IdentityContext):
    stored = await store(node, ctx)
    
    if settings.conflict_detection_enabled:
        candidates = await qdrant.search(
            query=node.embedding,
            filter={"agent_id": {"$ne": ctx.agent_id}},
            limit=10,
        )
        
        for candidate in candidates:
            if await is_contradiction(node, candidate):
                await create_conflict_edge(
                    source=stored.id,
                    target=candidate.id,
                    detected_by="system",
                )
                
                await emit("conflict.detected", {
                    "node_a": stored.id,
                    "node_b": candidate.id,
                    "agent_a": ctx.agent_id,
                    "agent_b": candidate.agent_id,
                })
    
    return stored
```

### Contradiction Detection

```python
async def is_contradiction(a: Node, b: Node) -> bool:
    if a.label != b.label:
        return False
    
    similarity = cosine(a.embedding, b.embedding)
    if similarity < 0.7:
        return False
    
    spo_a = extract_spo(a.content)
    spo_b = extract_spo(b.content)
    
    if not same_subject(spo_a, spo_b):
        return False
    
    if settings.llm_contradiction_check:
        return await llm_is_contradiction(a.content, b.content)
    
    return similarity > 0.85
```

### Latency Budget

| Step | Target |
|------|--------|
| Qdrant search | ~50ms |
| SPO extraction | ~20ms |
| LLM check (if enabled) | ~200ms |
| Total (fast path) | ~70ms |
| Total (with LLM) | ~270ms |

### Configuration

```yaml
conflict_detection:
  enabled: true
  check_other_agents_only: true
  similarity_threshold: 0.7
  llm_verification: false
```

## Event Emission

### Events

```python
"node.created"       # any write
"node.superseded"    # SUPERSEDES edge created
"conflict.detected"  # CONTRADICTS edge created
"conflict.resolved"  # conflict status changed
"agent.first_seen"   # new agent_id in silo
```

### Payloads

```python
NodeCreatedEvent = {
    "node_id": str,
    "label": str,
    "agent_id": str,
    "session_id": str,
    "silo_id": str,
}

ConflictDetectedEvent = {
    "conflict_id": str,
    "node_a": str,
    "node_b": str,
    "agent_a": str,
    "agent_b": str,
    "similarity": float,
    "silo_id": str,
}
```

### Subscription Options

```python
# Polling (recommended starting point)
GET /events?silo_id=X&since=<timestamp>&types=conflict.detected

# SSE stream (future)
GET /events/stream?silo_id=X&types=conflict.detected

# Webhook (future)
POST /webhooks { silo_id, url, events }
```

Recommendation: Start with polling via `conflicts()` tool. Add SSE/webhooks when needed.

## Migration Path

### Phase 1: Schema Additions (non-breaking)

- Create Agent entity table
- Add identity fields to nodes (agent_id, session_id, owner_id)
- Add believers[], confidence_signals, cached_confidence to nodes
- Create belief_events table
- Backfill existing nodes with `agent_id = "legacy"`, `believers = []`
- Add indexes

### Phase 2: Write-Path Changes

- Identity resolution on all writes
- Confidence signal computation on write
- Event logging on write
- Conflict detection on write (feature flag)

### Phase 3: Query Surface

- Add `agents()`, `beliefs_by()`, `conflicts()`, `diff()`, `trust_report()`, `believers()` tools
- Extend `recall()` with agent filtering, min_confidence, min_trust
- Add conflict resolution tools

### Phase 4: Trust Scoring

- Background job to update trust scores based on outcomes
- 30-day survival check for beliefs_validated increment
- Hook supersession to beliefs_contradicted

### Phase 5: Deprecations

- SAGE batch contradiction detection becomes optional
- No breaking changes to existing MCP tools

## Summary

| Component | What changes |
|-----------|--------------|
| **Agent entity** | New entity with trust_score, role, hierarchy, track record |
| **Identity** | `agent_id`, `session_id`, `model_id`, `owner_id` on every node |
| **Believers** | `believers[]` array on nodes (who believes this) |
| **Confidence** | Computed from signals, cached on write |
| **Trust** | Earned from track record (validated/contradicted ratio) |
| **Resolution** | Layered fallback chain, always succeeds |
| **Conflicts** | Write-time detection, CONTRADICTS edge extended |
| **Query surface** | `agents()`, `beliefs_by()`, `conflicts()`, `diff()`, `trust_report()`, `believers()` |
| **Events** | Append-only EventLog for audit and time-travel |
| **Harness contract** | Provide identity for coordination, or we derive it |

**Substrate owns:** Identity resolution, confidence computation, trust scoring, conflict detection, event logging, queries.

**Harness owns:** Resolution policy, consensus mechanisms, hierarchy definitions.

## Open Questions

1. Event retention: how long do we keep events? (suggest: 90 days, then archive)
2. Should expensive confidence signals (NCB, evidence_score) run sync or async?
3. Trust score decay: should old beliefs count less than recent ones?

## References

- EAG Agent Instructions: `context/brainstorm/2026-05-10-eag-agent-instructions.md`
- Coherence Layer Pivot: `context/brainstorm/2026-06-18-coherence-layer-pivot.md`
- CITE v2 Schema: `primitives/src/primitives/schema/`
