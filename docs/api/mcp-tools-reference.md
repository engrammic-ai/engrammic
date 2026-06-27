# MCP Tools Reference

Complete reference for the Engrammic MCP tool surface. Source of truth: `src/context_service/config/mcp_tools.yaml`.

## Quick Reference

| Tool | Purpose | Layer |
|------|---------|-------|
| `remember` | Store observation | Memory |
| `learn` | Record claim with evidence | Knowledge |
| `recall` | Search or fetch knowledge | All |
| `trace` | Walk provenance chain | All |
| `forget` | Tombstone a node | All |
| `tick` | Engagement check, decay prevention | - |
| `update` | Supersede existing knowledge | Knowledge |
| `agents` | List agents in silo | - |
| `introspect` | Metacognitive queries | - |
| `conflicts` | List contradictions | - |
| `dismiss_conflict` | Mark as not-a-conflict | - |
| `escalate_conflict` | Flag for human review | - |
| `resolve_conflict` | Pick winner, supersede loser | - |

---

## Core Write Tools

### remember

Store an observation to memory. No evidence required.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `content` | string | Yes | - | What to remember |
| `tags` | string[] | No | null | Categorization tags |
| `decay` | string | No | "standard" | Decay class: `ephemeral` \| `standard` \| `durable` \| `permanent` |
| `supersedes` | string | No | null | Node ID this replaces (use `recall` first to find it) |
| `memory_type` | string | No | null | Type: `observation` \| `reflection` \| `event` \| `document` |
| `about` | string[] | No | null | Node IDs this memory is about (creates ABOUT edges) |

#### Response

```json
{
  "node_id": "uuid",
  "created_at": "2024-01-01T00:00:00Z",
  "supersedes": "uuid-if-provided"
}
```

#### Notes

