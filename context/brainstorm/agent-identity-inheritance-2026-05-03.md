# Agent Identity Inheritance Brainstorm

**Date**: 2026-05-03
**Status**: Ready for planning

## Problem Statement

Current `agent_id` implementation is broken: `getattr(auth, "agent_id", None)` always returns `None` because `AuthContext` has no `agent_id` field. This breaks:

1. **Attribution**: MetaObservation with `agent_id = "org-abc123"` can't distinguish orchestrator from worker
2. **Reflection isolation**: Worker reflections pollute silo-wide meta-memory
3. **Consensus scoring**: R2 rule counts `distinct produced_by_agent_id` - all chains look like same source

## Research Findings

### Actor Model Patterns (Akka/Erlang)

Supervision trees are the closest analog:
- Parent creates child, becomes supervisor
- If parent stops, children recursively stop
- Single inheritance (one supervisor per actor)
- **Incarnation concept**: identity = path + UID, not just name

Three identity patterns in multi-agent systems:
| Pattern | Description | Problem |
|---------|-------------|---------|
| Full inheritance | Child gets parent's permissions | Violates least privilege |
| Service account | Child gets static credential | Outlives task |
| No scoping | Child runs in auth vacuum | No auditability |

Production recommendation: Per-agent identity with version + deployment ID.

### Existing Systems Evaluated

**Memory Infrastructure**:
- Zep: Time-indexed knowledge graph, async ingestion. Closest to meta-memory.
- Mem0: Vector + fact extraction. Simpler than our 4-tier model.
- Letta: 3-tier (core/archival/recall). Agent manages own context.

**Multi-Agent Frameworks**:
- LangGraph: Checkpointing + time-travel, identity implicit in graph state
- CrewAI: Role-based, no cross-run identity persistence
- OpenAgents: Native MCP + A2A, persistent agent networks

**Verdict**: None replace our core value prop (epistemic memory, belief promotion, consensus). Agent identity inheritance doesn't exist as standalone component - embedded in orchestration frameworks.

### OpenAgents Deep Dive

"Slack for agents" - collaboration/networking layer:
- Workspace (browser UI) + Launcher (orchestration) + Network SDK
- Persistent agent identities within networks
- Native MCP + A2A support
- No graph DB or knowledge structures

**Different concern**: They solve agent networking (who talks to whom). We solve epistemic memory (who believed what). Complementary, not competing.

## Proposed Design

### Architecture: Thin Wire via Headers

```
Authorization: Bearer <api_key>
X-Agent-Id: <stable_agent_identifier>
X-Parent-Agent-Id: <parent_identifier>   # optional
X-Agent-Role: orchestrator|worker|peer   # optional
```

### Data Model

New `:Agent` node:
```cypher
(:Agent {
  agent_id: string,
  role: string,
  lineage_root_id: string,  # denormalized for O(1) queries
  silo_id: string,
  created_at: datetime
})
```

New edge: `SPAWNED_BY` (child)-[:SPAWNED_BY]->(parent)

### Key Design Decisions

1. **Denormalized `lineage_root_id`**: Avoids multi-hop traversal for ancestry
2. **3-hop max depth**: Risk mitigation for graph traversal
3. **Silo-scoped**: All lineage queries include silo boundary check
4. **Opt-in inheritance**: Existing agents work without changes
5. **Validate parent**: Parent must exist in same silo before writing edge

### Lineage Queries

Fast path (uses denormalized root):
```cypher
MATCH (a:Agent {silo_id: $silo_id})
WHERE a.lineage_root_id = $root_agent_id
RETURN a.agent_id, a.role
```

Full ancestry (bounded):
```cypher
MATCH path = (a:Agent {agent_id: $agent_id})-[:SPAWNED_BY*0..3]->(ancestor)
WHERE ancestor.silo_id = $silo_id
RETURN [node IN nodes(path) | node.agent_id] AS lineage
```

## Risk Assessment

### P1 Critical

| Risk | Mitigation |
|------|------------|
| Graph traversal complexity | 3-hop bound + index Agent(id, silo_id) + Redis cache |
| Silo boundary leakage | Mandatory silo check in all lineage queries |
| AuthContext schema break | Optional field, backward compatible |
| Reflection scope creep | Gate visibility through edge traversal only |

### P2 Medium

| Risk | Mitigation |
|------|------------|
| Migration of existing data | Lazy MERGE, opt-in backfill script |
| Identity sprawl | Depth limit + archival policy for stale agents |
| MCP tool changes | Optional parameters, existing clients unaffected |

## Open Questions

1. **WorkOS agent_id source**: Custom attribute vs derived from `user_id`?
2. **Caller-supplied override**: Allow orchestrators to pass worker identity?
3. **CONTINUES vs DERIVED_FROM**: Chain handoff semantics?
4. **Custodian vote counting**: Should custodian chains count toward R2 consensus?

## Implementation Phases

**Phase A - Foundation** (unblocks everything):
- Add `agent_id: str | None` to AuthContext
- Parse X-Agent-Id headers in MCP
- Fix dev fallback, remove getattr guards

**Phase B - Graph Structure**:
- Add `:Agent` node, `SPAWNED_BY` edge
- Upsert on first write
- Denormalize lineage_root_id

**Phase C - Consumer Features**:
- `context_get_reflections(agent_id=...)` filter
- `context_reason(parent_chain_id=...)` for handoffs
- Custodian identity constant

**Phase D - Migration**:
- Backfill script for existing nodes
- Add indexes

## Files Affected

| File | Change |
|------|--------|
| `auth/context.py` | Add `agent_id: str \| None` |
| `mcp/server.py` | Parse agent headers |
| `models/inference.py` | Add `AgentIdentity` model |
| `engine/queries.py` | UPSERT_AGENT, CREATE_SPAWNED_BY |
| `engine/protocols.py` | `upsert_agent()` method |
| `engine/memgraph_store.py` | Implement upsert |
| `mcp/tools/context_*.py` | Wire agent upsert |
| `db/indexes.py` | Agent indexes |
| `primitives/.../edges.py` | SPAWNED_BY edge type |

## References

- [Akka Actor Systems](https://doc.akka.io/libraries/akka-core/current/general/actor-systems.html)
- [The Identity Problem Agents Create](https://luminitydigital.com/the-identity-problem-agents-create/)
- [Hierarchical Multi-Agent Systems Taxonomy](https://arxiv.org/html/2508.12683v1)
- [AI Agent Memory Comparison 2026](https://explore.n1n.ai/blog/ai-agent-memory-comparison-2026-mem0-zep-letta-cognee-2026-04-23)
- [OpenAgents GitHub](https://github.com/openagents-org/openagents)
