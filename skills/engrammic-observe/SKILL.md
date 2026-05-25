---
name: engrammic:observe
description: Store observation to memory. Use for "remember this", "note that", ephemeral context.
allowed-tools:
  - mcp__engrammic__remember
---

# Observe

Store a raw observation to memory. Memories decay over time and are the starting point for deeper knowledge formation.

## When to use

- "Remember this" / "note that" / "keep track of"
- You encountered something worth recalling later (an error, a decision, a user preference)
- Capturing transient session context before it is lost
- You have an observation but no evidence yet to back a claim

**Heuristic:** If you would tell a colleague about it tomorrow, store it. If it is scratch work, use `decay: "ephemeral"`.

## Tool call

```
remember(
  content: "{observation}",
  tags: ["{domain}", "{type}", "{specific}"],
  decay: "standard"  # optional: ephemeral|standard|durable|permanent
)
```

**Tagging:** Always include 2-5 tags. At minimum: one domain tag + one specificity tag.

Tag examples: `api`, `database`, `auth`, `ui`, `infra`, `bug`, `decision`, `session`, `project`

## What comes next

After storing an observation, you might:
- `learn` - if you have a source or evidence and want to form a verifiable claim from this observation
- `connect` - to link this observation to an existing node it relates to
- `reason` - if this observation is one step in a chain you are working through

## Example workflow

1. `remember(content: "Auth endpoint returns 403 on missing tenant header", tags: ["auth", "api", "bug"])` - capture the raw finding
2. `learn(claim: "Missing X-Tenant-ID header causes 403 on /auth/token", evidence: [...])` - promote to knowledge once you have a reproduction
3. `connect(from_node: "...", to_node: "...", relationship: "SUPPORTS")` - link the observation to the relevant auth design node
