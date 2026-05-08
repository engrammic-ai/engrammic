# Q/A Framework for Agent-Based E2E Testing

## Overview

A framework for live E2E testing of Engrammic using teams of Claude Code agents. Supports validation, exploratory, dogfooding, and stress testing modes through configurable scenarios.

## Directory Structure

```
context/qa/
  README.md              # Framework overview, how to run
  roles/
    coordinator.md       # Spawns workers, monitors, triggers review
    worker.md            # Base instructions for scenario workers
    reviewer.md          # Validates results against spec + invariants
  scenarios/
    _template.md         # Scenario template
  invariants.md          # Universal checks applied to all scenarios
  results/
    YYYY-MM-DD-NNN-result.md
```

## Scenario Spec Format

```markdown
# Scenario: <Name>

## Metadata
- ID: NNN
- Agents: <count>
- Duration: <estimate>
- Silo: <silo-id>

## Setup
What needs to exist before workers start (seed data, silo state).

## Instructions
What each worker agent should do. Can be shared or per-agent.

## Success Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Notes
Optional context for the reviewer.
```

## Role Behaviors

### Coordinator

1. Reads scenario spec from `scenarios/`
2. Creates or resets test silo via `context_admin`
3. Spawns N worker agents (Claude Code teammates) with:
   - Scenario instructions
   - Silo ID
   - Worker role instructions from `roles/worker.md`
4. Waits for all workers to report completion
5. Spawns reviewer agent with scenario ID
6. Writes result file to `results/`

### Worker

1. Receives scenario instructions + silo ID from coordinator
2. Reads base instructions from `roles/worker.md`
3. Uses MCP tools (`context_store`, `context_recall`, `context_link`, etc.) against live Engrammic
4. Reports completion summary back to coordinator

### Reviewer

1. Reads scenario spec (especially Success Criteria section)
2. Reads `invariants.md` for universal checks
3. Queries Engrammic state via `context_recall`, `context_admin`, `context_belief_state`
4. Checks each criterion and invariant
5. Returns structured pass/fail with evidence

## Invariants (Universal Checks)

Applied to every scenario:

- Silo isolation: no cross-silo data leakage
- Provenance chains valid: all nodes traceable to source
- No errors: no error responses from MCP tools
- No orphan nodes: all nodes reachable via edges or queries

## Result Format

```markdown
# Result: NNN-<scenario-name>

**Date:** YYYY-MM-DD
**Status:** PASS | FAIL | PARTIAL

## Summary
One-line outcome.

## Criteria Results
- [x] Criterion 1
- [ ] Criterion 2 — FAILED: <reason>

## Invariants
- [x] Silo isolation
- [x] Provenance chains valid
- [x] No errors
- [x] No orphan nodes

## Evidence
Relevant queries, node IDs, or excerpts supporting the results.

## Notes
Reviewer observations, edge cases found, recommendations.
```

## Extensibility

### Agent Types

Currently: Claude Code teammates (via Agent tool)

Future:
- Standalone MCP clients (external processes)
- Simulated agents (Python test harnesses)
- Mixed teams

The coordinator abstracts agent spawning; scenarios specify agent count and type.

### Testing Modes

The same framework supports:

- **Validation**: Scripted scenarios with strict pass/fail criteria
- **Exploratory**: Open-ended instructions, reviewer looks for anomalies
- **Dogfooding**: Real workflow scenarios used routinely
- **Stress**: High agent count, concurrent operations, performance criteria

Mode is implicit in scenario design, not a separate config.

## Usage

```
/qa run <scenario-id>
```

Or manually:
1. Read scenario from `context/qa/scenarios/NNN-*.md`
2. Follow coordinator role instructions
3. Result written to `context/qa/results/`
