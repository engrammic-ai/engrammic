# Q/A Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the context/qa/ directory structure with role definitions, scenario template, and invariants for agent-based E2E testing.

**Architecture:** Flat markdown framework - role files instruct agents, scenarios define tests, reviewer validates against invariants.

**Tech Stack:** Markdown, Claude Code Agent tool, Engrammic MCP tools

---

### Task 1: Create Directory Structure and README

**Files:**
- Create: `context/qa/README.md`
- Create: `context/qa/roles/` (directory)
- Create: `context/qa/scenarios/` (directory)
- Create: `context/qa/results/.gitkeep`

- [ ] **Step 1: Create directories**

```bash
mkdir -p context/qa/roles context/qa/scenarios context/qa/results
touch context/qa/results/.gitkeep
```

- [ ] **Step 2: Write README.md**

```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add context/qa/
git commit -m "feat(qa): scaffold directory structure and README"
```

---

### Task 2: Create Coordinator Role

**Files:**
- Create: `context/qa/roles/coordinator.md`

- [ ] **Step 1: Write coordinator.md**

```markdown
# Coordinator Role

You orchestrate Q/A test scenarios by spawning workers, monitoring completion, and triggering review.

## Inputs

- Scenario ID (e.g., `001`)
- Scenario file at `context/qa/scenarios/NNN-*.md`

## Process

### 1. Read Scenario

Read the scenario spec. Extract:
- Metadata (agent count, silo ID, duration estimate)
- Setup requirements
- Worker instructions
- Success criteria

### 2. Setup Silo

Create or reset the test silo:

```
context_admin(action="create_silo", silo_id="<from-scenario>")
```

If silo exists and needs reset:

```
context_admin(action="delete_silo", silo_id="<from-scenario>")
context_admin(action="create_silo", silo_id="<from-scenario>")
```

### 3. Spawn Workers

For each worker (1 to N from metadata):

```python
Agent(
    description=f"QA Worker {i} for scenario {scenario_id}",
    prompt=f"""You are a Q/A test worker.

Silo ID: {silo_id}

Read your base instructions: context/qa/roles/worker.md

Your task:
{worker_instructions_from_scenario}

Report back with a summary of what you did and any issues encountered."""
)
```

Spawn all workers in parallel (single message with multiple Agent calls).

### 4. Collect Results

Wait for all workers to complete. Note any failures or anomalies.

### 5. Spawn Reviewer

```python
Agent(
    description=f"QA Reviewer for scenario {scenario_id}",
    prompt=f"""You are a Q/A test reviewer.

Scenario: {scenario_id}
Silo: {silo_id}

Read your instructions: context/qa/roles/reviewer.md
Read the scenario: context/qa/scenarios/{scenario_file}
Read invariants: context/qa/invariants.md

Validate the scenario executed correctly. Return structured pass/fail."""
)
```

### 6. Write Result

Create result file at `context/qa/results/YYYY-MM-DD-NNN-result.md` using the reviewer's output.

## Error Handling

- If worker spawn fails: note in result, continue with remaining workers
- If reviewer fails: write partial result with error noted
- If silo setup fails: abort scenario, write failure result
```

- [ ] **Step 2: Commit**

```bash
git add context/qa/roles/coordinator.md
git commit -m "feat(qa): add coordinator role"
```

---

### Task 3: Create Worker Role

**Files:**
- Create: `context/qa/roles/worker.md`

- [ ] **Step 1: Write worker.md**

```markdown
# Worker Role

You execute test actions against Engrammic as part of a Q/A scenario.

## Inputs

- Silo ID (from coordinator)
- Task instructions (from scenario spec)

## Guidelines

### Use Real MCP Tools

Interact with Engrammic via MCP tools:

- `context_store` - Write to memory/knowledge/wisdom layers
- `context_recall` - Read and search
- `context_link` - Create relationships
- `context_belief_state` - Check working hypotheses
- `context_admin` - Query provenance, history

### Stay in Your Silo

Always use the silo ID provided. Never access other silos.

### Report Clearly

When done, report back to coordinator with:

1. **Actions taken** - What you stored, linked, queried
2. **Node IDs** - Any node_ids created (for reviewer verification)
3. **Issues** - Errors, unexpected behavior, confusion about instructions

### Example Report

```
## Worker 1 Complete

