# context-service — API Examples & Agent Integration Patterns

MCP is the primary agent-facing interface. The REST API is used for admin, dashboard, and silo management. Examples below cover both surfaces.

The 9 MCP tools are:

- `context_store` — write to any layer (memory, knowledge, wisdom, intelligence, meta, belief)
- `context_recall` — read, search, traverse, or trace context; surfaces `proposed_beliefs`
- `context_link` — create a typed relationship between two nodes
- `context_admin` — silo management, provenance, history, session control
- `context_belief_state` — query live session beliefs + contradiction detection
- `context_update_belief` — mutate working belief in-place
- `context_crystallize` — promote working beliefs to commitments
- `context_accept_belief` — accept a ProposedBelief, convert to WorkingBelief
- `context_reject_belief` — reject a ProposedBelief with optional reason

`silo_id` is no longer passed by callers. It is derived from the authenticated session.

---

## MCP Tools (Agent Interface)

### context_store

Write content to any cognitive layer. The `layer` param selects the target; layer-specific required params are enforced at call time.

**Params:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `content` | str | required | The content to store. For `intelligence` layer, this is the conclusion. |
| `layer` | str | `"memory"` | One of `memory \| knowledge \| wisdom \| intelligence \| meta` |
| `evidence` | list[str] | null | Required for `knowledge` layer. `node:<uuid>` refs or URIs (http/https/file) |
| `source_type` | str | null | Required for `knowledge` layer. One of `document \| user \| external \| agent` |
| `confidence` | float | `0.8` | Agent confidence, 0.0–1.0 |
| `about` | list[str] | null | Required for `wisdom` and `meta` layers. Node IDs this entry concerns. Must be non-empty. |
| `reasoning` | str | null | Optional. Reasoning behind a wisdom-layer belief |
| `steps` | list[dict] | null | Required for `intelligence` layer. Each dict: `{step, reasoning, confidence?}` |
| `observation_type` | str | null | Required for `meta` layer. One of `belief_change \| confidence_shift \| contradiction \| uncertainty \| correction \| insight` |
| `decay_class` | str | `"standard"` | Memory layer only. One of `ephemeral \| standard \| durable \| permanent` |
| `parent_chain_id` | str | null | Intelligence layer only. UUID of an existing chain this one continues (creates a CONTINUES edge) |
| `tags` | list[str] | null | Optional labels |

---

#### Memory layer

Observations and experiences. Decays over time.

```json
{
  "tool": "context_store",
  "arguments": {
    "content": "OAuth refresh tokens expire in 30 days per the auth service config.",
    "layer": "memory",
    "tags": ["auth", "tokens", "expiry"]
  }
}
```

Response:

```json
{
  "node_id": "node-abc-123",
  "layer": "memory",
  "created_at": "2026-04-28T09:00:00+00:00"
}
```

---

#### Knowledge layer

Claims that persist until contradicted. Evidence is required.

```json
{
  "tool": "context_store",
  "arguments": {
    "content": "The async connection pool uses a maximum of 20 connections by default.",
    "layer": "knowledge",
    "evidence": ["node:node-abc-123"],
    "source_type": "document",
    "tags": ["database", "async", "config"]
  }
}
```

Structured (SPO) content also accepted as a string or via tags; evidence must resolve to existing nodes:

```json
{
  "tool": "context_store",
  "arguments": {
    "content": "async-pool max_connections is 20",
    "layer": "knowledge",
    "evidence": ["node:node-abc-123", "node:node-def-456"],
    "source_type": "agent",
    "tags": ["database", "config"]
  }
}
```

Response:

```json
{
  "node_id": "node-claim-789",
  "layer": "knowledge",
  "evidence_status": "verified",
  "evidence_nodes": ["node-abc-123"],
  "status": "pending_promotion",
  "created_at": "2026-04-28T09:01:00+00:00"
}
```

Note: `status: pending_promotion` indicates the claim is queued for async fact promotion by the custodian.

---

#### Wisdom layer

Agent-scoped beliefs or stances. `about` is required — list the nodes this belief concerns.

```json
{
  "tool": "context_store",
  "arguments": {
    "content": "Exponential backoff is the preferred retry strategy for this service.",
    "layer": "wisdom",
    "about": ["node-abc-123", "node-def-456"],
    "tags": ["retry", "architecture"]
  }
}
```

Response:

