# MCP Tool Surface Simplification Brainstorm

**Date:** 2026-05-03
**Status:** In progress

## Problem

Current surface: 15 MCP tools with 5-8 params each. Pain points:
- `silo_id` required on every call (derivable from auth)
- `agent_id` always None (AuthContext bug)
- `session_id` always None (same bug)
- Too many tools = LLM confusion
- ~2250 tokens in system prompt for tool schemas

## Inspiration

Pi coding agent: 4 tools only (Read, Write, Edit, Bash), shortest system prompt.
"If you strip down to minimum, frontier models perform better."

## Research Findings

### Pattern Analysis
- CRUD consolidation: 5 write tools are really one tool with `layer` param
- Verb consolidation: 7 read tools fragment a unified retrieval concept
- Convention over configuration: derive what you can, explicit only when needed

### Integration Constraints
- AuthContext needs `agent_id`, `session_id` fields (currently broken)
- `silo_id` fully derivable from auth
- stdio transport (Claude Desktop) has no headers
- Each tool beyond 5-6 adds noise for LLM selection

### Tradeoffs
- Keep explicit layers (inference unreliable, core value prop)
- Keep structured `steps` for reasoning (auditable chains)
- 9 tools safe, 5 requires runtime validation tradeoff

## Design Decision

**Two-tier architecture:**

```
┌─────────────────────────────────────────┐
│           Agent Harness                 │
│  ┌─────────────────────────────────┐    │
│  │  Skills (installed prompts)     │    │
│  │  - research_and_remember        │    │
│  │  - fact_check                   │    │
│  │  - summarize_beliefs            │    │
│  │  - trace_reasoning              │    │
│  └─────────────────────────────────┘    │
│                  │                      │
│                  ▼                      │
│  ┌─────────────────────────────────┐    │
│  │  MCP Tools (3 core)             │    │
│  │  - context_store                │    │
│  │  - context_recall               │    │
│  │  - context_link                 │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
                   │
                   ▼
         ┌─────────────────┐
         │ Context Service │
         └─────────────────┘
```

## Core MCP Tools (3)

### context_store

Store content to epistemic memory.

```python
context_store(
    content: str,
    layer: str = "memory",  # memory|knowledge|wisdom|intelligence|meta
    evidence: list[str] | None = None,   # required for knowledge
    about: list[str] | None = None,      # required for wisdom/meta
    steps: list[dict] | None = None,     # required for intelligence
    tags: list[str] | None = None,
    session: str | None = None,
) -> {"node_id": str, "layer": str}
```

**Layer behavior:**
| Layer | Decays | Requires | Creates |
|-------|--------|----------|---------|
| memory | Yes | - | Memory node |
| knowledge | No | evidence | Claim (promotes to Fact via sage.custodian) |
| wisdom | No | about | Belief/Commitment |
| intelligence | No | steps | ReasoningChain |
| meta | No | about | MetaObservation |

### context_recall

Retrieve from epistemic memory.

```python
context_recall(
    query: str,
    mode: str = "search",  # search|fetch|graph|history|provenance
    node_ids: list[str] | None = None,  # for fetch/history/provenance modes
    depth: int = 0,        # 0 = flat, 1-3 = graph traversal
    layers: list[str] | None = None,
    top_k: int = 10,
    as_of: str | None = None,  # time-travel
) -> {"results": [...], "mode": str}
```

**Mode behavior:**
| Mode | Uses query | Uses node_ids | Returns |
|------|------------|---------------|---------|
| search | Yes | No | Semantic search results |
| fetch | No | Yes | Nodes by ID |
| graph | Yes or node_ids | Optional | Subgraph traversal |
| history | No | Yes (one) | Supersession chain |
| provenance | No | Yes (one) | Citation chain to sources |

### context_link

Create relationship between nodes.

```python
context_link(
    from_id: str,
    to_id: str,
    rel: str,  # supports|contradicts|derives|supersedes|references
    weight: float = 1.0,
    note: str | None = None,
) -> {"edge_id": str, "rel": str}
```

## Skills (Agent-Side)

Skills are prompt templates that compose core tools. Installed in agent harness, not service.

### Design Principles

1. **Narrow scope**: Skills handle epistemic memory ONLY (remember, recall, reason, reflect)
2. **Complementary**: Complex workflows should defer to gsd/superpowers skills when available
3. **Explicit triggers**: Each skill has trigger phrases for pattern matching
4. **Composable**: Skills use the 3 core MCP tools, nothing else

