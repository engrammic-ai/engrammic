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
