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

### Stream 3 (continued): Query Import Wiring

Wired context-service to import queries from primitives.

- `engine/queries.py`: imports silo queries from primitives (explicit re-exports)
- `clustering/queries.py`: imports cluster queries from primitives
- Extracted 11 more queries: 6 finding + 5 pass ledger

### Stream 5: MemgraphStore Inheritance

Wired `MemgraphStore` to inherit from `EAGKnowledgeStore`.

- Added protocol adapter methods: `get`, `get_batch`, `delete`
- `ingest`/`query` marked `NotImplementedError` (flow through pipelines)
- Documented gaps in class docstring

### Fixes

- Added `pydantic>=2.0` as primitives dependency (was causing mypy errors)
- Removed stale `type: ignore` comments
- Fixed explicit re-exports for mypy (`X as X` pattern)

## Commits

- **primitives** `9f96547`: feat: add protocol implementations + query extraction
- **primitives** `7655d95`: feat: add pydantic dep + finding/pass queries
- **context-service** `9343786`: feat: wire primitives epistemology + dedup BudgetStatus
- **context-service** `335a312`: feat: wire primitives queries + MemgraphStore inheritance

## Verification

- primitives: 53/53 tests pass, ruff clean, mypy clean
- context-service: ruff clean, mypy clean (pre-existing stub errors only)

## Remaining

- Wire `EAGLifecycleManager.should_promote` into custodian promotion logic
- Extract more queries with `content_union_predicate` dependency (needs refactor)
- Wire context-service imports for finding/pass queries from primitives
