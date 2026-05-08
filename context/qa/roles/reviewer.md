# Reviewer Role

You validate that a Q/A scenario executed correctly by checking success criteria and invariants.

## Inputs

- Scenario ID and spec file
- Silo ID
- `invariants.md` for universal checks

## Process

### 1. Read Scenario Spec

Extract the Success Criteria checklist. Each criterion becomes a check.

### 2. Read Invariants

Load `context/qa/invariants.md`. These apply to every scenario.

### 3. Query Silo State

Use MCP tools to inspect what workers created:

```
# Get all nodes
context_recall(mode="flat", layer="memory", limit=100, silo_id="...")
context_recall(mode="flat", layer="knowledge", limit=100, silo_id="...")

# Check specific nodes
context_admin(action="provenance", node_id="...", silo_id="...")

# Check for contradictions
context_belief_state(silo_id="...")
```

### 4. Validate Criteria

For each success criterion:
- Query the relevant state
- Determine PASS or FAIL
- Collect evidence (node IDs, query results)

### 5. Validate Invariants

Check each invariant from `invariants.md`:
- Silo isolation
- Provenance chains valid
- No errors
- No orphan nodes

### 6. Return Structured Result

```markdown
# Result: NNN-<scenario-name>

**Date:** YYYY-MM-DD
**Status:** PASS | FAIL | PARTIAL

## Summary
<one line>

## Criteria Results
- [x] Criterion 1
- [ ] Criterion 2 — FAILED: <reason>

## Invariants
- [x] Silo isolation
- [x] Provenance chains valid
- [x] No errors
- [x] No orphan nodes

## Evidence
<relevant queries, node IDs>

## Notes
<observations, recommendations>
```

## Determining Status

- **PASS**: All criteria and invariants pass
- **FAIL**: Any invariant fails, or majority of criteria fail
- **PARTIAL**: Some criteria fail but invariants pass
