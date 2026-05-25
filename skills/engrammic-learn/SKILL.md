---
name: engrammic:learn
description: Store fact with evidence to knowledge layer. Use for "assert that", "we know that".
allowed-tools:
  - mcp__engrammic__learn
---

# Learn

Store a verifiable claim with supporting evidence to the knowledge layer. Facts stored here may be promoted to Beliefs by sage.synthesizer when corroborated across multiple sources.

## When to use

- "We know that..." / "assert that..." / "it has been confirmed that..."
- You have a claim you can back with a source, node ID, or URI
- Moving from an observation (memory) to a grounded fact (knowledge)
- Recording output from a tool call, document, or external reference

**Heuristic:** If you would need to cite a source to defend this claim, it belongs here with that source as evidence. If you cannot cite a source, use `observe` instead.

## Tool call

```
learn(
  claim: "{claim}",
  evidence: ["{source_node_ids_or_uris}"],
  source: "agent",  # or: document|user|external
  confidence: 0.9,  # optional
  tags: ["{domain}", "{type}", "{specific}"],
  source_tier: "validated"  # optional: authoritative|validated|community
)
```

Always provide evidence refs (node IDs or URIs). Always tag with 2-5 relevant tags.

**source_tier hint:** When you know the quality of your source, hint it for better confidence scoring:
- `authoritative` - official sources (.gov, .edu, court records, SEC filings)
- `validated` - curated professional data (PitchBook, Bloomberg, arXiv)
- `community` - user-generated (LinkedIn, Medium, Wikipedia)

If omitted, the system auto-classifies based on evidence URIs.

## What comes next

After storing a fact, you might:
- `connect` - link this fact to related nodes (`SUPPORTS`, `CONTRADICTS`, `DERIVED_FROM`)
- `reason` - use this fact as a step in a multi-step reasoning chain
- `reflect` - if this fact changes or contradicts something you previously believed

## Example workflow

1. `remember(...)` - capture initial raw finding to memory
2. `learn(claim: "Qdrant vector search latency averages 180ms at depth 2", evidence: ["bench://2026-05-15/qdrant-depth2"])` - assert the fact with evidence
3. `connect(from_node: "{learn_node_id}", to_node: "{design_decision_node_id}", relationship: "SUPPORTS")` - link to the architecture decision it informs
