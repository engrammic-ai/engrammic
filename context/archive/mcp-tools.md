# MCP Tool Specifications

**Status:** draft
**Date:** 2026-04-26

Tool interface specs for EAG-compatible MCP servers. Implementations live in product repos; these specs define the contract.

## Core Tools (MVP)

### context_store

Store content into the knowledge graph.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| content | string | yes | Text content to store |
| metadata | object | no | Arbitrary metadata (source, tags, etc.) |
| silo_id | string | no | Target silo (uses default if omitted) |
| node_type | string | no | "document" \| "passage" \| "utterance" (default: "document") |

**Returns:**
```json
{
  "node_id": "uuid",
  "silo_id": "uuid",
  "extracted_claims": ["claim_id_1", "claim_id_2"]
}
```

### context_get

Retrieve node(s) by ID.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| node_ids | string \| string[] | yes | One or more node IDs |
| include_edges | boolean | no | Include connected edges (default: false) |

**Returns:**
```json
{
  "nodes": [
    {
      "id": "uuid",
      "content": "...",
      "node_type": "document",
      "metadata": {},
      "created_at": "iso8601",
      "edges": []
    }
  ]
}
```

### context_lookup

Semantic search across knowledge.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| query | string | yes | Natural language query |
| limit | integer | no | Max results (default: 10) |
| silo_id | string | no | Scope to silo |
| node_types | string[] | no | Filter by type |
| min_score | float | no | Minimum similarity threshold |

**Returns:**
```json
{
  "results": [
    {
      "node_id": "uuid",
      "content": "...",
      "score": 0.87,
      "node_type": "passage"
    }
  ]
}
```

### context_link

Create relationship between nodes.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| source_id | string | yes | Source node ID |
| target_id | string | yes | Target node ID |
| edge_type | string | yes | Relationship type (RELATES_TO, SUPPORTS, CONTRADICTS, etc.) |
| metadata | object | no | Edge metadata |

**Returns:**
```json
{
  "edge_id": "uuid",
  "source_id": "...",
  "target_id": "...",
  "edge_type": "SUPPORTS"
}
```

### context_delete

Delete a node (with optional cascade).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| node_id | string | yes | Node to delete |
| cascade | boolean | no | Delete derived nodes (default: false) |

**Returns:**
```json
{
  "deleted": true,
  "node_id": "...",
  "cascade_count": 0
}
```

## Silo Tools

### silo_create

Create a new silo.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | yes | Silo display name |
| description | string | no | Silo description |

**Returns:**
```json
{
  "silo_id": "uuid",
  "name": "...",
  "created_at": "iso8601"
}
```

### silo_list

List available silos.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:**
```json
{
  "silos": [
    {
      "silo_id": "uuid",
      "name": "...",
      "node_count": 42
    }
  ]
}
```

## Advanced Tools (Post-MVP)

### context_batch_store

Batch store multiple items.

### context_graph

Graph traversal retrieval (PPR-based).

### context_store_chain

Store reasoning chain with crystallizations.

### context_get_own_drafts

Retrieve agent's own draft commitments/chains.

## Implementation Notes

- All tools should validate `silo_id` scope before operations
- Tools return structured JSON, never raw text
- Errors use standard MCP error format with codes
- Rate limiting is product-specific, not in spec
