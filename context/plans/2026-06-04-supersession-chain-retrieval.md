# Supersession Chain Retrieval

**Status:** Ready  
**Date:** 2026-06-04  
**Context:** Somnus benchmark revealed agents can't query full supersession chains

## Problem

Agents can CREATE supersession chains (`learn(..., supersedes=node_id)`) but can't READ them:

| What agents can do today | What's missing |
|--------------------------|----------------|
| `recall(query)` → finds current nodes | Can't include superseded versions |
| `recall(node_id=X)` on expired node → `{error: "node_expired", superseded_by: Y}` | Must loop manually to walk chain |
| `trace(node_id)` → follows CITES/ABOUT/DERIVED_FROM | Doesn't follow SUPERSEDES |

The backend has `ContextService.history()` that traverses SUPERSEDES chains, but it's not exposed via MCP.

## Design Principle

**Two tools at MCP surface, unified backend.**

Agent-facing tools are focused and discoverable:
- `trace(node_id)` — "where did this come from?" (provenance)
- `history(node_id)` — "how did this evolve?" (versioning)

Backend uses generalized graph traversal that both tools dispatch to. This keeps the agent surface simple while the plumbing stays DRY.

## Use Cases

1. **"What did I used to believe about X?"** — Agent recalls a topic, wants to see how understanding evolved
2. **"Why was this superseded?"** — Agent finds superseded_by pointer, wants the reason/context
3. **"Show me the full version history"** — Debug/audit, understanding belief drift
4. **"Find when a fact changed"** — Temporal queries ("what did I know about auth before May?")

## Options Considered

### A. Manual chaining (no code change)
Agent loops: `recall(node_id) → check superseded_by → recall(superseded_by) → repeat`

**Rejected:** Clunky, N round-trips for N-length chain, no atomicity.

### B. Add `include_superseded` flag to `recall`
```
recall(query="API auth", include_superseded=true)
```
Returns flat list including old versions.

**Rejected:** Loses chain structure (which came first? are there branches?). Doesn't answer "show me the evolution".

### C. Single flexible `trace` with `edge_types` param
```
trace(node_id, edge_types=["SUPERSEDES"])
```

**Rejected:** Composable but less discoverable. Agents need to know the param exists and what edge types mean. Response shape also differs between provenance (tree) and supersession (chain).

### D. Two focused tools, unified backend (recommended)
```
trace(node_id)    # provenance (existing)
history(node_id)  # versioning (new)
```

Both dispatch to generalized graph traversal backend. Agent surface is simple and discoverable; plumbing stays DRY. Can add `edge_types` param to `trace` later for power users if needed.

## Proposed Design

### Tool signature

```yaml
history:
  description: |
    Show how a belief evolved over time. Returns the supersession chain
    from oldest to newest. Use when you need to understand how knowledge
    changed, not just what it is now.
  maps_to: history
```

### Parameters

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `node_id` | string | Yes | Start from this node, walk SUPERSEDES chain |

Note: `subject` param was considered but rejected. Mixing search semantics into traversal is fuzzy (what if subject matches multiple chains?). Agents should do `recall("topic") → history(node_id)` instead. Clean separation of concerns.

### Response

```json
{
  "timeline": [
    {
      "node_id": "oldest_abc",
      "content": "API uses basic auth",
      "valid_from": "2026-01-15T10:00:00Z",
      "valid_to": "2026-03-20T14:30:00Z",
      "confidence": 0.8,
      "supersession_reason": null
    },
    {
      "node_id": "middle_def",
      "content": "API uses OAuth2",
      "valid_from": "2026-03-20T14:30:00Z",
      "valid_to": "2026-05-10T09:00:00Z",
      "confidence": 0.9,
      "supersession_reason": "Found OAuth2 config in codebase"
    },
    {
      "node_id": "current_ghi",
      "content": "API uses OAuth2 with PKCE",
      "valid_from": "2026-05-10T09:00:00Z",
      "valid_to": null,
      "confidence": 0.95,
      "supersession_reason": "Security audit required PKCE"
    }
  ]
}
```

