# Custodian Stress Testing Design

## Overview

Benchmark harness for stress-testing the custodian subsystem against live docker stack. Validates correctness under load and establishes performance baselines.

## Harness Structure

```
benchmarks/
  custodian_stress/
    __init__.py
    harness.py          # StressHarness class - setup/teardown, timing, assertions
    mocks.py            # Mock validators, LLM clients for controlled failure injection
    scenarios/
      __init__.py
      base.py           # ScenarioResult dataclass, shared seeding/assertion helpers
      volume.py         # many pending commitments hitting consensus
      concurrency.py    # parallel sweeps, edge dedup, cross-visit citation
      edge_cases.py     # supersession (structured + LLM), validator failures, business rules
      recovery.py       # crash mid-visit (per phase), enum recovery
      security.py       # cross-tenant citation rejection
      synthesis.py      # silo-scope synthesis path
      history.py        # FindingHistory trim, fingerprint/Jaccard drift
    conftest.py         # pytest fixtures for docker stack, silo isolation
    runner.py           # standalone entry point (outside pytest)
```

Run via:
- `uv run pytest benchmarks/custodian_stress -v` (integration style, JSON via `--json-report`)
- `uv run python -m benchmarks.custodian_stress.runner` (standalone with JSON output)

### Shared Contract

All scenarios return `ScenarioResult`:

```python
@dataclass
class ScenarioResult:
    name: str
    passed: bool
    duration_s: float
    metrics: dict[str, float]  # scenario-specific measurements
    error: str | None = None
```

Both `runner.py` and pytest consume the same scenario functions via `scenarios/base.py`.

### Fixture Isolation

Each scenario runs against a unique `silo_id` (UUID generated per test). Fixtures do not truncate shared state; silo-scoped queries ensure no cross-contamination. `conftest.py` provides:

- `fresh_silo` fixture: creates silo, yields silo_id, no teardown needed
- `seeded_memgraph` fixture: runs `indexes.py` schema setup before first scenario
- `mock_llm_client` fixture: deterministic responses for supersession LLM path

## Node Types Clarified

The custodian operates on different node types at different stages:

- **`:Claim`** - raw extracted claims from ingestion
- **`:Commitment`** - validated claims ready for consensus (output of write_path validation)
- **`:Finding`** - promoted result of consensus (has `:CITES` edges to source nodes)

`consensus_promotion.py` promotes `:Commitment` nodes, not raw `:Claim`. Volume scenarios must seed `:Commitment` nodes with proper `status='pending'`.

## Stress Vectors

### Volume (`volume.py`)

Seeds 500+ pending `:Commitment` nodes across 10 clusters. Cluster sizes intentionally uneven (one cluster with 100 nodes) to stress O(n^2) pair comparison in `detect_structured_supersession`.

**Tests:**
- `test_500_commitments_consensus`: run consensus sweep, assert all eligible commitments promoted
- `test_uneven_cluster_scaling`: verify 100-node cluster completes without timeout

**Eligibility defined as:** passed citation validation AND passed business rules (quality score >= threshold) AND not superseded.

**Measures:** total sweep time, commitments/second throughput, per-cluster breakdown.

### Concurrency (`concurrency.py`)

Spawns 3-5 parallel sweep tasks targeting overlapping clusters.

**Tests:**
- `test_no_duplicate_findings`: deterministic blake2b ID + MERGE prevents duplicates
- `test_no_duplicate_supersedes_edges`: parallel `run_supersession_pass` must not create duplicate edges for same pair
- `test_cross_visit_same_node_citation`: two visits cite the same node ID, both should succeed (per-visit `seen_node_ids` is independent)
- `test_concurrent_write_race`: two sweeps racing before first transaction commits

**Measures:** contention overhead vs serial baseline, edge dedup verification.

### Edge Cases (`edge_cases.py`)

#### Supersession

**Structured path (SPO nodes):**
- `test_supersession_chain_terminal_only`: A supersedes B supersedes C within same cluster, only terminal promotes
- `test_cross_cluster_supersession_chain`: A, B, C in different clusters - verify chain-stitching pass connects them, only terminal promotes

**LLM fallback path:**
- `test_llm_supersession_confidence_threshold`: verify confidence below threshold does not create edge
- `test_llm_supersession_malformed_output`: verify model_validator recovers uppercase/titlecase variants

**Circular dependencies:**
- `test_circular_dep_no_hang`: A references B references A - verify timeout or explicit cycle detection
- NOTE: Current code has no explicit cycle-breaking. Test documents actual behavior; if it hangs, that's a bug to fix before this test can pass.

#### Validator Failures

Injection via `mocks.py` which provides `FailingCitationValidator` that raises after N validations. Wired in via dependency injection in `write_path.py` (requires adding optional `validator_override` param).

- `test_validator_failure_partial_progress`: inject failure at validation 50 of 100, verify 49 committed, clean error logged
- `test_validator_timeout`: inject slow validator, verify timeout handling

#### Business Rules

- `test_quality_score_below_threshold`: seed low-quality findings, verify skip path fires, no `:Finding` written
- `test_all_claims_rejected_skip`: all claims in a visit fail validation, verify graceful skip (named path in `write_path.py`)

### Recovery (`recovery.py`)

Visit is a multi-phase agent loop (fast/plan/deep/stitch), not a single transaction.

