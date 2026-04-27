# 2026-04-27: primitives/context-service Surface Completion

## Summary

Completed 4 parallel work streams to finish the integration surface between `primitives` (open-source) and `context-service` (proprietary).

## Changes

### Stream 1: Epistemology Wiring

Replaced hard-coded confidence logic with primitives imports.

- `validators.py`, `models.py`: 0.7 threshold replaced with configurable `min_edge_confidence` setting
- `handlers/consensus.py`: arithmetic mean replaced with `noisy_or_aggregate` from primitives

### Stream 2: Protocol Implementation

Created abstract bases in primitives for storage implementations.

- `primitives/eag/lifecycle.py`: `EAGLifecycleManager` with `should_promote` (R1/R2) and `detect_contradiction`
- `primitives/eag/store.py`: `EAGKnowledgeStore` abstract base

### Stream 3: Query Extraction

Extracted ~40 pure Cypher queries from context-service to primitives.

- `primitives/eag/queries/silo.py`: 6 silo CRUD queries
- `primitives/eag/queries/cluster.py`: 14 cluster queries + Leiden/PageRank
- `primitives/eag/queries/ddl.py`: 20 DDL statements

### Stream 4: Agent Primitives

De-duplicated infrastructure between repos.

- `BudgetStatus` now imported from primitives (deleted duplicate)
- `VisitDeps` implements `DepsProtocol` with `record_commit()` method
- Added `py.typed` marker for mypy compatibility

## Commits

- **primitives** `9f96547`: feat: add protocol implementations + query extraction
- **context-service** `9343786`: feat: wire primitives epistemology + dedup BudgetStatus

## Verification

- primitives: 53/53 tests pass, ruff clean, mypy clean
- context-service: ruff clean, mypy clean (pre-existing pydantic_ai stub errors only)

## Next

- Update context-service imports to use extracted queries from primitives
- Wire `EAGLifecycleManager` into custodian promotion logic
- Consider extracting more queries (finding CRUD, pass ledger)
