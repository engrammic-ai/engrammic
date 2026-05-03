# Context Skills

Skills for working with delta-prime context-service. These are prompt templates that compose the 3 core MCP tools: `context_store`, `context_recall`, `context_link`.

## Prerequisites

Connect to context-service MCP server. Skills assume the tools are available.

---

## Core Skills

### observe

**Triggers:** "remember this", "note that", "I noticed", "storing observation"

Store an observation to memory. Memories decay over time.

```
context_store(
  content: "{observation}",
  layer: "memory",
  tags: [{relevant_tags}]
)
```

Example:
```
User mentioned they prefer Python over JavaScript.
-> context_store(content="User prefers Python over JavaScript", layer="memory", tags=["preferences", "languages"])
```

---

### learn

**Triggers:** "I learned", "this means", "the fact is", "storing fact"

Store a fact with evidence. Facts enter the knowledge layer and may be promoted by the custodian.

```
context_store(
  content: "{claim}",
  layer: "knowledge",
  evidence: ["{source_node_ids}"]
)
```

Evidence should be node IDs from prior observations or external references.

Example:
```
From the config file, the project uses FastAPI.
-> context_store(content="Project uses FastAPI framework", layer="knowledge", evidence=["node:abc123"])
```

---

### recall

**Triggers:** "what do I know about", "search memory", "find in context", "retrieve"

Search and retrieve from epistemic memory.

```
# Semantic search
context_recall(query: "{question}", top_k: 10)

# Fetch specific nodes
context_recall(mode: "fetch", node_ids: ["{ids}"])

# Graph exploration
context_recall(query: "{topic}", depth: 2)

# Filter by layer
context_recall(query: "{topic}", layers: ["knowledge", "wisdom"])
```

Example:
```
What do I know about the user's tech stack?
-> context_recall(query="user tech stack preferences", top_k=10)
```

---

### trace

**Triggers:** "why do I believe", "where did this come from", "trace provenance", "show reasoning chain"

Understand how a belief was formed by tracing its provenance.

```
# 1. Find the belief
result = context_recall(query: "{belief}", layers: ["wisdom", "knowledge"])

# 2. Get provenance chain
context_recall(mode: "provenance", node_ids: ["{belief_node_id}"])
```

The provenance chain shows:
- Original source (Memory layer)
- Extracted claims (Knowledge layer)
- Synthesized beliefs (Wisdom layer)
- Reasoning chains (Intelligence layer)

---

### reflect

**Triggers:** "I notice a pattern", "this contradicts", "my confidence changed", "storing reflection"

Store a meta-cognitive observation about your own reasoning or beliefs.

```
context_store(
  content: "{observation}",
  layer: "meta",
  about: ["{relevant_node_ids}"]
)
```

Reflection types:
- `belief_change` - a belief was updated
- `contradiction` - conflicting information found
- `uncertainty` - high uncertainty noticed
- `insight` - new understanding formed

Example:
```
I noticed my belief about the deployment strategy changed after reading the new docs.
-> context_store(
     content="Belief about deployment changed after reading updated docs",
     layer="meta",
     about=["node:old_belief", "node:new_belief", "node:doc_source"]
   )
```

---

### reason

**Triggers:** "let me think through", "reasoning about", "analyzing step by step", "structured thinking"

Store a multi-step reasoning chain with an audit trail.

```
# 1. Gather evidence
context_recall(query: "{topic}", top_k: 10)

# 2. Store reasoning chain
context_store(
  content: "{conclusion}",
  layer: "intelligence",
  steps: [
    {"step": "Observation", "reasoning": "...", "confidence": 0.9},
    {"step": "Inference", "reasoning": "...", "confidence": 0.8},
    {"step": "Conclusion", "reasoning": "...", "confidence": 0.85}
  ],
  evidence: ["{source_node_ids}"]
)
```

Each step should have:
- `step`: Name/label for this step
- `reasoning`: The actual reasoning
- `confidence`: 0.0-1.0 confidence in this step

---

## Workflow-Adjacent Skills

These skills touch workflow concerns. For complex multi-step workflows, use gsd or superpowers skills if available.

### research

**Triggers:** "research this topic", "deep dive on", "gather information about"

Research a topic using existing knowledge.

```
# 1. Search existing knowledge
results = context_recall(query: "{topic}", top_k: 20)

# 2. Analyze for:
#    - Direct answers
#    - Related facts
#    - Confidence levels
#    - Gaps in knowledge

# 3. Optionally synthesize into a belief
context_store(
  content: "{synthesis}",
  layer: "wisdom",
  about: ["{source_node_ids}"]
)
```

For complex research requiring external sources or multi-step analysis, use gsd or superpowers skills.

---

### fact_check

**Triggers:** "is this true", "verify this", "fact check", "check against knowledge"

Verify a claim against stored knowledge.

```
# 1. Search for related knowledge
context_recall(query: "{claim}", layers: ["knowledge", "wisdom"])

# 2. Assess:
#    - Supporting evidence
#    - Contradicting evidence
#    - Confidence levels

# 3. If contradiction found, link it
context_link(
  from_id: "{claim_id}",
  to_id: "{contradicting_id}",
  rel: "contradicts"
)

# 4. Optionally reflect on discrepancy
context_store(content: "Found contradiction...", layer: "meta", about: [...])
```

For verification requiring external sources, use gsd or superpowers skills.

---

### connect

**Triggers:** "how does X relate to Y", "connect these concepts", "link these nodes", "find relationship"

Find and create relationships between concepts.

```
# 1. Recall both concepts
a = context_recall(query: "{concept_a}")
b = context_recall(query: "{concept_b}")

# 2. Determine relationship type:
#    - supports: A provides evidence for B
#    - contradicts: A conflicts with B
#    - derives: A is derived from B
#    - supersedes: A replaces B
#    - references: A mentions B

# 3. Create the link
context_link(
  from_id: "{a_node_id}",
  to_id: "{b_node_id}",
  rel: "{relationship}"
)
```

For complex relationship analysis, use gsd or superpowers skills.

---

## Quick Reference

| Skill | Layer | Required params |
|-------|-------|-----------------|
| observe | memory | content |
| learn | knowledge | content, evidence |
| recall | (read) | query or node_ids |
| trace | (read) | node_id for provenance |
| reflect | meta | content, about |
| reason | intelligence | content, steps |
| research | wisdom | content, about |
| fact_check | (read + link) | query |
| connect | (link) | from_id, to_id, rel |

## MCP Tools Reference

These skills use 3 core MCP tools:

**context_store(content, layer, evidence?, about?, steps?, tags?, session?)**
- Stores content to epistemic memory
- `layer`: memory | knowledge | wisdom | intelligence | meta

**context_recall(query?, mode?, node_ids?, depth?, layers?, top_k?, as_of?)**
- Retrieves from epistemic memory
- `mode`: search | fetch | graph | history | provenance

**context_link(from_id, to_id, rel, weight?, note?)**
- Creates relationship between nodes
- `rel`: supports | contradicts | derives | supersedes | references
