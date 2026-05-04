# Custodian Stress Testing Design

## Overview

Benchmark harness for stress-testing the custodian subsystem against live docker stack. Validates correctness under load and establishes performance baselines.

## Harness Structure

```
benchmarks/
  custodian_stress/
    __init__.py
    harness.py          # StressHarness class - setup/teardown, timing, assertions
    scenarios/
      __init__.py
      volume.py         # many pending claims hitting consensus
      concurrency.py    # parallel sweeps
      edge_cases.py     # supersession chains, circular deps, validator failures
      recovery.py       # crash mid-sweep, enum recovery
    conftest.py         # pytest fixtures for docker stack
    runner.py           # standalone entry point (outside pytest)
```

Run via:
- `uv run pytest benchmarks/custodian_stress -v` (integration style)
- `uv run python -m benchmarks.custodian_stress.runner` (standalone with richer output)

Each scenario function: seeds graph state, runs custodian operation, asserts correctness, returns timing metrics.

## Stress Vectors

### Volume (`volume.py`)

- Seed 500+ pending claims across 10 clusters
- Run consensus sweep, assert all eligible claims promoted to Findings
- Measure: total sweep time, claims/second throughput

### Concurrency (`concurrency.py`)

- Spawn 3-5 parallel sweep tasks targeting overlapping clusters
- Assert: no duplicate Findings, no lost claims, correct PROMOTED_FROM edges
- Measure: contention overhead vs serial baseline

### Edge Cases (`edge_cases.py`)

- Supersession chains: A supersedes B supersedes C - verify only terminal claim promotes
- Circular deps: A references B references A - verify no infinite loop, graceful handling
- Validator failures: inject failing validator mid-sweep - verify partial progress preserved, clean error

### Recovery (`recovery.py`)

- Crash mid-sweep: kill sweep after N claims processed, restart, verify idempotent completion
- Enum recovery: feed malformed LLM outputs (uppercase variants), verify model_validator fixes them

## Success Criteria

### Correctness Assertions (must pass)

- All eligible claims promoted exactly once
- No orphaned PROMOTED_FROM edges
- Superseded chains resolve to terminal claim only
- Circular deps logged and skipped, no hang
- Crash recovery completes without duplicates
- Enum malformation auto-corrected

### Performance Baselines (informational, no hard fail)

| Scenario | Target |
|----------|--------|
| Volume (500 claims) | < 60s p95 |
| Concurrency overhead | < 20% vs serial |
| Individual promotion | < 300ms p95 |

## Output Format

Console:
```
PASS  volume.test_500_claims_consensus     52.3s (9.6 claims/s)
PASS  concurrency.test_parallel_sweeps     18.1s (overhead: 12%)
PASS  edge_cases.test_supersession_chain   0.8s
FAIL  recovery.test_crash_resume           AssertionError: duplicate finding F-abc
```

JSON summary for CI:
```json
{"passed": 7, "failed": 1, "total_time_s": 84.2, "metrics": {...}}
```

## Dependencies

- Live docker stack (Memgraph, Qdrant, Redis)
- Existing custodian modules: `consensus_promotion`, `supersession`, `validators`, `dispatch`
- Dagster not required (direct module calls)