```json
{
  "node_id": "node-wisdom-101",
  "layer": "wisdom",
  "declared_by": "agent-uuid-abc",
  "about_nodes": ["node-abc-123", "node-def-456"],
  "created_at": "2026-04-28T09:02:00+00:00"
}
```

---

#### Intelligence layer

Multi-step reasoning chains. `steps` is required. Crystallizations (emergent claims) are extracted automatically.

```json
{
  "tool": "context_store",
  "arguments": {
    "content": "asyncpg connection pool is the correct approach for this workload.",
    "layer": "intelligence",
    "steps": [
      {"step": 1, "reasoning": "Considered approach A: per-request connection.", "confidence": 0.6},
      {"step": 2, "reasoning": "Rejected — unacceptable latency overhead under load.", "confidence": 0.85},
      {"step": 3, "reasoning": "Settled on approach B: pooled connections with asyncpg.", "confidence": 0.95}
    ],
    "tags": ["database", "architecture"]
  }
}
```

Response:

```json
{
  "chain_id": "chain-uuid-xyz",
  "layer": "intelligence",
  "steps_count": 3,
  "crystallizations_queued": 1,
  "session_id": "session-uuid-abc",
  "created_at": "2026-04-28T09:03:00+00:00"
}
```

---

#### Meta layer

Meta-observations about cognition: belief changes, contradictions, confidence shifts, corrections, insights. `about` is required.

```json
{
  "tool": "context_store",
  "arguments": {
    "content": "My earlier confidence in approach A was too high; incident data contradicts it.",
    "layer": "meta",
    "observation_type": "contradiction",
    "about": ["node-abc-123", "node-claim-789"],
    "tags": ["contradiction"]
  }
}
```

Response:

```json
{
  "node_id": "node-reflect-202",
  "layer": "meta",
  "about_nodes": ["node-abc-123", "node-claim-789"],
  "created_at": "2026-04-28T09:04:00+00:00"
}
```

---

### context_recall

Read, search, traverse, or trace context. The `mode` param selects the operation.

**Params:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `query` | str | null | Semantic query string. Required for `search` and `graph` modes |
| `mode` | str | `"search"` | One of `search \| fetch \| graph \| history \| provenance` |
| `node_ids` | list[str] | null | Required for `fetch`, `history`, and `provenance` modes |
| `depth` | int | 0 | Values > 0 trigger graph traversal (used with `graph` mode, range 1-5) |
| `layers` | list[str] | null | Filter to specific layers: `memory \| knowledge \| wisdom \| intelligence \| meta` |
| `top_k` | int | 10 | Max results for `search` mode |
| `as_of` | str | null | ISO 8601 datetime for point-in-time queries |

---

#### search mode

Semantic search across layers.

```json
{
  "tool": "context_recall",
  "arguments": {
    "query": "How did we implement the async database connection pool?",
    "mode": "search",
    "layers": ["knowledge"],
    "top_k": 5
  }
}
```

Response:

```json
{
  "results": [
    {
      "node_id": "node-abc-123",
      "layer": "knowledge",
      "content": "Full content of the node...",
      "summary": "Implementation of async connection pool using asyncpg",
      "confidence": 0.94,
      "relevance_score": 0.91,
      "tags": ["python", "asyncpg", "connection-pool"],
      "created_at": "2026-02-05T14:30:00+00:00"
    }
  ],
  "total_candidates": 1,
  "search_time_ms": 45
}
```

---

#### fetch mode

Retrieve one or more nodes by ID.

```json
{
  "tool": "context_recall",
  "arguments": {
    "mode": "fetch",
    "node_ids": ["node-abc-123", "node-def-456"]
  }
}
```

Response:

```json
{
  "nodes": [
    {
      "node_id": "node-abc-123",
      "content": "Full content here...",
      "type": "Claim",
      "layer": "knowledge",
      "summary": "Implementation of async connection pool using asyncpg",
      "confidence": 0.87,
      "tags": ["python", "asyncpg"],
      "created_at": "2026-02-05T14:30:00+00:00"
    }
  ]
}
```

---

#### graph mode

Graph traversal from a semantic query or explicit seed nodes. Returns a subgraph. Set `depth` > 0 to hop the graph.

```json
{
  "tool": "context_recall",
  "arguments": {
    "query": "database connection decisions",
    "mode": "graph",
    "depth": 2,
    "top_k": 30
  }
}
```

With explicit seed nodes:

```json
{
  "tool": "context_recall",
  "arguments": {
    "mode": "graph",
    "node_ids": ["node-abc-123"],
    "depth": 2
  }
}
```

Response:

```json
{
  "nodes": [...],
  "edges": [...],
  "traversal_stats": {
    "depth_reached": 2,
    "nodes_visited": 18,
    "edges_traversed": 22
  }
}
```

---

#### history mode

Show how a belief or fact evolved over time. Traverses the SUPERSEDES chain oldest-to-newest.

```json
{
  "tool": "context_recall",
  "arguments": {
    "mode": "history",
    "node_ids": ["node-claim-789"]
  }
}
```

Response:

```json
{
  "timeline": [
    {
      "node_id": "node-claim-001",
      "content": "Connection pool max is 10.",
      "valid_from": "2026-01-01T00:00:00+00:00",
      "valid_to": "2026-02-01T00:00:00+00:00",
      "confidence": 0.7,
      "supersession_reason": "Revised after load testing"
    },
    {
      "node_id": "node-claim-789",
      "content": "Connection pool max is 20.",
      "valid_from": "2026-02-01T00:00:00+00:00",
      "valid_to": null,
      "confidence": 0.95,
      "supersession_reason": null
    }
  ],
  "current": "node-claim-789",
  "entries_count": 2
}
```

---

#### provenance mode

Trace a node's citation chain back to its Memory-layer sources. Follows DERIVED_FROM, PROMOTED_FROM, and SYNTHESIZED_FROM edges.

```json
{
  "tool": "context_recall",
  "arguments": {
    "mode": "provenance",
    "node_ids": ["node-claim-789"]
  }
}
```

Response:

```json
{
  "node_id": "node-claim-789",
  "chain": [
    {
      "node_id": "node-abc-123",
      "layer": "memory",
      "relationship": "PROMOTED_FROM",
      "confidence": 0.9
    }
  ],
  "root_sources": ["node-abc-123"],
  "chain_length": 1
}
```

---

### context_link

Create a typed relationship between two context nodes.

**Params:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `from_node` | str | required | Source node ID |
| `to_node` | str | required | Target node ID |
| `relationship` | str | required | One of `REFERENCES \| SUPPORTS \| CONTRADICTS \| DERIVED_FROM \| RELATED_TO \| CAUSES \| CORROBORATES \| PREVENTS` |
| `weight` | float | 1.0 | Edge weight, range 0.0-10.0 |
| `note` | str | null | Optional annotation on the edge |

```json
{
  "tool": "context_link",
  "arguments": {
    "from_node": "node-abc-123",
    "to_node": "node-def-456",
    "relationship": "REFERENCES",
    "weight": 1.0,
    "note": "Connection pool implementation references the asyncpg docs"
  }
}
```

Response:

```json
{
  "edge_id": "edge-uuid-xyz",
  "from_node": "node-abc-123",
  "to_node": "node-def-456",
  "relationship": "REFERENCES",
  "created_at": "2026-04-28T09:05:00+00:00"
}
```

---

## REST API (Admin / Dashboard)

Base path: `/api/v1`

### Lookup

```http
POST /api/v1/context/lookup
Content-Type: application/json
Authorization: Bearer {api_key}

{
  "silo_id": "silo-uuid-123",
  "query": "How did we implement the async database connection pool?",
  "filters": {
    "layer": "knowledge",
    "tags": ["database", "async"],
    "time_range": {
      "start": "2026-01-01T00:00:00Z",
      "end": "2026-04-30T23:59:59Z"
    }
  },
  "top_k": 5,
  "include_related": true,
  "max_depth": 2
}
```

### Store

```http
POST /api/v1/context
Content-Type: application/json
Authorization: Bearer {api_key}

{
  "silo_id": "silo-uuid-123",
  "content": "def handle_retry(func, max_retries=3): ...",
  "content_type": "code",
  "metadata": {
    "language": "python",
    "file_path": "/src/utils/retry.py"
  },
  "tags": ["python", "retry", "error-handling"]
}
```

Response:

```json
{
  "node_id": "node-new-123",
  "status": "created",
  "extraction_queued": true
}
```

### Get by ID

```http
GET /api/v1/nodes/{node_id}?silo_id=silo-uuid-123
Authorization: Bearer {api_key}
```

### Delete (with erasure cascade)

```http
DELETE /api/v1/nodes/{node_id}?silo_id=silo-uuid-123
Authorization: Bearer {api_key}
```

