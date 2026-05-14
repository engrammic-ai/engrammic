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
    include_hypotheses: bool = False,  # Include tentative beliefs from current session
) -> {results|nodes, hypotheses?, ...}
```

**Description:** "Retrieve knowledge. Search by query or fetch by node_id. Set depth > 0 for graph traversal from seed nodes. Use include_hypotheses to see your tentative beliefs."

**Maps to:** context_recall (with hypotheses extension)

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
    confidence: float = 0.8,
    session_id: str = None,    # Optional: defaults to MCP session from auth context
) -> {belief_id, session_id, potential_conflicts, created_at}
```

**Description:** "Form a tentative belief during reasoning. Unlike believe, hypotheses can be revised as you learn more. Use commit to finalize when confident. Session is auto-derived from MCP connection."

**Maps to:** context_store(layer="belief")

**Note:** `session_id` is auto-derived from `auth.session_id` (set during MCP connection). Agents don't need to manage sessions explicitly - the MCP connection IS the session.

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

## Design Decisions

### believe vs hypothesize

Both create belief-like nodes, but serve different purposes:

| Tool | Creates | Lifespan | Can revise? | Use when |
|------|---------|----------|-------------|----------|
| `believe` | Commitment | Permanent | No (supersede only) | You're confident in your conclusion |
| `hypothesize` | WorkingHypothesis | Session-scoped | Yes (via `revise`) | You're still reasoning, may change mind |

**Enforcement:** `believe` creates a Commitment directly - it cannot be revised, only superseded by a new belief. `hypothesize` creates a WorkingHypothesis that can be updated via `revise` and promoted via `commit`. The system enforces this - you can't call `revise` on a Commitment.

### link weight range

`link.weight` uses 0.0-10.0 range (not 0.0-1.0 like confidence). This is intentional:
- **Confidence** (0.0-1.0): probability/certainty of a belief
- **Weight** (0.0-10.0): strength/importance of a relationship

Default weight is 1.0. Higher weights (e.g., 5.0, 10.0) indicate stronger relationships for graph algorithms.

### Session lifecycle

Sessions are implicit - derived from the MCP connection's auth context. No explicit session creation needed:
- `auth.session_id` is set during MCP connection (from WorkOS token or generated)
- `hypothesize` uses this automatically
- Session ends when MCP connection closes
- Uncommitted hypotheses remain as WorkingHypotheses (can be committed in future session)

### context_skills

`context_skills` is **not included in profiles** - it's a separate utility tool that remains available regardless of profile. It serves a different purpose: discovering available skills (prompt patterns) vs. interacting with memory.

If agents need skill discovery, `context_skills` is always available. For most use cases, the intent-based tool names and MCP instructions provide sufficient guidance.

---

## Internal-Only Tools

These are NOT exposed to external agents. Used by SAGE and internal systems via direct service calls:

| Current Tool | Internal Use |
|--------------|--------------|
| context_admin | Silo management, session lifecycle |
| context_accept_belief | SAGE Custodian accepting ProposedBeliefs |
| context_reject_belief | SAGE Custodian rejecting ProposedBeliefs |
| context_belief_state | Internal session inspection (replaced by `recall(include_hypotheses=True)` for agents) |

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

## YAML-Based Tool Configuration

Tool names, descriptions, and profiles are defined in YAML for easy iteration without code changes.

### Configuration File

```yaml
# config/mcp_tools.yaml

mcp_instructions: |
  Engrammic: Epistemic memory for AI agents.
  
  Quick start:
  - remember: store observations
  - learn: record claims WITH evidence
  - believe: declare conclusions
  - recall: search your knowledge
  - trace: understand why you believe something
  - link: connect related knowledge

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

tools:
  remember:
    description: "Store an observation. Use for raw information you may need later."
    maps_to: memory
    params:
      content:
        type: str
        required: true
        description: "What to remember"
      tags:
        type: list[str]
        description: "Optional categorization"
      decay:
        type: str
        default: "standard"
        description: "ephemeral|standard|durable|permanent"

  learn:
    description: "Record something you learned with evidence. Evidence is required."
    maps_to: knowledge
    params:
      claim:
        type: str
        required: true
        description: "What you learned"
      evidence:
        type: list[str]
        required: true
        description: "node:<id> or URI - REQUIRED"
      source:
        type: str
        required: true
        description: "document|user|external|agent"
      confidence:
        type: float
        default: 0.8
        description: "0.0-1.0"
      tags:
        type: list[str]
        description: "Optional categorization"

  believe:
    description: "Declare a belief as a commitment. Use when you've synthesized knowledge into a conclusion."
    maps_to: wisdom
    params:
      belief:
        type: str
        required: true
      about:
        type: list[str]
        required: true
        description: "Node IDs this belief concerns"
      confidence:
        type: float
        default: 0.8
      reasoning:
        type: str
        description: "Why you believe this"

  recall:
    description: "Retrieve knowledge. Search by query or fetch by node_id. Use include_hypotheses to see tentative beliefs."
    maps_to: recall
    params:
      query:
        type: str
        description: "Natural language search"
      node_ids:
        type: list[str]
        description: "Specific nodes to fetch"
      depth:
        type: int
        default: 0
        description: "0=flat, 1-3=graph traversal"
      layers:
        type: list[str]
        description: "memory|knowledge|wisdom|intelligence"
      top_k:
        type: int
        default: 10
      include_hypotheses:
        type: bool
        default: false
        description: "Include tentative beliefs from current session"

  trace:
    description: "Trace the provenance of a belief back to its sources."
    maps_to: provenance
    params:
      node_id:
        type: str
        required: true
        description: "Node to trace"

  link:
    description: "Create a typed relationship between nodes."
    maps_to: link
    params:
      from_node:
        type: str
        required: true
      to_node:
        type: str
        required: true
      relationship:
        type: str
        required: true
        description: "supports|contradicts|derives|references|causes|supersedes"
      weight:
        type: float
        default: 1.0
      note:
        type: str

  # Reasoning profile tools
  reason:
    description: "Record explicit reasoning steps for complex problems."
    maps_to: intelligence
    params:
      steps:
        type: list[dict]
        required: true
        description: "List of {step, reasoning, confidence?}"
      conclusion:
        type: str
      evidence_used:
        type: list[str]

  reflect:
    description: "Record a meta-observation about your knowledge."
    maps_to: meta
    params:
      observation:
        type: str
        required: true
      type:
        type: str
        required: true
        description: "pattern|contradiction|uncertainty|drift"
      about:
        type: list[str]
        required: true
      confidence:
        type: float
        default: 0.8

  hypothesize:
    description: "Form a tentative belief during reasoning. Use commit to finalize. Session auto-derived from MCP connection."
    maps_to: belief
    params:
      hypothesis:
        type: str
        required: true
      about:
        type: list[str]
        required: true
      confidence:
        type: float
        default: 0.8
      session_id:
        type: str
        description: "Optional override. Defaults to MCP session from auth context."

  revise:
    description: "Update a tentative hypothesis when new information arrives."
    maps_to: update_belief
    params:
      belief_id:
        type: str
        required: true
      confidence:
        type: float
        required: true
      content:
        type: str
      reason:
        type: str
        required: true

  commit:
    description: "Promote tentative hypotheses to permanent commitments."
    maps_to: crystallize
    params:
      belief_ids:
        type: list[str]
        required: true
      reason:
        type: str
```