### Scope Boundaries

| Context Skills (ours) | Workflow Skills (defer to) |
|-----------------------|---------------------------|
| observe, learn, recall | plan, execute, brainstorm |
| trace, reflect, reason | debug, review, ship |
| fact_check, connect, research | task management, code review |

Skills that touch workflow (research, fact_check, connect) should include:
> "For complex multi-step workflows, use gsd or superpowers skills if available."

---

### Skill: observe

Simplest write - just remember something.

```yaml
name: observe
triggers:
  - "remember this"
  - "note that"
  - "I noticed"
  - "storing observation"
template: |
  Use context_store to record this observation.
  
  context_store(
    content="{observation}",
    layer="memory",
    tags={extracted_tags}
  )
```

### Skill: learn

Store a fact with evidence.

```yaml
name: learn
triggers:
  - "I learned"
  - "this means"
  - "the fact is"
  - "storing fact"
template: |
  1. Identify the claim being made
  2. Identify evidence (prior node IDs or external refs)
  3. Store as knowledge:
  
  context_store(
    content="{claim}",
    layer="knowledge",
    evidence=[{evidence_ids}]
  )
```

### Skill: recall

Search and retrieve from memory.

```yaml
name: recall
triggers:
  - "what do I know about"
  - "search memory"
  - "find in context"
  - "retrieve"
template: |
  Search epistemic memory for relevant content.
  
  context_recall(
    query="{query}",
    mode="search",
    layers={layers_if_specified},
    top_k={limit_or_10}
  )
  
  For graph exploration, add depth:
  context_recall(query="{query}", depth=2)
```

### Skill: trace

Understand how a belief was formed.

```yaml
name: trace
triggers:
  - "why do I believe"
  - "where did this come from"
  - "trace provenance"
  - "show reasoning chain"
template: |
  1. Find the belief:
     context_recall(query="{belief}", mode="search", layers=["wisdom", "knowledge"])
  
  2. Get provenance:
     context_recall(mode="provenance", node_ids=[{belief_id}])
  
  3. Explain the chain:
     - Original source (Memory)
     - Extracted claims (Knowledge)
     - Synthesized belief (Wisdom)
```

### Skill: reflect

Meta-cognitive observation.

```yaml
name: reflect
triggers:
  - "I notice a pattern"
  - "this contradicts"
  - "my confidence changed"
  - "storing reflection"
template: |
  1. Identify what you're reflecting on (node IDs)
  2. Classify the observation type:
     - belief_change
     - contradiction
     - uncertainty
     - insight
  
  3. Store meta-observation:
     context_store(
       content="{observation}",
       layer="meta",
       about=[{relevant_node_ids}]
     )
```

### Skill: reason

Multi-step reasoning with audit trail.

```yaml
name: reason
triggers:
  - "let me think through"
  - "reasoning about"
  - "analyzing step by step"
  - "structured thinking"
template: |
  1. Gather evidence:
     context_recall(query="{topic}", top_k=10)
  
  2. Structure your reasoning as steps:
     steps = [
       {"step": "observation", "reasoning": "...", "confidence": 0.9},
       {"step": "inference", "reasoning": "...", "confidence": 0.8},
       {"step": "conclusion", "reasoning": "...", "confidence": 0.85}
     ]
  
  3. Store the chain:
     context_store(
       content="{conclusion}",
       layer="intelligence",
       steps=steps,
       evidence=[{source_ids}]
     )
```

---

### Workflow-Adjacent Skills

These skills touch workflow concerns. They should defer to gsd/superpowers for complex multi-step work.

### Skill: research

Research a topic, synthesize findings.

```yaml
name: research
triggers:
  - "research this topic"
  - "deep dive on"
  - "gather information about"
category: workflow-adjacent
template: |
  NOTE: For complex research workflows, use gsd or superpowers skills if available.
  This skill handles epistemic memory lookup only.
  
  1. Search existing knowledge:
     context_recall(query="{topic}", top_k=20)
  
  2. Analyze results for:
     - Direct answers
     - Related facts
     - Confidence levels
     - Gaps in knowledge
  
  3. Optionally store synthesis as new belief:
     context_store(content="{synthesis}", layer="wisdom", about=[{source_ids}])
```

