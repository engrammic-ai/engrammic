---
name: engrammic:recall
description: Search and retrieve context. Use for "what do I know about", "find", "search".
allowed-tools:
  - mcp__engrammic__recall
---

# Recall

Search or retrieve from epistemic memory. Use this before reasoning or storing new information to avoid duplicates and ground your work in existing context.

## When to use

- "What do I know about..." / "find..." / "search for..."
- Before starting a reasoning chain, to gather relevant evidence
- Before storing a new fact, to check if it already exists
- When asked to summarize what is known on a topic
- Surfacing working hypotheses from the current session

## Tool call

**Semantic search (default):**
```
recall(query: "{question}", top_k: 10)
```

**Filter by layer:**
```
recall(query: "{question}", layers: ["knowledge", "wisdom"])
```

**Include working hypotheses:**
```
recall(query: "{question}", include_hypotheses: true)
```

## What comes next

After recalling context, you might:
- `reason` - use retrieved nodes as evidence in a reasoning chain
- `learn` - if recall surfaces a gap you can now fill with a grounded claim
- `reflect` - if recall reveals a contradiction with something you believed

## Example workflow

1. `recall(query: "embedding latency performance", layers: ["knowledge", "wisdom"])` - gather existing facts on the topic
2. `reason(steps: [...], evidence_used: ["{node_ids_from_recall}"])` - reason over the retrieved nodes
3. `learn(claim: "...", evidence: ["{node_ids_from_recall}"])` - store a new fact grounded in what was retrieved
