# MCP Tool Surface Redesign

**Status:** Draft
**Created:** 2026-05-15
**Goal:** Intent-based tool surface for external agents with configurable profiles

## Problem

Current MCP surface has issues:
- 10 tools with unclear boundaries (context_store, context_recall, context_admin, etc.)
- Layer-based naming requires agents to understand EAG internals
- `context_admin` is a grab-bag of unrelated actions meant for internal use
- MCP instructions don't match actual tool names
- 97% of MCP tool descriptions have quality issues (per research)

## Design Principles

Based on research ([arxiv MCP study](https://arxiv.org/html/2602.14878v1), [agent design patterns](https://onagents.org/patterns/)):

1. **Intent-based naming** - tools named for what agent wants to do, not implementation layer
2. **Clear purpose** - most important factor in tool descriptions
3. **Fewer tools** - don't overwhelm; use profiles to expose relevant subsets
4. **Progressive complexity** - simple path works, advanced features available
5. **Configurable** - different harnesses need different surfaces

## Tool Profiles

Two profiles, selectable per-silo or per-connection:

### standard (default) - 6 tools

For most agents. Covers observe, claim, believe, search, trace, connect.

### reasoning - 11 tools

For extended reasoning sessions with tentative belief management. Adds reasoning chains, meta-observations, hypothesis workflow.

```yaml
profiles:
  standard:
    - remember
    - learn
    - believe
    - recall
    - trace
    - link

  reasoning:
    - remember
    - learn
    - believe
    - reason
    - reflect
    - recall
    - trace
    - link
    - hypothesize
    - revise
    - commit
```

## Tool Definitions

### Standard Profile

#### remember

Store an observation.

```python
remember(
    content: str,              # What to remember
    tags: list[str] = None,    # Optional categorization
    decay: str = "standard",   # ephemeral|standard|durable|permanent
) -> {node_id, created_at}
```

**Description:** "Store an observation. Use for raw information you may need later - conversations, facts encountered, things you noticed. No evidence required."

**Maps to:** Memory layer (Document node)

---

#### learn

Assert a claim with evidence.

```python
learn(
    claim: str,                # What you learned
    evidence: list[str],       # REQUIRED: node:<id> or URI
    source: str,               # document|user|external|agent
    confidence: float = 0.8,   # 0.0-1.0
    tags: list[str] = None,
) -> {node_id, evidence_status, created_at}
```

**Description:** "Record something you learned with evidence. Evidence is required - reference memory nodes or external URIs. Claims without evidence should be observations (remember) not claims (learn)."

**Maps to:** Knowledge layer (Claim node)

---

#### believe

Declare a commitment.

```python
believe(
    belief: str,               # What you believe
    about: list[str],          # REQUIRED: node IDs this concerns
    confidence: float = 0.8,   # 0.0-1.0
    reasoning: str = None,     # Why you believe this
) -> {node_id, created_at}
```

**Description:** "Declare a belief as a commitment. Use when you've synthesized knowledge into a conclusion. Requires 'about' - what nodes led to this belief. For tentative beliefs during reasoning, use hypothesize instead."

**Maps to:** Wisdom layer (Commitment node)

---

#### recall

Search or fetch knowledge.

```python
recall(
    query: str = None,         # Natural language search
    node_ids: list[str] = None,# Specific nodes to fetch
    depth: int = 0,            # 0=flat, 1-3=graph traversal
    layers: list[str] = None,  # memory|knowledge|wisdom|intelligence
    top_k: int = 10,           # Max results for search
) -> {results|nodes, ...}
```

**Description:** "Retrieve knowledge. Search by query or fetch by node_id. Set depth > 0 for graph traversal from seed nodes."

**Maps to:** context_recall (unchanged behavior)

---

#### trace

Explain why you believe something.

```python
trace(
    node_id: str,              # Node to trace
) -> {chain: [...], root_sources: [...]}
```

**Description:** "Trace the provenance of a belief or claim back to its sources. Returns the citation chain showing what evidence supports it."

**Maps to:** context_admin(action="provenance") - extracted to standalone tool

---

#### link

Create a relationship.

```python
link(
    from_node: str,            # Source node
    to_node: str,              # Target node
    relationship: str,         # supports|contradicts|derives|references|causes|supersedes
    weight: float = 1.0,       # 0.0-10.0
    note: str = None,          # Optional annotation
) -> {edge_id, created_at}
```

**Description:** "Create a typed relationship between nodes. Use to build explicit connections in the knowledge graph."

**Maps to:** context_link (unchanged)

---

### Reasoning Profile Additions

#### reason

Record a reasoning chain.

```python
reason(
    steps: list[{step, reasoning, confidence?}],  # Reasoning steps
    conclusion: str = None,    # Final conclusion
    evidence_used: list[str] = None,  # Nodes referenced
) -> {chain_id, session_id, created_at}
```

**Description:** "Record explicit reasoning steps. Use when working through a complex problem. Captures your thought process for later reference and reuse."

**Maps to:** context_store(layer="intelligence")

---

#### reflect

Note a meta-observation.

```python
reflect(
    observation: str,          # What you noticed
    type: str,                 # pattern|contradiction|uncertainty|drift
    about: list[str],          # REQUIRED: nodes this concerns
    confidence: float = 0.8,
) -> {node_id, created_at}
```

**Description:** "Record a meta-observation about your knowledge. Use when you notice patterns, contradictions, or uncertainty in what you know."

**Maps to:** context_store(layer="meta")

---

#### hypothesize

Form a tentative belief.

```python
hypothesize(
    hypothesis: str,           # Tentative belief
    about: list[str],          # REQUIRED: nodes this concerns
    session_id: str,           # Reasoning session
    confidence: float = 0.8,
) -> {belief_id, potential_conflicts, created_at}
```

**Description:** "Form a tentative belief during reasoning. Unlike believe, hypotheses can be revised as you learn more. Use commit to finalize when confident."

**Maps to:** context_store(layer="belief")

---

#### revise

Update a tentative belief.

```python
revise(
    belief_id: str,            # Hypothesis to update
    confidence: float,         # New confidence
    content: str = None,       # New content (optional)
    reason: str,               # REQUIRED: why revising
) -> {updated_at}
```

**Description:** "Update a tentative hypothesis. Use when new information changes your confidence or understanding."

**Maps to:** context_update_belief

---

#### commit

Crystallize to commitment.

```python
commit(
    belief_ids: list[str],     # Hypotheses to commit
    reason: str = None,        # Why committing now
) -> {committed: [...], superseded: [...]}
```

**Description:** "Promote tentative hypotheses to permanent commitments. Use when you're confident in your conclusions."

**Maps to:** context_crystallize

---

## Internal-Only Tools

These are NOT exposed to external agents. Used by SAGE and internal systems via direct service calls:

| Current Tool | Internal Use |
|--------------|--------------|
| context_admin | Silo management, session lifecycle |
| context_accept_belief | SAGE Custodian accepting ProposedBeliefs |
| context_reject_belief | SAGE Custodian rejecting ProposedBeliefs |
| context_belief_state | Internal session inspection |

## MCP Instructions

```
Engrammic: Epistemic memory for AI agents.

Quick start:
- remember: store observations
- learn: record claims WITH evidence
- believe: declare conclusions
- recall: search your knowledge
- trace: understand why you believe something
- link: connect related knowledge

Guidelines:
- Always provide evidence when using learn
- Reference existing nodes when forming beliefs
- Use recall before storing to avoid duplicates
```

## Profile Configuration

Profiles are configurable at:
1. **Silo level** - default profile for all connections to a silo
2. **Connection level** - override via MCP connection params

```yaml
# silo config
default_tool_profile: standard

# or per-connection
mcp_connect(profile="reasoning")
```

Implementation registers tools dynamically based on profile:

```python
def register_tools(mcp: FastMCP, profile: str = "standard"):
    tools = PROFILES[profile]
    
    if "remember" in tools:
        register_remember(mcp)
    if "learn" in tools:
        register_learn(mcp)
    # ...
```

## Migration

### Mapping from current tools

| Current | New | Notes |
|---------|-----|-------|
| context_store(layer=memory) | remember | |
| context_store(layer=knowledge) | learn | |
| context_store(layer=wisdom) | believe | |
| context_store(layer=intelligence) | reason | reasoning profile |
| context_store(layer=meta) | reflect | reasoning profile |
| context_store(layer=belief) | hypothesize | reasoning profile |
| context_recall | recall | |
| context_link | link | |
| context_admin(action=provenance) | trace | |
| context_update_belief | revise | reasoning profile |
| context_crystallize | commit | reasoning profile |
| context_admin | (internal only) | |
| context_accept_belief | (internal only) | |
| context_reject_belief | (internal only) | |
| context_belief_state | (internal only) | |
| context_skills | context_skills | unchanged, separate concern |

### Deprecation

No deprecation period needed - still in dev. Clean cut replacement.

## Success Criteria

- [ ] External agents can use standard profile without understanding EAG layers
- [ ] Tool descriptions pass quality check (clear purpose, no smells)
- [ ] Profile switching works at silo and connection level
- [ ] Internal tools (admin, accept/reject belief) not exposed to external agents
- [ ] MCP instructions match actual tool names
- [ ] Existing tests updated for new tool names

## Open Questions

1. **context_skills** - keep as-is or rename to just `skills`?
2. **Error responses** - standardize error format across all tools?
3. **Metrics** - update telemetry for new tool names?

## References

- [MCP Tool Descriptions Are Smelly (arxiv)](https://arxiv.org/html/2602.14878v1)
- [Agentic Design Patterns Part 3: Tool Use](https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-3-tool-use/)
- [Design Patterns for LLM Agent Systems](https://onagents.org/patterns/)
- [v1.4.1 MCP QoL Plan](../plans/archive/v1.4.1-mcp-qol.md) - prior consolidation
- [05-mcp-contract.md](../../primitives/context/specs/05-mcp-contract.md) - original spec