Response:

```json
{
  "node_id": "node-abc-123",
  "status": "deleted",
  "cascade": {
    "derived_nodes_nulled": 3,
    "vector_deleted": true
  }
}
```

---

## Agent Integration Patterns

### Pattern 1: Store then search

```python
# Agent stores an observation to Memory
result = await mcp.call("context_store", {
    "content": response_text,
    "layer": "memory",
    "tags": extract_tags(response_text),
})
node_id = result["node_id"]

# Later — agent searches across layers
results = await mcp.call("context_recall", {
    "query": current_query,
    "mode": "search",
    "top_k": 3,
})

# Fetch full content for top results
for r in results["results"]:
    node = await mcp.call("context_recall", {
        "mode": "fetch",
        "node_ids": [r["node_id"]],
    })
    # inject into prompt
```

### Pattern 2: Assert a claim with evidence

```python
# Agent asserts a Knowledge-layer claim backed by a Memory node
await mcp.call("context_store", {
    "content": "The retry helper uses exponential backoff with jitter.",
    "layer": "knowledge",
    "evidence": [f"node:{node_id}"],
    "source_type": "agent",
    "tags": ["retry", "error-handling"],
})
```

### Pattern 3: Multi-agent shared silo

Silo isolation is handled by auth. Agents sharing a silo see the same context without any extra params.

```python
# Agent A stores shared context
await mcp.call("context_store", {
    "content": "Database schema design decisions: ...",
    "layer": "memory",
    "tags": ["shared", "database", "architecture"],
})

# Agent B (different agent, same silo) searches
results = await mcp.call("context_recall", {
    "query": "What database decisions were made?",
    "mode": "search",
    "layers": ["memory", "knowledge"],
})
```

### Pattern 4: Graph traversal for related context

```python
# Seed with semantic search, then hop the graph
results = await mcp.call("context_recall", {
    "query": "database connection decisions",
    "mode": "graph",
    "depth": 2,
    "top_k": 30,
})
```

### Pattern 5: Reasoning chain to Intelligence layer

```python
# Store a reasoning chain — crystallizations become Knowledge candidates
await mcp.call("context_store", {
    "content": "Exponential backoff is preferred for all external calls.",
    "layer": "intelligence",
    "steps": reasoning_steps,  # list of {step, reasoning, confidence?}
    "tags": ["retry", "architecture"],
})
```

### Pattern 6: Commit a belief to Wisdom

```python
# Agent commits a synthesized judgment about prior nodes
await mcp.call("context_store", {
    "content": "Exponential backoff is the team standard for all external calls.",
    "layer": "wisdom",
    "about": [knowledge_node_id, chain_node_id],
    "tags": ["retry", "architecture"],
})
```

### Pattern 7: Trace provenance then history

```python
# Where did this fact come from?
prov = await mcp.call("context_recall", {
    "mode": "provenance",
    "node_ids": ["node-claim-789"],
})

# How did this fact evolve?
history = await mcp.call("context_recall", {
    "mode": "history",
    "node_ids": ["node-claim-789"],
})
```

---

## Error Handling

All MCP tools use a consistent error envelope:

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "details": {}
  },
  "ignored_flags": []
}
```

Error codes: `VALIDATION_ERROR`, `NOT_FOUND`, `CONFLICT`, `INTERNAL_ERROR`, `FEATURE_DISABLED`

### Node not found

```json
{
  "success": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "Node may have been deleted or does not belong to the current silo.",
    "details": {"node_id": "node-missing-123"}
  }
}
```

### Missing required param

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "evidence is required for the knowledge layer",
    "details": {"param": "evidence", "layer": "knowledge"}
  }
}
```

### Invalid evidence

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Evidence node does not exist in the silo",
    "details": {"evidence": "node:node-missing-999"}
  }
}
```

### Ignored flags

When callers pass flags that don't apply to the operation, they're reported:

```json
{
  "success": true,
  "nodes": [...],
  "ignored_flags": ["include_steps", "include_reflections"]
}
```

---

## Performance Targets

| Operation | Target |
|-----------|--------|
| `context_recall` fetch (cached) | < 20ms |
| `context_recall` search | < 250ms |
| `context_store` (single-layer writes) | < 300ms p95 |
| `context_recall` graph (depth 2) | < 500ms |
| `context_recall` history / provenance | < 400ms p95 |