**Crash injection points:**
- `test_crash_after_fast_phase`: kill after fast phase completes, restart, verify idempotent completion
- `test_crash_after_plan_phase`: kill after plan phase, restart
- `test_crash_mid_deep_phase`: kill during deep phase execution

Implementation: scenario spawns visit in subprocess, sends SIGKILL at phase boundary (detected via log marker or callback hook), restarts visit, asserts no duplicate findings via deterministic ID.

**Enum recovery:**
- `test_enum_recovery_uppercase`: feed `{"kind": "PRIMARY"}`, verify model_validator normalizes to `"primary"`
- `test_enum_recovery_titlecase`: feed `{"complexity": "High"}`, verify normalization

### Security (`security.py`)

- `test_cross_tenant_citation_rejected`: seed nodes in silo A, attempt citation from visit in silo B, verify rejection with `CROSS_TENANT_CITATION` reason
- `test_silo_boundary_finding_isolation`: findings in silo A not visible to queries in silo B

### Synthesis (`synthesis.py`)

Tests `silo_synthesis.py` path (Pro model call, `[:SUMMARIZES]->(:Silo)` edge).

- `test_silo_synthesis_creates_summary`: trigger synthesis, verify `:SUMMARIZES` edge created
- `test_silo_synthesis_coarse_finding_input`: verify correct findings fed to Pro model
- `test_silo_synthesis_idempotent`: run twice, verify no duplicate summaries

### History (`history.py`)

- `test_finding_history_trim`: update same Finding 25 times, verify `:FindingHistory` capped at `HISTORY_KEEP_COUNT=20`
- `test_fingerprint_reuse_on_stable_cluster`: cluster unchanged, verify cached finding reused via Jaccard check
- `test_fingerprint_invalidation_on_drift`: add node to cluster, verify Jaccard drift triggers recompute

## Success Criteria

### Correctness Assertions (must pass)

| Assertion | Applies To |
|-----------|------------|
| All eligible commitments promoted exactly once | volume, concurrency |
| No duplicate `:SUPERSEDES` edges for same pair | concurrency |
| No orphaned `:CITES` edges (Finding exists for each) | volume, concurrency |
| Superseded chains resolve to terminal only (same cluster) | edge_cases |
| Cross-cluster chains stitched and resolved to terminal | edge_cases |
| Circular deps timeout or skip, no hang | edge_cases |
| Partial progress preserved on validator failure | edge_cases |
| Quality gate rejects low-score findings | edge_cases |
| Crash recovery completes without duplicates | recovery |
| Enum malformation auto-corrected | recovery |
| Cross-tenant citations rejected | security |
| FindingHistory trimmed to 20 | history |
| Fingerprint reuse/invalidation correct | history |
| Silo synthesis creates `:SUMMARIZES` edge | synthesis |

### Performance Baselines

Soft fail (log warning, don't fail CI) unless regression > 2x from baseline.

| Scenario | Target | Notes |
|----------|--------|-------|
| Volume (500 commitments) | < 60s p95 | Indexes must exist |
| Uneven cluster (100 nodes) | < 30s | O(n^2) stress |
| Concurrency overhead | < 20% vs serial | |
| Individual promotion | < 300ms p95 | |
| Per-phase timing (fast/plan/deep/stitch) | logged | Informational |

## Output Format

Console:
```
PASS  volume.test_500_commitments_consensus      52.3s (9.6 commits/s)
PASS  concurrency.test_no_duplicate_findings     18.1s (overhead: 12%)
PASS  edge_cases.test_supersession_chain         0.8s
WARN  edge_cases.test_circular_dep_no_hang       2.1s (no cycle detection - documents current behavior)
FAIL  recovery.test_crash_after_fast_phase       AssertionError: duplicate finding F-abc
```

JSON summary (both pytest and standalone):
```json
{
  "passed": 14,
  "failed": 1,
  "warned": 1,
  "total_time_s": 142.7,
  "metrics": {
    "volume.commitments_per_second": 9.6,
    "concurrency.overhead_percent": 12,
    "phases": {"fast": 0.3, "plan": 1.2, "deep": 8.4, "stitch": 2.1}
  }
}
```

## Implementation Prerequisites

Before scenarios can run:

1. **Validator injection point**: Add optional `validator_override` param to `write_path.py` for test-time injection
2. **Phase boundary hooks**: Add optional callback in `visit.py` for crash injection tests
3. **STITCH_TOOLS smoke test**: Add `test_stitch_tools_valid` that calls `validate_stitch_tools()` at harness startup
4. **Metrics emission**: Verify OTel histograms emitted; add `test_metrics_emitted` scenario

## Dependencies

- Live docker stack (Memgraph, Qdrant, Redis)
- `indexes.py` must run before seeding (fixture handles this)
- Mock LLM client for deterministic supersession tests
- Real LLM client optional for smoke tests (flag: `--real-llm`)
- Existing custodian modules: `consensus_promotion`, `supersession`, `validators`, `dispatch`, `write_path`, `visit`, `silo_synthesis`, `fingerprints`

## Prerequisites (implement before harness)

1. **Circular dep cycle detection**: Add explicit cycle-breaking to `supersession.py`. Without this, `test_circular_dep_no_hang` cannot pass.
2. **Cross-cluster chain stitching**: Add a chain-stitching pass that connects supersession chains spanning multiple clusters (A→B→C where nodes are in different clusters). Without this, `test_cross_cluster_supersession_chain` would only document a limitation rather than test correct behavior.
