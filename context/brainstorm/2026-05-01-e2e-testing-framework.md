# Brainstorm: E2E Testing Framework for context-service

**Date:** 2026-05-01
**Mode:** Feature design

## Summary

Design a multi-use E2E testing framework for context-service that serves CI pipelines, local dev validation, and demo preparation. Must test MCP tools, Dagster pipelines, and full data lifecycle (ingest to extraction to promotion to recall).

## Use Cases and Requirements

### CI Pipeline
- Fast execution (<5 min for smoke + critical paths)
- Docker stack auto-provisioned
- Deterministic, isolated results
- Parallel unit test execution

### Local Development
- Quick feedback loop (<1 min unit, <5 min integration)
- Selective test execution (markers, single file)
- Optional live stack (skip if unavailable)
- Clear debugging output

### Demo Preparation
- Seed data setup (realistic graphs, claims, facts)
- Reproducible state (deterministic ingestion)
- Demo data markers for cleanup
- State reset between runs

## Current State

**Strengths:**
- 53+ tests with fixture patterns
- Org/silo isolation via UUIDs
- Async/await support (pytest-asyncio)
- Mocking for external dependencies
- Integration tests in `tests/integration/`

**Gaps:**
1. No E2E lifecycle scaffolding (ingest to query chains)
2. No CI workflow (.github/workflows/)
3. No demo data seeding fixtures
4. No smoke test category
5. No parallel test execution (shared Memgraph conflicts)
6. Flaky 1s socket health checks

## Test Categories

| Category | Duration | Frequency | Purpose |
|----------|----------|-----------|---------|
| **Smoke** | 1m | Every commit | Service health, tool registration |
| **Unit** | 30s | Every commit | Fast feedback, mocked deps |
| **Integration** | 3-5m | PR, nightly | Real infrastructure validation |
| **Regression** | 10m+ | Nightly | Subtle bug detection |
| **Scenario** | 5m | Demo prep, PR | Business workflow validation |

## Implementation Patterns

### MCP Tool Testing
Direct function call bypassing FastMCP transport:
```python
from context_service.mcp.tools.context_assert import _context_assert

result = await _context_assert(
    silo_id=silo_id,
    claim="OAuth tokens expire in 30 days",
    evidence="node:abc-123",
    source_type="document",
)
```

### Dagster Asset Testing
Use `materialize_to_memory()` with mocked resources:
```python
result = dg.materialize_to_memory(
    [extraction],
    resources={"memgraph": mem_res, "llm": mock_llm},
    partition_key=silo_id,
    instance=instance,
)
assert result.success
```

### E2E Scenario Builder
Fluent API for lifecycle tests:
```python
scenario = (
    E2EScenarioBuilder(memgraph_client, scope)
    .with_document("Alice owns a property in Berlin.")
    .with_claim("Alice is a property owner", evidence=["doc-1"])
)

await scenario.run_extraction(llm_res)
await scenario.run_promotion()

assert await scenario.get_facts_count() > 0
```

### Fixture Patterns
```python
@pytest.fixture
async def cleanup_silo(memgraph_client, unique_silo_id):
    yield
    await memgraph_client.execute_write(
        "MATCH (n {silo_id: $silo_id}) DETACH DELETE n",
        {"silo_id": str(unique_silo_id)},
    )
```

## Risks and Mitigations

### Risk 1: Shared State Contamination (Critical)
- Tests can't run in parallel due to shared Memgraph
- Orphaned data causes flaky failures

**Mitigation:** Per-test transactional cleanup OR per-session testcontainers

### Risk 2: Flaky Health Checks (High)
- 1s socket timeout, no backoff
- Tests silently skip when stack slow to start

**Mitigation:** Exponential backoff (1s, 2s, 4s, 8s up to 60s total)

### Risk 3: Async Event Loop Conflicts (High)
- `asyncio.run()` conflicts with pytest-asyncio auto mode

**Mitigation:** Set `asyncio_mode = "strict"`, use session-scoped event loop

## Proposed Directory Structure

```
tests/
  smoke/
    test_health.py          # Memgraph, Qdrant, Redis connectivity
    test_tool_registration.py
  unit/
    (existing test_*.py)
  integration/
    conftest.py             # Backoff health checks, cleanup fixtures
    test_lifecycle.py       # Ingest -> extract -> promote -> query
    test_extraction_pipeline.py
    ...
  scenarios/
    conftest.py             # Scenario fixtures
    test_knowledge_graph.py # Business workflow: entity graph construction
    test_provenance.py      # Citation chain validation
  fixtures/
    builders.py             # E2EScenarioBuilder
    factories.py            # Demo data factories
    mocks.py                # Shared mock resources
```

## Justfile Commands

```make
test-smoke:        uv run pytest tests/smoke -v
test-unit:         uv run pytest -m "not integration" -v
test-integration:  uv run pytest -m integration -v
test-scenarios:    uv run pytest tests/scenarios -v
test-ci:           uv run pytest tests/smoke tests/unit -v && uv run pytest -m "integration and not slow" -v
```

## Open Questions

1. **Testcontainers vs shared stack?** Testcontainers gives true isolation but adds 5-10s startup per session. Shared stack is faster but needs careful cleanup.

2. **Demo data format?** YAML fixtures, Python factories, or Cypher scripts? Factories are most flexible but verbose.

3. **Scenario granularity?** One test per business flow, or smaller composable steps?

4. **Performance baselines?** Should scenarios assert latency (e.g., query < 100ms)?

## Next Steps

1. [ ] Create `tests/fixtures/builders.py` with E2EScenarioBuilder
2. [ ] Refactor health checks with exponential backoff
3. [ ] Add `tests/smoke/` with basic health tests
4. [ ] Add `.github/workflows/test.yml`
5. [ ] Create first scenario: ingest -> extract -> promote -> query
6. [ ] Add demo data factory for partner demos