### Skill: fact_check

Verify a claim against existing knowledge.

```yaml
name: fact_check
triggers:
  - "is this true"
  - "verify this"
  - "fact check"
  - "check against knowledge"
category: workflow-adjacent
template: |
  NOTE: For complex verification workflows, use gsd or superpowers skills if available.
  This skill checks against stored epistemic memory only.
  
  1. Search for related knowledge:
     context_recall(query="{claim}", layers=["knowledge", "wisdom"])
  
  2. Look for:
     - Supporting evidence
     - Contradicting evidence
     - Confidence levels
  
  3. If contradiction found, link it:
     context_link(from_id={claim_id}, to_id={contradicting_id}, rel="contradicts")
  
  4. Optionally reflect on the discrepancy:
     context_store(content="Found contradiction...", layer="meta", about=[...])
```

### Skill: connect

Find and create relationships between concepts.

```yaml
name: connect
triggers:
  - "how does X relate to Y"
  - "connect these concepts"
  - "link these nodes"
  - "find relationship"
category: workflow-adjacent
template: |
  NOTE: For complex relationship analysis, use gsd or superpowers skills if available.
  This skill handles direct node linking only.
  
  1. Recall both concepts:
     a = context_recall(query="{concept_a}")
     b = context_recall(query="{concept_b}")
  
  2. Analyze relationship:
     - Does A support B?
     - Does A contradict B?
     - Does A derive from B?
  
  3. Create the link:
     context_link(from_id={a_id}, to_id={b_id}, rel="{relationship}")
```

## Final Skill Inventory

### Core Skills (6)
| Skill | Triggers | Layer touched |
|-------|----------|---------------|
| observe | "remember this", "I noticed" | memory |
| learn | "I learned", "the fact is" | knowledge |
| recall | "what do I know about", "search" | all (read) |
| trace | "why do I believe", "provenance" | all (read) |
| reflect | "I notice a pattern", "contradicts" | meta |
| reason | "let me think through", "analyzing" | intelligence |

### Workflow-Adjacent Skills (3)
| Skill | Triggers | Defers to |
|-------|----------|-----------|
| research | "research this", "deep dive" | gsd/superpowers |
| fact_check | "is this true", "verify" | gsd/superpowers |
| connect | "how does X relate to Y" | gsd/superpowers |

## Token Comparison

| Surface | Count | Tokens | Notes |
|---------|-------|--------|-------|
| Current MCP tools | 15 | ~2250 | ~150 tokens/tool |
| New MCP tools | 3 | ~540 | ~180 tokens/tool |
| Core skills | 6 | ~420 | ~70 tokens/skill |
| Workflow-adjacent skills | 3 | ~300 | ~100 tokens/skill (longer due to deferral notes) |
| **New total** | | **~1260** | |
| **Savings** | | **~990** | **44% reduction** |

Skills are agent-side prompts, not MCP schema. Token cost depends on whether harness loads all skills or just relevant ones.

## Migration Path

### Phase 1: Foundation (v1.4.1)
- Fix AuthContext (agent_id, session_id)
- Make silo_id optional on existing tools
- No breaking changes

### Phase 2: New Surface (v1.4.2)
- Add 3 new simplified tools alongside existing
- Deprecate old tools via description prefix
- Ship skills package

### Phase 3: Cleanup (v1.5)
- Remove deprecated tools
- Document skills-first approach

## Open Questions

1. ~~**Skill format:**~~ YAML in markdown files (decided)
2. ~~**Skill distribution:**~~ Package or curl install (decided)
3. **Skill discovery:** How does agent know which skills are available? Options:
   - Listed in system prompt (explicit)
   - Discovered via `context_admin(action="list_skills")` (dynamic)
   - Harness injects based on available integrations
4. **Layer inference:** Should `context_store` without explicit layer try to infer, or always default to memory?
   - Leaning: default to memory (safe), never infer (predictable)
5. **Skill location:** context-service repo for now, move to primitives if we OSS the engine
6. ~~**Triggers:**~~ Explicit trigger phrases per skill (decided)

## References

- [Pi Agent Philosophy](https://lucumr.pocoo.org/2026/1/31/pi/)
- [Pi-Mono GitHub](https://github.com/badlogic/pi-mono)
- [v1.4.1 QoL Plan](../plans/v1.4.1-mcp-qol.md)