- Reflections (`memory_type="reflection"`) don't decay and require `about` to link to referenced nodes.
- Node becomes searchable within ~500ms (async embedding). For immediate recall, use `recall(node_ids=[node_id])`.
- When `supersedes` is omitted, the write triggers [write-time supersession detection](#write-time-supersession-detection); the response may include `auto_superseded`, `likely_updates`, or `possible_updates`.

---

### learn

Record a claim with evidence. Writes a Knowledge-layer Claim node.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `claim` | string | Yes | - | What you learned |
| `evidence` | string[] | Yes | - | References: `node:<uuid>` or URI |
| `source` | string | Yes | - | Source type: `document` \| `user` \| `external` \| `agent` |
| `confidence` | float | No | 0.8 | Confidence score 0.0-1.0 |
| `tags` | string[] | No | null | Categorization tags |
| `source_tier` | string | No | null | Quality hint: `authoritative` \| `validated` \| `community` \| `unknown` |
| `supersedes` | string | No | null | Node ID this claim replaces |

#### Response

```json
{
  "node_id": "uuid",
  "layer": "knowledge",
  "claim_type": "spo",
  "evidence_status": "verified",
  "evidence_nodes": ["uuid"],
  "created_at": "2024-01-01T00:00:00Z",
  "supersedes": "uuid-if-provided",
  "warning": "optional warning if evidence missing"
}
```

`evidence_status` is `verified` when evidence is validated synchronously, or `pending` when validation is deferred.

#### Notes

- Evidence is required by default. If enforcement is enabled and evidence is empty, returns an error.
- Use `source_tier` to hint quality when you know it (e.g., `.gov`/`.edu` = `authoritative`).
- HTTP-fetches evidence URLs for validation. Private/auth-gated URLs will fail validation.
- When `supersedes` is omitted, the write triggers [write-time supersession detection](#write-time-supersession-detection); the response may include `auto_superseded`, `likely_updates`, or `possible_updates`.

---

### update

Supersede existing knowledge with new content. Knowledge-layer only.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `content` | string | Yes | - | Updated claim content |
| `evidence` | string[] | Yes | - | References for the new claim |
| `query` | string | No* | - | Semantic search to find target node |
| `target` | string | No* | - | Explicit node ID to supersede |
| `source_tier` | string | No | null | Quality tier hint |
| `confidence` | float | No | 0.8 | Confidence 0.0-1.0 |

*One of `query` or `target` is required.

#### Response

Success:
```json
{
  "status": "updated",
  "node_id": "new-uuid",
  "superseded_id": "old-uuid",
  "superseded_content": "first 200 chars of old content"
}
```

Ambiguous (multiple matches):
```json
{
  "status": "ambiguous",
  "candidates": [
    {"id": "uuid", "content": "snippet", "similarity": 0.85, "created_at": "..."},
    {"id": "uuid", "content": "snippet", "similarity": 0.72, "created_at": "..."}
  ]
}
```

Not found:
```json
{
  "status": "not_found",
  "message": "No existing knowledge matches query. Use learn() to create new."
}
```

Error (wrong layer):
```json
{
  "status": "error",
  "error": "wrong_layer",
  "message": "update is Knowledge-layer only (Claims). Target 'xyz' is a 'Memory' node.",
  "actual_label": "Memory"
}
```

#### Notes

- Only works on Claim nodes (Knowledge layer). Cannot update Memory/Belief nodes.
- Query path uses 0.7 similarity threshold. If multiple matches above threshold, returns `ambiguous`.
- Cannot supersede already-superseded nodes; returns `already_superseded` with `head_id` of the chain head.

---

## Core Read Tools

### recall

Search or fetch knowledge. Primary retrieval tool.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `query` | string | No* | - | Semantic search query. Use `"*"` to list all |
| `node_ids` | string[] | No* | - | Specific nodes to fetch |
| `depth` | int | No | 0 | Graph traversal depth: 0=flat, 1-3=neighbors |
| `layers` | string[] | No | null | Filter: `memory` \| `knowledge` \| `wisdom` \| `intelligence` |
| `top_k` | int | No | 10 | Max results for search |
| `min_threshold` | float | No | null | Relevance cutoff 0.0-1.0 |
| `include_withheld` | bool | No | false | Show low-confidence/conflicted nodes |
| `include_content` | bool | No | true | Return full content (false = summaries) |
| `fusion_mode` | bool | No | false | Run semantic+graph retrieval with RRF fusion |
| `since` | string | No | null | Temporal filter start (requires `fusion_mode`) |
| `until` | string | No | null | Temporal filter end |
| `graph_depth` | int | No | 2 | BFS depth for graph channel in fusion mode |
| `include_hints` | bool | No | false | Get belief candidate suggestions |
| `include_inactive` | bool | No | false | Include superseded/tombstoned nodes |
| `agent_id` | string | No | null | Filter to nodes by this agent |
| `exclude_agents` | string[] | No | null | Exclude nodes by these agents |
| `include_conflicts` | bool | No | false | Return contradicting nodes in `conflict_nodes` |
| `tags` | string[] | No | null | Filter to nodes having ALL specified tags |
| `include_hypotheses` | bool | No | false | Include unconfirmed hypothesis nodes |
| `bypass_cache` | bool | No | false | Force fresh search |
| `max_age_seconds` | int | No | null | Max cache age before refresh |

*At least one of `query` or `node_ids` should be provided.

#### Response

```json
{
  "results": [
    {
      "node_id": "uuid",
      "content": "...",
      "layer": "knowledge",
      "confidence": 0.85,
      "conflict_status": "none",
      "credibility": 0.9,
      "credibility_factors": {"source_tier": 0.3, "age": 0.2, ...}
    }
  ],
  "withheld": {
    "count": 2,
    "message": "2 memories withheld (low confidence...). Pass include_withheld=true to see them."
  },
  "engagement": {
    "markers": [...],
    "mode": "soft"
  },
  "has_unresolved_conflicts": false,
  "epistemic_hints": null,
  "conflict_nodes": []
}
```

#### Temporal Filtering

Requires `fusion_mode=True`. Accepts:
- Relative: `"7d"`, `"1w"`, `"30d"`
- ISO datetime: `"2024-01-01"`, `"2024-01-01T00:00:00Z"`

```json
{"query": "auth changes", "fusion_mode": true, "since": "7d"}
```

#### Notes

- Call at session start and before storing (to supersede, not duplicate).
- Hard engagement mode suppresses all results until markers are resolved.
- Low-confidence and unresolved-contradiction nodes withheld by default.

---

### trace

Walk provenance chain to understand why you believe something.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `node_id` | string | Yes | - | Node to trace |
| `direction` | string | No | "up" | `up` = sources (why), `down` = dependents (impact) |
| `max_depth` | int | No | 5 | Max traversal depth |
| `edge_types` | string[] | No | null | Filter edges: `DERIVED_FROM`, `PROMOTED_FROM`, `SYNTHESIZED_FROM`, `REFERENCES` |

#### Response

```json
{
  "direction": "up",
  "max_depth": 5,
  "chain": [
    {
      "node_id": "uuid",
      "layer": "knowledge",
      "relationship": "DERIVED_FROM",
      "confidence": 0.85,
      "stub": false
    }
  ],
  "root_sources": ["uuid", "uuid"]
}
```

When `direction="down"`:
```json
{
  "direction": "down",
  "max_depth": 5,
  "chain": [...],
  "leaf_nodes": ["uuid", "uuid"]
}
```

---

## Engagement Tools

### tick

Lightweight engagement check. Safe to call frequently.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `about_hint` | string[] | No | null | Node IDs to scope check and update access time |
| `silo_id` | string | No | null | Silo UUID (defaults to org's primary) |
| `session_id` | string | No | null | Session ID for continuity |
| `recent_context` | string | No | null | Current work context (reserved for future) |
| `engagement_type` | string | No | "viewed" | `viewed` (+0.5 heat), `used` (+1.0), `confirmed` (+2.0) |

#### Response

```json
{
  "status": "ok",
  "session_id": "uuid",
  "engagement": {
    "markers": [...],
    "mode": "soft"
  },
  "markers": [...],
  "context": [],
  "nudges": [
    {"type": "pending_markers", "message": "...", "priority": 1}
  ],
  "meta": {
    "checks_completed": ["markers", "storage_gap"],
    "checks_skipped": [],
    "latency_ms": 12.5,
    "nodes_updated": 3,
    "engagement_type": "viewed"
  }
}
```

Status values: `ok`, `current` (no pending work), `partial` (some checks skipped), `error`.

#### Notes

- When `about_hint` provided, updates `last_accessed_at` to prevent decay.
- Pass `session_id` back on subsequent calls for continuity and debouncing.

---

### conflicts

List contradictions between nodes.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `silo_id` | string | No | null | Silo UUID |
| `agent_id` | string | No | null | Filter to conflicts involving this agent |
| `status` | string | No | "unresolved" | Filter by resolution status |
| `limit` | int | No | 50 | Max results |

#### Response

```json
{
  "conflicts": [
    {
      "id": "conflict-uuid",
      "node_a_id": "uuid",
      "node_a_content": "...",
      "agent_a": "agent-id",
      "node_b_id": "uuid",
      "node_b_content": "...",
      "agent_b": "agent-id",
      "detected_at": "2024-01-01T00:00:00Z",
      "detected_by": "custodian",
      "resolution_status": "unresolved"
    }
  ],
  "count": 1
}
```

---

### dismiss_conflict

Mark a conflict as not-a-real-conflict.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `conflict_id` | string | Yes | - | CONTRADICTS edge ID |
| `reason` | string | No | null | Explanation for audit |
| `silo_id` | string | No | null | Silo UUID |

#### Response

```json
{
  "conflict_id": "uuid",
  "status": "dismissed",
  "reason": "Different contexts, not actually contradictory"
}
```

---

### escalate_conflict

Flag a conflict for human review.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `conflict_id` | string | Yes | - | CONTRADICTS edge ID |
| `message` | string | No | null | Context for reviewer |
| `silo_id` | string | No | null | Silo UUID |

#### Response

```json
{
  "conflict_id": "uuid",
  "status": "escalated",
  "message": "Need domain expert to verify"
}
```

---

### resolve_conflict

Pick a winner and optionally supersede the loser.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `conflict_id` | string | Yes | - | CONTRADICTS edge ID |
| `winner_id` | string | Yes | - | Node ID of authoritative node |
| `supersede` | bool | No | true | Mark loser as superseded by winner |
| `silo_id` | string | No | null | Silo UUID |

#### Response

```json
{
  "conflict_id": "uuid",
  "status": "superseded",
  "winner_id": "uuid"
}
```

---

## Lifecycle Tools

### forget

Request deletion of a node. Enters tombstone state before permanent deletion.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `node_id` | string | Yes | - | Node to forget |
| `reason` | string | No | null | Audit trail reason |
| `cascade` | bool | No | false | Also tombstone downstream references |

#### Response

Success:
```json
{
  "status": "tombstoned",
  "node_id": "uuid",
  "tombstoned_at": "2024-01-01T00:00:00Z",
  "cascade_count": 3
}
```

Not found:
```json
{
  "status": "not_found",
  "node_id": "uuid"
}
```

---

## Coordination Tools

### agents

List agents registered in the silo.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `silo_id` | string | No | null | Silo UUID |

#### Response

```json
{
  "agents": [
    {
      "agent_id": "uuid",
      "role": "assistant",
      "first_seen": "2024-01-01T00:00:00Z",
      "last_seen": "2024-01-15T00:00:00Z",
      "node_count": 42,
      "trust_score": 0.85
    }
  ],
  "count": 1
}
```

---

### introspect

Metacognitive queries about epistemic health.

#### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `query_type` | string | Yes | - | `volatility` \| `gaps` \| `provenance` \| `contributions` |
| `node_id` | string | No | null | Required for `provenance` |
| `agent_id` | string | No | null | For `contributions` (defaults to self) |
| `min_threshold` | int | No | varies | Min chain length (volatility) or ask count (gaps) |
| `limit` | int | No | 10 | Max results |

#### Query Types

**volatility** - Topics with high supersession churn (unstable knowledge)
```json
{
  "query_type": "volatility",
  "volatile_topics": [
    {"topic": "auth config", "chain_length": 5, "last_change": "..."}
  ],
  "count": 1
}
```

**gaps** - Frequently-asked but unanswered queries
```json
{
  "query_type": "gaps",
  "knowledge_gaps": [
    {"query": "deployment process", "ask_count": 4, "last_asked": "..."}
  ],
  "count": 1
}
```

**provenance** - Which agents contributed to a belief
```json
{
  "query_type": "provenance",
  "node_id": "uuid",
  "contributing_agents": ["agent-1", "agent-2"],
  "source_chain": [...]
}
```

**contributions** - Agent contribution stats
```json
{
  "query_type": "contributions",
  "agent_id": "uuid",
  "total_nodes": 42,
  "by_layer": {"memory": 20, "knowledge": 22},
  "promoted_count": 5
}
```

---

## Common Patterns

### Supersession Pattern

Always recall before storing to chain updates:

```
1. recall("API auth method")
2. Found node abc123: "Uses OAuth2"
3. learn("Uses OAuth2 with PKCE", evidence=[...], supersedes="abc123")
```

### Write-time Supersession Detection

When you call `remember` or `learn` **without** an explicit `supersedes`, the
system checks whether the new write likely replaces an existing node, so you
don't silently duplicate knowledge. Detection runs in tiers and stops at the
first confident match:

1. `session_recall` - a node you recalled earlier this session, matched by subject
2. `spo_match` / `subject_match` - same agent, matching subject-predicate-object
3. `semantic_similarity` - embedding similarity fallback (never auto-supersedes)

The response may carry up to three extra fields:

```json
{
  "node_id": "new-uuid",
  "auto_superseded": "old-uuid",
  "likely_updates": [
    {"id": "uuid", "subject": "...", "predicate": "...", "object": "...", "reason": "spo_match"}
  ],
  "possible_updates": [
    {"id": "uuid", "reason": "semantic_similarity"}
  ]
}
```

- `auto_superseded` - a high-confidence match the system chained automatically
  (only when auto-supersede is enabled). The new node already supersedes it.
- `likely_updates` - high-confidence candidates surfaced for you to confirm with
  an explicit `update`/`supersedes`.
- `possible_updates` - lower-confidence (semantic-only) candidates; review before acting.

Detection is config-gated (`supersession_detection.*`); when disabled, these
fields are absent.

### Session Continuity

Pass `session_id` back to maintain state:

```
1. tick() -> {session_id: "xyz", ...}
2. tick(session_id="xyz") -> uses same session
3. recall(...) -> engagement checked against session
```

### Trust Gate

Low-confidence and conflicted nodes are withheld by default:

```json
{
  "results": [...],
  "withheld": {
    "count": 2,
    "message": "Pass include_withheld=true to see them."
  }
}
```

---

## Error Responses

All tools return errors in this format:

```json
{
  "error": "error_code",
  "message": "Human-readable description"
}
```

Common error codes:
- `missing_node_id` - Required node_id not provided
- `missing_evidence` - Evidence required but not provided
- `not_found` - Node or conflict doesn't exist
- `already_superseded` - Cannot supersede already-superseded node
- `wrong_layer` - Operation not valid for this node type
- `invalid_edge_types` - Unknown edge type in filter
- `service_unavailable` - Backend service not available
