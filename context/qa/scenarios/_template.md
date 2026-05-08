# Scenario: <Name>

## Metadata

- **ID:** NNN
- **Agents:** <count>
- **Duration:** <estimate, e.g., ~5 min>
- **Silo:** qa-test-NNN

## Setup

<!-- What needs to exist before workers start. Can be "None" for fresh silo. -->

None

## Instructions

<!-- What each worker should do. Can be shared (all workers do same thing) or per-agent. -->

### All Workers

1. Store 3 observations to memory layer with topic "test-topic"
2. Query your own stored observations
3. Create a link between two of your observations
4. Report back with node IDs

<!-- Or for per-agent instructions: -->
<!--
### Worker 1
...

### Worker 2
...
-->

## Success Criteria

<!-- Checkboxes for reviewer to validate -->

- [ ] Each worker stored at least 3 observations
- [ ] Each worker created at least 1 link
- [ ] All observations retrievable via recall
- [ ] No cross-worker data conflicts

## Notes

<!-- Optional context for reviewer, edge cases to watch for -->

This is a basic smoke test for multi-agent memory operations.
