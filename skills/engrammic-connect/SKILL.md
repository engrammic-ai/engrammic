---
name: engrammic:connect
description: Link two concepts with a typed relationship. Use for "X relates to Y", "connect these".
allowed-tools:
  - mcp__engrammic__link
---

# Connect

Create a typed relationship between two nodes in the epistemic graph. Use this to make the knowledge graph navigable and to record how pieces of evidence relate to one another.

## When to use

- "X relates to Y" / "connect these" / "this supports that" / "this contradicts that"
- After storing a new fact, to link it to the nodes it supports or derives from
- After a `recall` reveals two nodes that should be explicitly related
- To mark when a newer belief supersedes an older one

## Tool call

```
link(
  from_node: "{source_node_id}",
  to_node: "{target_node_id}",
  relationship: "{type}",
  weight: 1.0,  # optional
  note: "{annotation}"  # optional
)
```

**Common relationship values:**
- `SUPPORTS` - evidence supports a claim
- `CONTRADICTS` - evidence contradicts a claim
- `DERIVED_FROM` - conclusion derived from premises
- `RELATED_TO` - general association
- `SUPERSEDES` - newer belief replaces older

## What comes next

After creating a link, you might:
- `trace` - to verify the provenance chain now looks correct
- `reflect` - if the link reveals a contradiction worth recording as meta-memory
- `recall` - to traverse the graph and see what else connects to these nodes

## Example workflow

1. `learn(claim: "Redis semaphore prevents SAGE race conditions", evidence: [...])` - store the fact
2. `connect(from_node: "{learn_node_id}", to_node: "{sage_design_node_id}", relationship: "SUPPORTS")` - link to the design node it supports
3. `trace(node_id: "{sage_design_node_id}")` - verify the provenance chain is correct
