# Q/A Framework

Agent-based E2E testing for Engrammic.

## Quick Start

1. Pick a scenario from `scenarios/`
2. Run as coordinator (or use `/qa run <id>` when skill exists)
3. Results written to `results/`

## Structure

- `roles/` - Agent role instructions (coordinator, worker, reviewer)
- `scenarios/` - Test scenario specs
- `invariants.md` - Universal checks applied to all scenarios
- `results/` - Test run outputs

## Running a Scenario

As coordinator:

1. Read scenario from `scenarios/NNN-*.md`
2. Create/reset test silo via `context_admin`
3. Spawn worker agents with scenario instructions
4. Wait for completion
5. Spawn reviewer agent
6. Write result to `results/`

See `roles/coordinator.md` for detailed instructions.
