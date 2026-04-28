# Plan: Architecture Cleanup — Protocol Adoption + Settings Consolidation

**Status:** Draft 2026-04-28
**Branch:** `phase-eag-arch-cleanup` (when work starts)
**Workstream:** v1-β phase 6+ (parallel to `v1b-eag-completion.md`; opportunistic)

## Goal

Migrate the two largest remaining architecture-debt items from the 2026-04-28 review:

1. **NF-003 / NF-006 / NF-009 — protocol bypass.** `services/context.py` (1100+ lines, ~19 inline Cypher strings) and the entire `custodian/` subsystem (19 files) take a raw `MemgraphClient` directly instead of depending on `engine/protocols.py`. This violates CLAUDE.md rule 8 and makes the storage layer untestable without a live database.
2. **B2 — dual `Settings` classes.** `config/settings.py` (used by FastAPI / runtime) and `core/settings.py` (used by some library code) have overlapping fields with diverging names (`vertex_project_id` vs `vertex_project`, `embedding_provider` only on one, etc.). The R-002 fix in β0 had to inline embedding-service construction precisely because of this split. Pick one canonical, migrate callers.

These were called out as P1 architecture findings during the review and explicitly deferred from β0 (`v1b-review-cleanup.md`) because the touch surface is too large for a remediation branch.

## Why

- **Protocol adoption** is the only way the storage layer becomes test-isolatable. Today, every test that exercises `services/context.py` either hits a live Memgraph (integration tests) or mocks `MemgraphClient` ad-hoc. With a clean `Storage` protocol, the same tests can run against an in-memory implementation, drastically widening unit coverage.
- **Settings consolidation** removes a class of bugs where production reads from one Settings shape and a library path reads from the other. We hit this in β0/R-002 and worked around it; the workaround is technical debt that grows with every new settings field.

Both items also unblock the protocol-based migrations that β2 (Dagster) will want — Dagster ops should depend on the storage protocol, not on a concrete client.

## Current state (anchored from audit on 2026-04-28)

### Inline Cypher / direct client usage in `services/context.py`

`rg '^\s+("""\)?\s*(MATCH|CREATE|MERGE)' src/context_service/services/context.py | wc -l` returns ~19 inline query bodies. Methods that hold inline Cypher today:

- `store()` — CREATE_NODE variant + idempotency key write
- `get()` — MATCH-by-id with cache layer
- `lookup()` — semantic + keyword path with Qdrant integration
- `query()` — same, plus filters
- `link()` — CREATE relationship (now enum-validated post N-003)
- `graph_traversal()` — UNWIND seeds + variable-length match
- `reason()` — MERGE ReasoningChain (post N-008)
- `assert_claim()` — store + DERIVED_FROM edge writes
- `commit_belief()`, `reflect()`, `provenance()`, `history()`, plus the ScopeContext helpers

### Custodian subsystem direct imports

```
$ rg "from context_service.stores.memgraph import MemgraphClient" src/context_service/custodian/ -l | wc -l
~19
```

Every file in `custodian/` (visit, dispatch, validators, business_rules, write_path, promotion, consensus_promotion, supersession, agents, tools, etc.) imports `MemgraphClient` directly. Many call `client.execute_write` or `client.transaction()` inline.

### Dual Settings shape

```
src/context_service/config/settings.py   — pydantic-settings, env-loaded, used by FastAPI lifespan
src/context_service/core/settings.py     — pydantic-settings, hand-built configs, used by ServiceFactory (now deleted) + clustering/custodian library code
```

Field deltas (non-exhaustive, audit at task start):

| Field | config/settings | core/settings |
|---|---|---|
| `vertex_project_id` | str (default "") | n/a |
| `vertex_project` | n/a | str \| None |
| `embedding_provider` | n/a | str (default "jina") |
| `jina_api_key` | str (default "") | SecretStr \| None |
| `workos_api_key` | str \| None | n/a (different path) |

The two get_settings() functions return different objects.

## Tasks (priority order)

The two workstreams are independent. Pick one, finish it, ship, then start the other.

### Workstream A — Storage Protocol Adoption (NF-003 / NF-006 / NF-009)

1. **Audit `engine/protocols.py`. Confirm coverage.**
   - Read the existing protocol(s). Note every method `services/context.py` calls on `MemgraphClient` and every call from custodian. Cross-reference against the protocol's surface.
   - Output: a gap list — methods that need to be added to the protocol before migration.

2. **Add missing protocol methods.**
   - For each gap method, define on the protocol with strict type annotations. The concrete `memgraph_store.py` adapter implements them.
   - Mypy strict catches signature mismatches.

