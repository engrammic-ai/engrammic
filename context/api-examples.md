# context-service — API Examples & Agent Integration Patterns

MCP is the primary agent-facing interface. The REST API is used for admin, dashboard, and silo management. Examples below cover both surfaces.

---

## MCP Tools (Agent Interface)

### context_store

Store a context node with automatic extraction.

```json
{
  "tool": "context_store",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "content": "OAuth refresh tokens expire in 30 days per the auth service config.",
    "content_type": "text",
    "metadata": {
      "source": "auth-service-docs",
      "author_agent": "agent-uuid-abc"
    },
    "tags": ["auth", "tokens", "expiry"]
  }
}
```

Response:

```json
{
  "node_id": "node-abc-123",
  "status": "created",
  "embedding_status": "indexed",
  "extraction_queued": true
}
```

### context_lookup

Semantic search within a silo.

```json
{
  "tool": "context_lookup",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "query": "How did we implement the async database connection pool?",
    "filters": {
      "layer": "knowledge",
      "tags": ["database", "async"]
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
      "summary": "Implementation of async connection pool using asyncpg",
      "layer": "knowledge",
      "relevance_score": 0.94,
      "tags": ["python", "asyncpg", "connection-pool"],
      "created_at": "2026-02-05T14:30:00Z"
    }
  ],
  "query_metadata": {
    "total_matches": 12,
    "search_time_ms": 45
  }
}
```

### context_get

Retrieve full node content by ID(s).

```json
{
  "tool": "context_get",
  "arguments": {
    "silo_id": "silo-uuid-123",
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
      "layer": "knowledge",
      "content": "Full content here...",
      "summary": "Implementation of async connection pool using asyncpg",
      "confidence": 0.87,
      "tags": ["python", "asyncpg"],
      "created_at": "2026-02-05T14:30:00Z",
      "last_accessed": "2026-02-09T10:15:00Z"
    }
  ]
}
```

### context_link

Create a relationship between two nodes.

```json
{
  "tool": "context_link",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "from_node_id": "node-abc-123",
    "to_node_id": "node-def-456",
    "relationship": "REFERENCES",
    "note": "Connection pool references the asyncpg docs"
  }
}
```

### context_graph

Graph-traversal retrieval — semantic seed then hop.

```json
{
  "tool": "context_graph",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "query": "database connection decisions",
    "max_depth": 2,
    "relationship_types": ["REFERENCES", "DERIVED_FROM"],
    "top_k": 5
  }
}
```

### context_store_chain

Store a reasoning chain with optional crystallizations.

```json
{
  "tool": "context_store_chain",
  "arguments": {
    "silo_id": "silo-uuid-123",
    "agent_id": "agent-uuid-abc",
    "steps": [
      {"step": 1, "reasoning": "First considered approach A..."},
      {"step": 2, "reasoning": "Rejected because of constraint X..."},
      {"step": 3, "reasoning": "Settled on approach B."}
    ],
    "crystallizations": [
      {
        "subject": "approach-b",
        "predicate": "chosen_because",
        "object": "avoids constraint X",
        "confidence": 0.9
      }
    ]
  }
}
```

### silo_create

Create a new silo (tenancy boundary).

```json
{
  "tool": "silo_create",
  "arguments": {
    "name": "my-project",
    "org_id": "org-uuid-123",
    "config": {
      "extraction_enabled": true,
      "decay_class": "standard"
    }
  }
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

### Pattern 1: Store and retrieve context

```python
# Agent stores important context
node_id = await mcp.call("context_store", {
    "silo_id": silo_id,
    "content": response_text,
    "tags": extract_tags(response_text),
})

# Later — agent retrieves context after compaction
results = await mcp.call("context_lookup", {
    "silo_id": silo_id,
    "query": current_query,
    "top_k": 3,
})

for r in results["results"]:
    node = await mcp.call("context_get", {
        "silo_id": silo_id,
        "node_ids": [r["node_id"]],
    })
    # inject into prompt
```

### Pattern 2: Multi-agent shared silo

```python
# Agent A stores shared context
await mcp.call("context_store", {
    "silo_id": "team-silo-123",  # shared silo
    "content": "Database schema design decisions: ...",
    "tags": ["shared", "database", "architecture"],
})

# Agent B (different agent, same silo) retrieves
results = await mcp.call("context_lookup", {
    "silo_id": "team-silo-123",
    "query": "What database decisions were made?",
    "filters": {"tags": ["shared"]},
})
```

### Pattern 3: Graph traversal for related context

```python
# Seed with semantic search, then hop the graph
results = await mcp.call("context_graph", {
    "silo_id": silo_id,
    "query": "database connection decisions",
    "max_depth": 2,
    "relationship_types": ["REFERENCES", "DERIVED_FROM"],
    "top_k": 5,
})
```

### Pattern 4: Reasoning chain with crystallization

```python
# Store reasoning chain — crystallizations become Claim candidates
await mcp.call("context_store_chain", {
    "silo_id": silo_id,
    "agent_id": my_agent_id,
    "steps": reasoning_steps,
    "crystallizations": [
        {
            "subject": "retry-strategy",
            "predicate": "chosen_because",
            "object": "exponential backoff reduces thundering herd",
            "confidence": 0.92,
        }
    ],
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
  "silo_id": "silo-uuid-missing",
  "message": "Silo does not exist or org_id mismatch."
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
| `context_lookup` | < 250ms |
| `context_store` | < 300ms p95 |
| `context_graph` | < 500ms (depth 2) |
| `context_store_chain` | < 400ms p95 |