Actions:
- Stored 3 observations to memory layer
- Created 2 RELATES_TO links
- Recalled successfully with semantic search

Node IDs created:
- obs_abc123
- obs_def456
- obs_ghi789

Issues: None
```

## Common Patterns

### Store and Verify

```
# Store
context_store(layer="memory", content="...", silo_id="test-001")

# Verify it exists
context_recall(mode="flat", layer="memory", limit=10, silo_id="test-001")
```

### Create Linked Nodes

```
# Store two nodes
result1 = context_store(layer="knowledge", content="Fact A", silo_id="test-001")
result2 = context_store(layer="knowledge", content="Fact B", silo_id="test-001")

# Link them
context_link(
    source_id=result1["node_id"],
    target_id=result2["node_id"],
    relation="RELATES_TO",
    silo_id="test-001"
)
```
```

- [ ] **Step 2: Commit**

```bash
git add context/qa/roles/worker.md
git commit -m "feat(qa): add worker role"
```

---

### Task 4: Create Reviewer Role

**Files:**
- Create: `context/qa/roles/reviewer.md`

- [ ] **Step 1: Write reviewer.md**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add context/qa/roles/reviewer.md
git commit -m "feat(qa): add reviewer role"
```

---

### Task 5: Create Invariants

**Files:**
- Create: `context/qa/invariants.md`

- [ ] **Step 1: Write invariants.md**

```markdown
# Q/A Invariants

Universal checks applied to every scenario. These must pass regardless of scenario-specific criteria.

## 1. Silo Isolation

**Check:** No data from other silos appears in queries.

**How to verify:**
```
context_recall(mode="flat", layer="memory", limit=100, silo_id="<test-silo>")
```

All returned nodes must have matching silo_id.

**Fail condition:** Any node with different silo_id in results.

## 2. Provenance Chains Valid

**Check:** All nodes are traceable to a source.

**How to verify:**
For a sample of nodes:
```
context_admin(action="provenance", node_id="<node>", silo_id="<test-silo>")
```

Chain should reach a terminal node (Document, Observation, or external source).

**Fail condition:** Provenance returns empty or error for any node.

## 3. No Errors

**Check:** No MCP tool calls returned errors during the scenario.

**How to verify:**
- Review worker reports for error mentions
- Query nodes and check for error states

**Fail condition:** Any error response from MCP tools (excluding expected validation errors in negative test cases).

## 4. No Orphan Nodes

**Check:** All created nodes are reachable.

**How to verify:**
```
context_recall(mode="flat", layer="<layer>", limit=100, silo_id="<test-silo>")
```

Compare node count with worker-reported created nodes.

**Fail condition:** Nodes created but not retrievable via recall.
```

- [ ] **Step 2: Commit**

```bash
git add context/qa/invariants.md
git commit -m "feat(qa): add invariants"
```

---

### Task 6: Create Scenario Template

**Files:**
- Create: `context/qa/scenarios/_template.md`

- [ ] **Step 1: Write _template.md**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add context/qa/scenarios/_template.md
git commit -m "feat(qa): add scenario template"
```

---

### Task 7: Final Verification

- [ ] **Step 1: Verify structure**

```bash
find context/qa -type f | sort
```

Expected:
```
context/qa/README.md
context/qa/invariants.md
context/qa/results/.gitkeep
context/qa/roles/coordinator.md
context/qa/roles/reviewer.md
context/qa/roles/worker.md
context/qa/scenarios/_template.md
```

- [ ] **Step 2: Verify all committed**

```bash
git status
```

Expected: clean working tree

- [ ] **Step 3: Done**

Framework ready. Create first real scenario by copying `_template.md`.