3. **Migrate `services/context.py` to depend on the protocol.**
   - Change the constructor type hint from `MemgraphClient` to the protocol type.
   - Hoist every inline Cypher string into `db/queries.py` (already partially done — extend the convention) and call via the protocol method that runs it.
   - Where the inline query is genuinely one-off (e.g. a debug helper), keep it but route through `protocol.execute_*` rather than `client.execute_*`.
   - Compile + mypy + tests must stay green at each commit; do this method-by-method, not as a single atomic refactor.

4. **Migrate `custodian/` to depend on the protocol.**
   - Same pattern: change the type hint, replace `MemgraphClient`-specific calls with protocol calls.
   - Custodian has `client.transaction()` and `client.run_in_transaction()` (post-N-012) usage. These need to be protocol methods too.
   - 19 files; expect 1-2 commits each. Group by subsystem (validators, write_path, promotion, etc.).

5. **In-memory protocol implementation for tests.**
   - Add `tests/fakes/memgraph_protocol.py` with a dict-backed implementation of the storage protocol.
   - Migrate one or two integration tests to use it; demonstrate the speed-up.
   - Encourage future tests to use this by default.

6. **Lock the boundary.**
   - Add a CI check (or a test that grep-fails) that catches direct `MemgraphClient` imports outside `engine/`, `stores/`, and `db/`. Prevents regression.

### Workstream B — Settings Consolidation (B2)

1. **Audit field overlap.**
   - Diff `config/settings.py::Settings` against `core/settings.py::Settings`. Build a complete table.
   - For each field with diverging name (`vertex_project_id` vs `vertex_project`): pick the canonical name. Bias toward the name used in production paths (`config/settings.py`).
   - For each field with diverging type (`str` vs `SecretStr`): pick `SecretStr` for any value that holds a secret.

2. **Pick the home.**
   - `config/settings.py` is preferred — it's already used by the FastAPI lifespan and the env-loading path matches deployment.
   - `core/settings.py`'s grouped sub-configs (`InfraConfig`, `RetrievalTuning`, etc.) are useful and should migrate as nested models on the canonical Settings.

3. **Mechanical migration.**
   - Rename diverging fields on `core/settings.py` to match the canonical names.
   - Update every importer of `core.settings.Settings` to import `config.settings.Settings` instead.
   - Delete `core/settings.py` once empty. Update `core/__init__.py` re-exports.

4. **Backwards-compat shim during the migration.**
   - During the renaming, expose old field names as `@property` aliases on the surviving Settings class. Mark with a `# TODO(2026-Q3): remove after callers migrate` comment.
   - Remove the aliases once `rg` shows no callers.

5. **Verification.**
   - `just check && just test` green.
   - `python -c "from context_service.config import get_settings; from context_service.core import get_settings"` — both should resolve to the same callable.

## Out of scope

- Replacing the neo4j driver itself.
- Repointing custodian agents (pydantic-ai) at the protocol — agents talk to the LLM, not the graph; their data deps stay where they are.
- Splitting `services/context.py` into multiple files. The protocol migration may surface a natural split, but that's a follow-up.
- Adding new storage backends (postgres, etc.). Protocol adoption makes this possible later but is not the goal here.

## Done criteria

### Workstream A
- `services/context.py` and every file under `custodian/` declare `protocol: Storage` (or whatever the protocol type is named) instead of `client: MemgraphClient`.
- No direct `from context_service.stores.memgraph import MemgraphClient` statements outside `engine/`, `stores/`, `db/`, and the test fakes module.
- All inline Cypher in `services/context.py` is either moved to `db/queries.py` constants or routed through a protocol method.
- An in-memory protocol fake exists and at least one integration test runs against it as a demo.
- `just check` + `just test` green.

### Workstream B
- One canonical `Settings` class, in `config/settings.py`.
- `core/settings.py` deleted (or reduced to deprecated shims that re-export from config).
- Every callsite uses the canonical names.
- `just check` + `just test` green.

## Sequencing

Workstream A is bigger but more valuable (unlocks fake-backed unit testing for the whole storage surface). Workstream B is smaller and removes a known footgun (the dual-Settings issue we worked around in β0/R-002).

If picking only one for a given β6 cycle: do **B first** (fewer files, removes a sharp edge today), then **A** (set up for v1.0).

## Cross-references

- Source review: `context/review/codebase-review-2026-04-28.md` findings NF-003, NF-006, NF-009, B2.
- β0 (where R-002 inlined embedding construction to avoid the Settings split): `context/plans/v1b-review-cleanup.md`.
- β6 paradigm-completion plan (parallel hygiene workstream): `context/plans/v1b-eag-completion.md`.
- `engine/protocols.py` — current protocol surface.
- `db/queries.py` — destination for hoisted Cypher.