### Registry Implementation

```python
# mcp/tools/registry.py
from pathlib import Path
import yaml

def load_tool_config() -> dict:
    config_path = Path(__file__).parent.parent.parent / "config" / "mcp_tools.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)

TOOL_CONFIG = load_tool_config()

# Implementation functions (Python logic stays in code)
IMPLEMENTATIONS = {
    "remember": _remember_impl,
    "learn": _learn_impl,
    "believe": _believe_impl,
    "recall": _recall_impl,
    "trace": _trace_impl,
    "link": _link_impl,
    "reason": _reason_impl,
    "reflect": _reflect_impl,
    "hypothesize": _hypothesize_impl,
    "revise": _revise_impl,
    "commit": _commit_impl,
}

def register_tools(mcp: FastMCP, profile: str = "standard"):
    config = TOOL_CONFIG
    tool_names = config["profiles"][profile]
    
    # Set MCP instructions
    mcp.instructions = config["mcp_instructions"]
    
    for name in tool_names:
        tool_def = config["tools"][name]
        impl_fn = IMPLEMENTATIONS[name]
        
        # Register with description from YAML
        mcp.tool(
            name=name,
            description=tool_def["description"],
        )(impl_fn)
```

### Profile Selection

Profiles configurable at:
1. **Silo level** - default profile for all connections to a silo
2. **Connection level** - override via MCP connection params
3. **Environment** - `MCP_TOOL_PROFILE=reasoning`

```python
def get_profile() -> str:
    # Connection param > silo config > env > default
    return (
        get_connection_param("profile")
        or get_silo_config().tool_profile
        or os.environ.get("MCP_TOOL_PROFILE")
        or "standard"
    )
```

### Benefits

- **Iterate without code changes** - edit YAML, restart server
- **Non-developers can tune descriptions** - no Python knowledge needed
- **A/B test descriptions** - swap YAML files
- **Single source of truth** - profiles and tools in one place
- **Hot reload (dev mode)** - watch YAML for changes

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
| context_recall | recall | + include_hypotheses param |
| context_link | link | |
| context_admin(action=provenance) | trace | |
| context_update_belief | revise | reasoning profile |
| context_crystallize | commit | reasoning profile |
| context_admin | (internal only) | |
| context_accept_belief | (internal only) | |
| context_reject_belief | (internal only) | |
| context_belief_state | recall(include_hypotheses=true) | Merged into recall |
| context_skills | context_skills | unchanged, always available |

### Deprecation

No deprecation period needed - still in dev. Clean cut replacement.

## Success Criteria

- [ ] External agents can use standard profile without understanding EAG layers
- [ ] Tool descriptions pass quality check (clear purpose, no smells)
- [ ] Profile switching works at silo and connection level
- [ ] Internal tools (admin, accept/reject belief) not exposed to external agents
- [ ] MCP instructions match actual tool names
- [ ] Existing tests updated for new tool names
- [ ] Tool names and descriptions loaded from YAML config
- [ ] Profile can be changed without code deployment

## Open Questions

1. ~~**context_skills** - keep as-is or rename to just `skills`?~~ **Resolved:** Keep as `context_skills`, always available outside profiles
2. **Error responses** - standardize error format across all tools?
3. **Metrics** - update telemetry for new tool names?
4. **Hot reload** - worth implementing YAML watch in dev mode?
5. **Primitives spec** - update `05-mcp-contract.md` to reflect new tool surface?

## References

- [MCP Tool Descriptions Are Smelly (arxiv)](https://arxiv.org/html/2602.14878v1)
- [Agentic Design Patterns Part 3: Tool Use](https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-3-tool-use/)
- [Design Patterns for LLM Agent Systems](https://onagents.org/patterns/)
- [v1.4.1 MCP QoL Plan](../plans/archive/v1.4.1-mcp-qol.md) - prior consolidation
- [05-mcp-contract.md](../../primitives/context/specs/05-mcp-contract.md) - original spec
