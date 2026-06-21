# Multi-Agent Coherence Design

Date: 2026-06-21
Status: Draft
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
4. Harnesses decide resolution policy, not the substrate
5. Works for all scenarios: fleet coordination, specialized collaboration, adversarial verification, cross-session continuity

## Non-Goals

- Consensus mechanisms (harness-side)
- Trust scoring / reputation systems (harness-side)
- Turn-taking / locking (harness-side)
- Conflict resolution logic (harness-side)

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

### Confidence Decomposition

The substrate stores inputs; credence computation is reader-side.

- **Stated confidence**: agent's self-report
- **Author identity**: who wrote this
- **Owner identity**: who vouches
- **Evidence links**: provenance
- **Corroboration**: who else believes this

Harnesses compute credence (effective weight) from these inputs using their own policies.

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

### Node Metadata Additions

```python
class NodeMetadata:
    # Existing
    content: str
    label: str
    confidence: float
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

- Add identity fields to nodes
- Backfill existing nodes with `agent_id = "legacy"`
- Add indexes
- Extend CONTRADICTS edge with resolution_status

### Phase 2: Write-Path Changes

- Identity resolution on all writes
- Conflict detection on write (feature flag)
- Event emission (feature flag)

### Phase 3: Query Surface

- Add `agents()`, `beliefs_by()`, `conflicts()`, `diff()` tools
- Extend `recall()` with agent filtering
- Add conflict resolution tools

### Phase 4: Deprecations

- SAGE batch contradiction detection becomes optional
- No breaking changes to existing MCP tools

## Summary

| Component | What changes |
|-----------|--------------|
| **Identity** | `agent_id`, `session_id`, `model_id`, `owner_id` on every node |
| **Resolution** | Layered fallback chain, always succeeds |
| **Conflicts** | Write-time detection, CONTRADICTS edge extended |
| **Query surface** | `agents()`, `beliefs_by()`, `conflicts()`, `diff()` |
| **Events** | `conflict.detected`, `node.created`, etc. |
| **Harness contract** | Provide identity for coordination, or we derive it |

**Memory owns:** Detection, storage, surfacing, queries.

**Harness owns:** Identity assignment, trust policies, resolution decisions.

## Open Questions

1. Should `model_id` be required or optional?
2. Event retention: how long do we keep events for polling?
3. Should conflict detection run on all layers or just Knowledge/Wisdom?
4. Do we need a "merge" resolution in addition to supersede/dismiss?

## References

- EAG Agent Instructions: `context/brainstorm/2026-05-10-eag-agent-instructions.md`
- Coherence Layer Pivot: `context/brainstorm/2026-06-18-coherence-layer-pivot.md`
- CITE v2 Schema: `primitives/src/primitives/schema/`
