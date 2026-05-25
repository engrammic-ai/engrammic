---
name: engrammic:engage
description: Resolve engagement markers. Use for "resolve marker", "handle proposed belief", "clear contradiction", "update stale commitment".
allowed-tools:
  - mcp__engrammic__recall
  - mcp__engrammic__believe
  - mcp__engrammic__commit
  - mcp__engrammic__forget
  - mcp__engrammic__patterns
  - mcp__engrammic__accept
  - mcp__engrammic__reject
  - mcp__engrammic__dismiss
  - mcp__engrammic__tick
---

# Engage

Handle engagement markers surfaced by the system. Markers appear in `recall` responses (and `tick` responses) under an `engagement` key. Two modes exist: soft (advisory) and hard (blocking).

## Engagement modes

**Soft mode (`mode: "soft"`):** Markers are pending but not blocking. Results are still returned normally. Review and resolve when convenient, but do not let them accumulate.

**Hard mode (`mode: "hard"`):** Results are withheld until you resolve at least one marker. This happens after 3 or more touches without any resolution. You must resolve at least one marker before `recall` will return results again.

When hard mode is active, `recall` returns:
```json
{
  "engagement": {
    "mode": "hard",
    "markers": [...]
  }
}
```

No result nodes are included. Resolve one marker, then re-issue `recall`.

## Checking without full recall

Call `tick` to inspect pending markers without triggering a full recall. Safe to call frequently; zero side effects.

```
tick()
```

Optionally scope to specific nodes:
```
tick(about_hint: ["{node_id_1}", "{node_id_2}"])
```

Returns `{"engagement": {"mode": "soft"|"hard", "markers": [...]}}` or `{"engagement": null}` when nothing is pending.

Call `tick` proactively if many turns have passed without a `recall`. It lets you stay aware of pending markers without incurring recall overhead.

## Marker types and resolution patterns

### ProposedBelief

SAGE synthesized a candidate belief from existing knowledge. Decide whether it is accurate.

**To ratify (you agree):**
```
accept(
  node_id: "{proposed_belief_node_id}"
)
```

**To decline (you disagree or it is premature):**
```
reject(
  node_id: "{proposed_belief_node_id}",
  reason: "Why this proposal is not correct or ready"
)
```

Do not use `dismiss` for ProposedBelief markers; the system will reject it and tell you to use `reject` instead.

### Contradiction

Two knowledge claims conflict. Determine which is correct and resolve.

**Step 1 - Recall the conflicting nodes:**
```
recall(node_ids: ["{node_a_id}", "{node_b_id}"])
```

**Step 2 - Form a corrected belief that supersedes the outdated node:**
```
believe(
  conclusion: "The corrected or synthesized claim",
  about: ["{relevant_node_ids}"],
  supersedes: "{outdated_node_id}"
)
```

**Step 3 - Dismiss the marker:**
```
dismiss(
  marker_id: "{contradiction_marker_id}",
  reason: "Resolved: {brief explanation of what was correct}"
)
```

If the contradiction is a false positive (both claims are actually compatible), skip Step 2 and go straight to `dismiss`.

### StaleCommitment

A Commitment in the wisdom layer is outdated relative to newer knowledge. Form a fresh commitment to replace it.

**Step 1 - Recall the stale commitment and related context:**
```
recall(node_ids: ["{stale_commitment_id}"])
recall(query: "{topic of the commitment}", layers: ["knowledge"])
```

**Step 2 - Commit a replacement that supersedes the stale one:**
```
believe(
  conclusion: "Updated commitment reflecting current understanding",
  about: ["{supporting_knowledge_node_ids}"],
  supersedes: "{stale_commitment_id}"
)
```

**Step 3 - Dismiss the marker:**
```
dismiss(
  marker_id: "{stale_commitment_marker_id}",
  reason: "Superseded by {new_commitment_id}"
)
```

## Decision guide

| Marker type | Right action | Wrong action |
|-------------|--------------|--------------|
| ProposedBelief - accurate | `context_accept_belief` | `dismiss` |
| ProposedBelief - inaccurate | `context_reject_belief` | `dismiss` |
| Contradiction - one side wrong | `believe(..., supersedes=...)` then `dismiss` | ignore |
| Contradiction - false positive | `dismiss` with explanation | delete either node |
| StaleCommitment | `believe(..., supersedes=...)` then `dismiss` | ignore |

## What comes next

After resolving markers, you might:
- `recall` - re-issue the original query now that blocking is cleared
- `reflect` - record what changed in your understanding
- `tick` - verify no other markers are pending before continuing
