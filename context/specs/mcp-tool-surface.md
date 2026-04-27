# MCP Tool Surface Design

> EAG-native MCP tools for context-service. Intent-based verbs reflecting agent cognition.

## Design Principles

1. **Intent-based verbs** — `remember`, `assert`, `commit`, `reflect` (not CRUD)
2. **Evidence required for Knowledge** — no hallucinated sources; must be node ref or URI
3. **Implicit agent attribution** — from auth context
4. **Layer-aware reads, layer-inferred writes** — agents can filter reads by layer; writes go to appropriate layer based on verb
5. **Deterministic IDs + MERGE** — race conditions resolved via content-based hashing and idempotent writes
6. **Agent-scoped commitments** — beliefs/commitments tied to declaring agent

## Consumer Patterns

Primary: Multi-agent collaboration, single autonomous agents
Secondary: Human-in-loop with approval gates

---

## Tool Catalogue

### Write Tools (Intent Verbs)

| Tool | Layer | Evidence | Purpose |
|------|-------|----------|---------|
| `context_remember` | Memory | No | Store experiences, observations, events |
| `context_assert` | Knowledge | Required | Assert claims with grounded evidence |
| `context_commit` | Wisdom | No (refs Knowledge) | Declare beliefs, stances |
| `context_reflect` | Meta | No (refs any) | Meta-observations about cognition |
| `context_link` | Cross-layer | No | Create relationships |

### Read Tools

| Tool | Purpose |
|------|---------|
| `context_query` | Semantic search with layer/filter support |
| `context_get` | Retrieve by ID with optional edges |
| `context_graph` | Graph traversal from semantic seed |

### Meta-Memory Tools

| Tool | Purpose |
|------|---------|
| `context_provenance` | Trace citation chain to source |
| `context_history` | Belief/fact evolution over time |

### Intelligence Tools

| Tool | Purpose |
|------|---------|
| `context_reason` | Store reasoning chains with crystallizations |

### Silo Management

| Tool | Purpose |
|------|---------|
| `silo_create` | Create tenancy boundary |
| `silo_list` | List silos for org |

---

## Tool Signatures

### context_remember

Store an experience to Memory layer. No evidence required — memories ARE grounding.

```python
context_remember(
    silo_id: str,
    content: str,
    content_type: Literal["text", "utterance", "event"] = "text",
    metadata: dict | None = None,
    tags: list[str] | None = None,
    decay_class: Literal["ephemeral", "standard", "durable", "permanent"] = "standard",
    observed_from: str | None = None,  # "user:<id>" or "agent:<id>" if reporting others
) -> {
    node_id: str,
    layer: "memory",
    decay_class: str,
    created_at: datetime,
}
```

### context_assert

Assert a claim to Knowledge layer. Evidence required.

```python
context_assert(
    silo_id: str,
    claim: str | SPOClaim,  # Free text OR structured {subject, predicate, object}
    evidence: str | list[str],  # "node:<id>" or URI, required
    source_type: Literal["document", "user", "external", "agent"],
    confidence: float = 0.8,
    metadata: dict | None = None,
    tags: list[str] | None = None,
    evidence_mode: Literal["sync", "async"] = "sync",
) -> {
    node_id: str,
    layer: "knowledge",
    claim_type: "structured" | "freeform",
    evidence_status: "verified" | "pending" | "failed",
    evidence_nodes: list[str],
    created_at: datetime,
}

class SPOClaim:
    subject: str
    predicate: str
    object: str
    qualifiers: dict | None = None
```

**Evidence formats:**
- `node:<uuid>` — Reference to existing Memory-layer node
- `https://...` or `file://...` — URI, validated via evidence pipeline

**Source types:**
- `document` — From ingested doc/passage
- `user` — From user utterance
- `external` — From URI (fetched/validated)
- `agent` — Agent's own prior reasoning chain

### context_commit

Commit a belief or stance to Wisdom layer. Agent-scoped via `DECLARED_BY`.

```python
context_commit(
    silo_id: str,
    belief: str,
    about: list[str],  # Node IDs this belief concerns
    confidence: float = 0.8,
    reasoning: str | None = None,
    metadata: dict | None = None,
    tags: list[str] | None = None,
) -> {
    node_id: str,
    layer: "wisdom",
    declared_by: str,  # Agent ID from auth
    about_nodes: list[str],
    created_at: datetime,
}
```

### context_reflect

Store a meta-observation about the agent's own cognition.

```python
context_reflect(
    silo_id: str,
    observation: str,
    observation_type: Literal[
        "belief_change",
        "confidence_shift",
        "contradiction",
        "uncertainty",
        "correction",
        "insight",
    ],
    about: list[str],  # Node IDs this observation concerns
    confidence: float = 0.8,
    metadata: dict | None = None,
) -> {
    node_id: str,
    observation_type: str,
    about_nodes: list[str],
    created_at: datetime,
}
```

### context_link

Create a relationship between nodes.

```python
context_link(
    silo_id: str,
    from_node: str,
    to_node: str,
    relationship: Literal[
        "REFERENCES",
        "SUPPORTS",
        "CONTRADICTS",
        "DERIVED_FROM",
        "RELATED_TO",
    ],
    weight: float = 1.0,
    note: str | None = None,
) -> {
    edge_id: str,
    from_node: str,
    to_node: str,
    relationship: str,
    created_at: datetime,
}
```

### context_query

Semantic search with layer filtering.

