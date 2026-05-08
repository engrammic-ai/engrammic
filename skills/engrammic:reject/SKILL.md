---
name: engrammic:reject
description: Reject a proposed belief. Use for "reject proposal", "decline belief".
allowed-tools:
  - mcp__engrammic__context_reject_belief
---

Reject a ProposedBelief from custodian synthesis.

```
context_reject_belief(
  node_id: "{proposed_belief_node_id}",
  reason: "Why this proposal is rejected"
)
```

The ProposedBelief status changes to `rejected`. Reason is stored for provenance.
