# context-service — API Examples & Agent Integration Patterns

MCP is the primary agent-facing interface. The REST API is used for admin, dashboard, and silo management. Examples below cover both surfaces.

The 13 MCP tools are:

- Reads: `context_get`, `context_query`, `context_graph`, `context_history`, `context_provenance`
- Writes: `context_remember` (Memory), `context_assert` (Knowledge), `context_commit` (Wisdom), `context_reason` (Intelligence), `context_reflect` (meta-memory)
- Linking: `context_link`
- Tenancy: `silo_create`, `silo_list`

---

## MCP Tools (Agent Interface)

### context_remember

Store an experience or observation to the Memory layer. Memories decay over time.

**Params:** `silo_id` (str, required), `content` (str, required), `content_type` (str, default `"text"`), `metadata` (dict|null), `tags` (list[str]|null), `decay_class` (str, default `"standard"` — one of `ephemeral|standard|durable|permanent`), `observed_from` (str|null — attribution, e.g. `"user:<id>"` or `"agent:<id>"`).

```json
{
  "tool": "context_remember",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "content": "OAuth refresh tokens expire in 30 days per the auth service config.",
    "content_type": "text",
    "tags": ["auth", "tokens", "expiry"],
    "decay_class": "durable",
    "observed_from": "agent:agent-uuid-abc"
  }
}
```

Response:

```json
{
  "node_id": "node-abc-123",
  "layer": "memory",
  "decay_class": "durable",
  "created_at": "2026-04-28T09:00:00+00:00"
}
```

---

### context_assert

Assert a claim to the Knowledge layer. Evidence is required. Claims persist until contradicted (no decay).

**Params:** `silo_id` (str, required), `claim` (str or `{subject, predicate, object}` dict, required), `evidence` (str or list[str], required — `node:<uuid>` refs or URIs), `source_type` (str, required — one of `document|user|external|agent`), `confidence` (float, default `0.8`, range 0.0-1.0), `metadata` (dict|null), `tags` (list[str]|null), `evidence_mode` (str, default `"sync"` — `sync` validates evidence first, `async` validates later), `source_tier` (str|null — one of `authoritative|validated|community|unknown`; defaults to `unknown` if omitted, which fails R1 single-source promotion).

```json
{
  "tool": "context_assert",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "claim": "The async connection pool uses a maximum of 20 connections by default.",
    "evidence": "node:node-abc-123",
    "source_type": "document",
    "confidence": 0.9,
    "tags": ["database", "async", "config"],
    "source_tier": "authoritative"
  }
}
```

Structured (SPO) claim form:

```json
{
  "tool": "context_assert",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "claim": {
      "subject": "async-pool",
      "predicate": "max_connections",
      "object": "20"
    },
    "evidence": ["node:node-abc-123", "node:node-def-456"],
    "source_type": "document",
    "confidence": 0.95,
    "source_tier": "authoritative"
  }
}
```

Response:

```json
{
  "node_id": "node-claim-789",
  "layer": "knowledge",
  "claim_type": "freeform",
  "evidence_status": "verified",
  "evidence_nodes": ["node-abc-123"],
  "promoted_to_fact": true,
  "created_at": "2026-04-28T09:01:00+00:00"
}
```

---

### context_commit

Commit a belief or stance to the Wisdom layer. Commitments are agent-scoped via DECLARED_BY edge.

**Params:** `silo_id` (str, required), `belief` (str, required), `about` (list[str], required — node IDs this belief concerns, at least one), `confidence` (float, default `0.8`), `reasoning` (str|null — why the agent holds this belief), `metadata` (dict|null), `tags` (list[str]|null).