Notes:
- `current` field removed — it's just `timeline[-1]` where `valid_to: null`
- `chain_length` removed — it's just `len(timeline)`
- Timeline ordered by **chain-walk order** (not `valid_from`) — follows SUPERSEDES edges from oldest to newest
- Current node is always the last entry with `valid_to: null`
- `supersession_reason` field omitted on root node (not null)
- No pagination in v1 — long chains return full list; add `max_items` if needed later

### Edge cases

| Case | Behavior |
|------|----------|
| Node has no supersession history | `timeline` has 1 entry (the node itself) |
| Node is in middle of chain | Walks both directions, returns full chain |
| Node not found | `{error: "not_found", node_id: "..."}` |
| Edge ID passed instead of node ID | `{error: "invalid_node_id", message: "..."}` |
| SUPERSEDES cycle (malformed data) | Cycle detection, return `{error: "cycle_detected", partial_chain: [...]}` with path up to cycle point |
| Branched supersession (multiple nodes supersede same predecessor) | Return all branches as tree: `{branches: [[...], [...]], warning: "branched_history"}`. Don't error on valid data. |
| Node in chain was `forget`-ed | Tombstone entry: `{node_id, deleted: true, deleted_at}`. Content redacted for GDPR compliance. |

## Integration with existing tools

```
┌─────────────────────────────────────────────────────────────┐
│                     Agent workflows                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  "What do I know about X?"     →  recall(query)             │
│  "Where did this come from?"   →  trace(node_id)            │
│  "How did this evolve?"        →  history(node_id)  ← NEW   │
│  "Update my understanding"     →  learn(..., supersedes=Y)  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Typical flow for exploring evolution

```
1. recall("API authentication")           # find relevant nodes
2. history(node_id="abc123")              # see how it evolved
3. trace(node_id="abc123")                # see what evidence supports current version
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│  trace (MCP)    │     │  history (MCP)  │
└────────┬────────┘     └────────┬────────┘
         │                       │
         │  edge_types=          │  edge_types=
         │  [CITES,DERIVED...]   │  [SUPERSEDES]
         │                       │
         └───────────┬───────────┘
                     │
              ┌──────▼──────┐
              │ graph_walk  │  ← unified backend
              │ (cycle-safe)│
              └─────────────┘
```

## Skill updates needed

1. **New `engrammic-history` skill** — when/how to use history tool
2. **Update `engrammic-eag-guide`** — add history to the tool table, mention in supersession section
3. **Update `engrammic-recall` skill** — cross-reference history for evolution queries

## Implementation plan

### Phase 1: Backend — unified graph traversal (~45 min)

- [ ] Create `src/context_service/services/graph_walk.py`
  - Generalized traversal: `graph_walk(node_id, edge_types, direction, max_depth)`
  - Cycle detection built-in
  - Both `trace` and `history` will dispatch here
- [ ] Add Cypher query for bidirectional SUPERSEDES walk (find full chain from any node)
- [ ] Update `ContextService.history()` to use `graph_walk`

### Phase 2: MCP tool (~20 min)

- [ ] Create `src/context_service/mcp/tools/history.py`
  - Single param: `node_id`
  - Returns `{timeline: [...]}`
  - Rate limiting, auth, telemetry (copy pattern from trace.py)
- [ ] Add to `mcp_tools.yaml`
- [ ] Register in `src/context_service/mcp/tools/__init__.py`
- [ ] Add test in `tests/mcp/test_history.py`

### Phase 3: Skill updates (~15 min)

- [ ] Create `~/.claude/skills/engrammic-history/SKILL.md`
- [ ] Update `engrammic-eag-guide` supersession section — mention `history` for reading chains
- [ ] Update `engrammic-recall` to cross-reference history for evolution queries

### Phase 4: Verify on Somnus (~10 min)

- [ ] Run Somnus queries that need history traversal
- [ ] Confirm chain retrieval works end-to-end

## Future work (not in scope)

1. **`as_of` temporal queries** — "what was the current belief about X as of March 1?" Add when needed.

2. **`include_superseded` on recall** — for old versions in search results without chain structure. See if `history` covers use cases first.

3. **`edge_types` param on trace** — power-user escape hatch for custom traversals. Backend will support it; surface when there's demand.

4. **Branched supersession** — if we ever need merge semantics, revisit the schema and traversal logic.