```python
context_query(
    silo_id: str,
    query: str,
    layers: list[Literal["memory", "knowledge", "wisdom"]] | None = None,
    filters: QueryFilters | None = None,
    top_k: int = 10,
    include_superseded: bool = False,
    as_of: datetime | None = None,  # Time-travel
) -> {
    results: list[QueryResult],
    total_candidates: int,
    search_time_ms: int,
}

class QueryFilters:
    tags: list[str] | None = None
    source_type: list[str] | None = None
    min_confidence: float | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None

class QueryResult:
    node_id: str
    layer: str
    content: str
    summary: str | None
    confidence: float
    relevance_score: float
    tags: list[str]
    created_at: datetime
```

### context_get

Retrieve full node(s) by ID.

```python
context_get(
    silo_id: str,
    node_ids: str | list[str],
    include_edges: bool = False,
    edge_types: list[str] | None = None,
) -> {
    nodes: list[Node],
    edges: list[Edge] | None,
}
```

### context_graph

Graph traversal from semantic seed.

```python
context_graph(
    silo_id: str,
    query: str | None = None,
    seed_nodes: list[str] | None = None,
    max_depth: int = 2,
    max_nodes: int = 50,
    relationship_types: list[str] | None = None,
    layers: list[str] | None = None,
) -> {
    nodes: list[Node],
    edges: list[Edge],
    traversal_stats: {
        depth_reached: int,
        nodes_visited: int,
        edges_traversed: int,
    },
}
```

### context_provenance

Trace citation chain to source.

```python
context_provenance(
    silo_id: str,
    node_id: str,
    max_depth: int = 10,
) -> {
    chain: list[ProvenanceStep],
    root_sources: list[str],
}

class ProvenanceStep:
    node_id: str
    layer: str
    relationship: str
    confidence: float
```

### context_history

Belief/fact evolution over time.

```python
context_history(
    silo_id: str,
    subject: str | None = None,  # Semantic match
    node_id: str | None = None,  # Start from specific node
) -> {
    timeline: list[HistoryEntry],
    current: str | None,
}

class HistoryEntry:
    node_id: str
    content: str
    valid_from: datetime
    valid_to: datetime | None
    superseded_by: str | None
    supersession_reason: str | None
    confidence: float
```

### context_reason

Store a reasoning chain (Intelligence layer).

```python
context_reason(
    silo_id: str,
    steps: list[ReasoningStep],
    conclusion: str | None = None,
    evidence_used: list[str] | None = None,
    crystallizations: list[Crystallization] | None = None,
) -> {
    chain_id: str,
    layer: "intelligence",
    steps_count: int,
    crystallizations_queued: int,
    session_id: str,
}

class ReasoningStep:
    step: int
    reasoning: str
    confidence: float | None = None

class Crystallization:
    claim: str | SPOClaim
    confidence: float
```

### silo_create

```python
silo_create(
    name: str,
    description: str | None = None,
    config: SiloConfig | None = None,
) -> {
    silo_id: str,
    name: str,
    org_id: str,
    created_at: datetime,
}

class SiloConfig:
    extraction_enabled: bool = True
    decay_class: str = "standard"
    evidence_policy: EvidencePolicy | None = None
```

### silo_list

```python
silo_list() -> {
    silos: list[Silo],
}
```

---

## Evidence Pipeline

For `context_assert` with URI evidence:

```
URI arrives
    |
    v
+------------------+
|  Cache lookup    | --hit--> Return cached result
+--------+---------+
         | miss
         v
+------------------+
| Allowlist check  | --trusted domain--> confidence=0.9, skip fetch
+--------+---------+
         | unknown domain
         v
+------------------+
|  Reachability    | --HEAD 200--> confidence=0.7, store URI
+--------+---------+
         | success + ingest_policy
         v
+------------------+
|  Fetch & hash    | --content--> Dedup check
+--------+---------+
         | new content
         v
+------------------+
| Create :Document | --node_id--> confidence=1.0, full provenance
+------------------+
```

**EvidencePolicy (per-silo):**
```python
class EvidencePolicy:
    allowlist: list[str]       # ["*.internal.co", "docs.example.com"]
    auto_ingest: bool          # Fetch and create Memory nodes?
    require_reachable: bool    # Reject if HEAD fails?
    cache_ttl: timedelta       # Validation cache TTL
```

---

## Race Condition Handling

| Scenario | Resolution |
|----------|------------|
| Same claim asserted twice | Deterministic ID (content hash) + MERGE |
| Conflicting claims | Both written, Custodian detects via T2 supersession |
| Same belief committed | No conflict — commitments are agent-scoped |
| Same memory recorded | Deterministic ID + MERGE |

---

## Layer-Evidence Requirements

| Layer | Evidence required? | Grounding |
|-------|-------------------|-----------|
| Memory | No | Self-evident |
| Knowledge | Yes | `DERIVED_FROM` edge to Memory or URI |
| Wisdom | No | `SYNTHESIZED_FROM` edges (Custodian) |
| Intelligence | No | Session-scoped |

---

## Mapping to Transitions

Agent verbs map to system transitions:

| Agent verb | System transition | Custodian role |
|------------|-------------------|----------------|
| `remember` | (direct write) | Decay (T8), hard-delete (T9) |
| `assert` | (direct write) | Extract (T1), supersede (T2), promote (T5) |
| `commit` | T7 | Reconciliation |
| `reflect` | (direct write) | None |
| `reason` | (direct write) | Consensus (T5), trace (T6) |

Agents express intent; Custodian handles mechanics.