```json
{
  "tool": "context_commit",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "belief": "Exponential backoff is the preferred retry strategy for this service.",
    "about": ["node-abc-123", "node-def-456"],
    "confidence": 0.92,
    "reasoning": "Two separate incidents showed linear retry causing thundering herd; exponential backoff resolved both.",
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

### context_reason

Store a multi-step reasoning chain to the Intelligence layer. Optionally extract crystallizations (beliefs or claims) from the chain.

**Params:** `silo_id` (str, required), `steps` (list[dict], required — each dict has `step` (int), `reasoning` (str), optional `confidence` (float)), `conclusion` (str|null), `evidence_used` (list[str]|null — `node:<uuid>` or URI refs), `crystallizations` (list[dict]|null — each dict has `claim` (str), optional `confidence` (float)).

```json
{
  "tool": "context_reason",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "steps": [
      {"step": 1, "reasoning": "First considered approach A: per-request connection.", "confidence": 0.6},
      {"step": 2, "reasoning": "Rejected because of latency overhead under load.", "confidence": 0.85},
      {"step": 3, "reasoning": "Settled on approach B: pooled connections with asyncpg.", "confidence": 0.95}
    ],
    "conclusion": "asyncpg connection pool is the correct approach for this workload.",
    "evidence_used": ["node:node-abc-123"],
    "crystallizations": [
      {
        "claim": "Per-request connection creation adds unacceptable latency at scale.",
        "confidence": 0.85
      }
    ]
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

### context_reflect

Store a meta-observation about cognition. Use for belief changes, contradictions, confidence shifts, corrections, or insights.

**Params:** `silo_id` (str, required), `observation` (str, required), `observation_type` (str, required — one of `belief_change|confidence_shift|contradiction|uncertainty|correction|insight`), `about` (list[str], required — node IDs this observation concerns), `confidence` (float, default `0.8`), `metadata` (dict|null).

```json
{
  "tool": "context_reflect",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "observation": "My earlier confidence in approach A was too high; incident data contradicts it.",
    "observation_type": "contradiction",
    "about": ["node-abc-123", "node-claim-789"],
    "confidence": 0.9
  }
}
```

Response:

```json
{
  "node_id": "node-reflect-202",
  "observation_type": "contradiction",
  "about_nodes": ["node-abc-123", "node-claim-789"],
  "created_at": "2026-04-28T09:04:00+00:00"
}
```

---

### context_get

Retrieve one or more context nodes by ID.

**Params:** `node_ids` (str or list[str], required), `silo_id` (str|null — defaults to the org's primary silo), `as_of` (str|null — reserved for point-in-time retrieval; currently returns `as_of_not_supported` if non-null).

```json
{
  "tool": "context_get",
  "arguments": {
    "node_ids": ["node-abc-123", "node-def-456"],
    "silo_id": "silo-uuid-123"
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
      "silo_id": "silo-uuid-123",
      "properties": {},
      "source_uri": null,
      "content_hash": "sha256-abc...",
      "layer": "knowledge",
      "summary": "Implementation of async connection pool using asyncpg",
      "confidence": 0.87,
      "tags": ["python", "asyncpg"],
      "created_at": "2026-02-05T14:30:00+00:00"
    }
  ]
}
```

Note: passing `as_of` currently returns an error:

```json
{
  "error": "as_of_not_supported",
  "message": "Point-in-time retrieval is not yet implemented"
}
```

---

### context_query

Semantic search across layers with optional filtering.

**Params:** `silo_id` (str, required), `query` (str, required), `layers` (list[str]|null — `memory|knowledge|wisdom|intelligence`), `filters` (dict|null — keys: `tags`, `source_type`, `min_confidence`, `created_after`, `created_before`), `top_k` (int, default `10`), `include_superseded` (bool, default `false`), `as_of` (str|null — reserved, returns `as_of_not_supported` if non-null).

```json
{
  "tool": "context_query",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "query": "How did we implement the async database connection pool?",
    "layers": ["knowledge"],
    "filters": {
      "tags": ["database", "async"],
      "min_confidence": 0.7
    },
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

### context_graph

Graph traversal from a semantic query or explicit seed nodes. Returns a subgraph.

**Params:** `silo_id` (str, required), `query` (str|null — semantic seed), `seed_nodes` (list[str]|null — explicit starting node IDs), `max_depth` (int, default `2`, range 1-5), `max_nodes` (int, default `50`, range 1-200), `relationship_types` (list[str]|null — e.g. `["REFERENCES", "SUPPORTS"]`), `layers` (list[str]|null — filter nodes to specific layers). At least one of `query` or `seed_nodes` is required.

```json
{
  "tool": "context_graph",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "query": "database connection decisions",
    "max_depth": 2,
    "max_nodes": 30,
    "relationship_types": ["REFERENCES", "DERIVED_FROM"]
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

### context_history

Show how a belief or fact evolved over time. Traverses the SUPERSEDES chain oldest-to-newest.

**Params:** `silo_id` (str, required), `subject` (str|null — keyword to search for), `node_id` (str|null — specific node to trace). At least one of `subject` or `node_id` is required.

```json
{
  "tool": "context_history",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "node_id": "node-claim-789"
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

### context_provenance

Trace a node's citation chain back to its Memory-layer sources. Follows DERIVED_FROM, PROMOTED_FROM, and SYNTHESIZED_FROM edges.

**Params:** `silo_id` (str, required), `node_id` (str, required), `max_depth` (int, default `10`).

```json
{
  "tool": "context_provenance",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "node_id": "node-claim-789",
    "max_depth": 5
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

**Params:** `silo_id` (str, required), `from_node` (str, required), `to_node` (str, required), `relationship` (str, required — one of `REFERENCES|SUPPORTS|CONTRADICTS|DERIVED_FROM|RELATED_TO`), `weight` (float, default `1.0`, range 0.0-10.0), `note` (str|null — optional annotation on the edge).

```json
{
  "tool": "context_link",
  "arguments": {
    "silo_id": "silo-uuid-123",
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

### silo_create

Create a new organizational silo (tenancy boundary).

**Params:** `name` (str, required), `description` (str|null), `dissolvability` (float, default `0.5` — cross-silo traversal permeability, 0.0 = fully isolated, 1.0 = fully open).

```json
{
  "tool": "silo_create",
  "arguments": {
    "name": "my-project",
    "description": "Silo for the auth service team",
    "dissolvability": 0.3
  }
}
```

Response:

```json
{
  "silo_id": "silo-uuid-new",
  "name": "my-project",
  "org_id": "org-uuid-123",
  "description": "Silo for the auth service team",
  "dissolvability": 0.3
}
```

---

### silo_list

List all silos for the current tenant. Takes no arguments.

```json
{
  "tool": "silo_list",
  "arguments": {}
}
```

Response:

```json
{
  "silos": [
    {
      "silo_id": "silo-uuid-123",
      "name": "my-project",
      "org_id": "org-uuid-123",
      "description": "Silo for the auth service team",
      "dissolvability": 0.3
    }
  ]
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

### Pattern 1: Remember then query

```python
# Agent stores an observation to Memory
result = await mcp.call("context_remember", {
    "silo_id": silo_id,
    "content": response_text,
    "tags": extract_tags(response_text),
    "decay_class": "standard",
})
node_id = result["node_id"]

# Later — agent searches across layers
results = await mcp.call("context_query", {
    "silo_id": silo_id,
    "query": current_query,
    "top_k": 3,
})

for r in results["results"]:
    node = await mcp.call("context_get", {
        "node_ids": [r["node_id"]],
        "silo_id": silo_id,
    })
    # inject into prompt
```

### Pattern 2: Assert a claim with evidence

```python
# Agent asserts a Knowledge-layer claim backed by a Memory node
await mcp.call("context_assert", {
    "silo_id": silo_id,
    "claim": "The retry helper uses exponential backoff with jitter.",
    "evidence": f"node:{node_id}",
    "source_type": "agent",
    "confidence": 0.88,
    "source_tier": "validated",
    "tags": ["retry", "error-handling"],
})
```

### Pattern 3: Multi-agent shared silo

```python
# Agent A stores shared context
await mcp.call("context_remember", {
    "silo_id": "team-silo-123",  # shared silo
    "content": "Database schema design decisions: ...",
    "tags": ["shared", "database", "architecture"],
})

# Agent B (different agent, same silo) searches
results = await mcp.call("context_query", {
    "silo_id": "team-silo-123",
    "query": "What database decisions were made?",
    "filters": {"tags": ["shared"]},
})
```

### Pattern 4: Graph traversal for related context

```python
# Seed with semantic search, then hop the graph
results = await mcp.call("context_graph", {
    "silo_id": silo_id,
    "query": "database connection decisions",
    "max_depth": 2,
    "max_nodes": 30,
    "relationship_types": ["REFERENCES", "DERIVED_FROM"],
})
```

### Pattern 5: Reasoning chain with crystallization

```python
# Store a reasoning chain — crystallizations become Claim candidates
await mcp.call("context_reason", {
    "silo_id": silo_id,
    "steps": reasoning_steps,   # list of {step, reasoning, confidence?}
    "conclusion": "Exponential backoff is preferred.",
    "evidence_used": [f"node:{evidence_node_id}"],
    "crystallizations": [
        {
            "claim": "Exponential backoff reduces thundering herd at high concurrency.",
            "confidence": 0.92,
        }
    ],
})
```

### Pattern 6: Commit a belief to Wisdom

```python
# Agent commits a synthesized judgment about prior nodes
await mcp.call("context_commit", {
    "silo_id": silo_id,
    "belief": "Exponential backoff is the team standard for all external calls.",
    "about": [knowledge_node_id, chain_node_id],
    "confidence": 0.95,
    "reasoning": "Consistent with two post-mortems and the retry policy doc.",
})
```

---

## Error Handling

### Node not found

```json
{
  "error": "node_not_found",
  "node_id": "node-missing-123",
  "message": "Node may have been deleted or the silo_id is wrong."
}
```

### Silo not found

```json
{
  "error": "silo_not_found",
  "silo_id": "silo-uuid-missing"
}
```

### Invalid evidence

```json
{
  "error": "invalid_evidence",
  "evidence": "node:node-missing-999",
  "reason": "Node does not exist in the silo"
}
```

### as_of not yet supported

```json
{
  "error": "as_of_not_supported",
  "message": "Point-in-time retrieval is not yet implemented"
}
```

### Rate limiting

```json
{
  "error": "rate_limit_exceeded",
  "retry_after": 60,
  "quota": {
    "limit": 1000,
    "remaining": 0,
    "reset_at": "2026-04-26T11:00:00Z"
  }
}
```

---

## Performance Targets

| Operation | Target |
|-----------|--------|
| `context_get` (cached) | < 20ms |
| `context_query` | < 250ms |
| `context_remember` / `context_assert` / `context_commit` / `context_reflect` (single-layer writes) | < 300ms p95 |
| `context_graph` (depth 2) | < 500ms |
| `context_reason` (chained) | < 400ms p95 |
