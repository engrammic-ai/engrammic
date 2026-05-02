# Plan: Review Cleanup (β0)

**Status:** Draft 2026-04-28
**Branch:** `phase-eag-c-review-cleanup`
**Workstream:** v1-β phase 0 (pre-flight before β1)
**Source:** `context/review/codebase-review-2026-04-28.md`

## Goal

Land the orphan findings from the 2026-04-28 codebase review — the ones not already owned by an existing v1-β phase plan. Get the service into a state where β1 (auth) and β2 (Dagster) can be tested end-to-end.

## Why this comes before β1 / β2

- `R-002` (embedding service not wired) means every `context_query` returns empty. β1's silo-ownership integration tests will pass for the wrong reason if semantic retrieval is silently no-op'd.
- `R-001` (indexes never applied) means every β1/β2 perf measurement is against full label scans. Baseline numbers will be meaningless.
- `B1` (`pydantic-ai` missing) means `import context_service.custodian` raises at runtime. β2b custodian asset can't even import, let alone test.
- `N-003` (Cypher injection in `link()`) is a P0 security bug small enough to fix now.

These four are the gating set. The rest of this plan is a sweep of orphan correctness/hygiene findings, ordered by leverage.

## Out of scope (owned elsewhere — do not touch in this branch)

| Finding | Owner |
|---|---|
| S-001 (auth split-brain) | **Lifted into Stage 1 of this plan** (P0, MCP surface dead without it; full per-request rewrite still owned by β1) |
| S-002, S-003, S-004 (dev-mode guard, per-request auth, timing-unsafe compare) | `v1b-auth-finish.md` (β1) — add as tasks there |
| S-007, S-008 (WorkOS SDK verify, SecretStr) | `v1b-auth-finish.md` (β1) |
| R-003 (extraction N+1) | `v1b-dagster.md` (β2a) — extraction asset rewrite supersedes |
| R-005 (consensus batching) | `v1b-dagster.md` (β2b) |
| R-006, R-007 (clustering batching) | `v1b-dagster.md` (β2c) |
| NF-003, NF-006, NF-009 (protocol bypass) | Defer to β6 hygiene; size is too large for this branch |

A separate one-line PR-style task is added below to record the auth/dagster findings in their owning plans (so we don't lose them).

## Current state (anchored from review on 2026-04-28)

- `src/context_service/api/app.py:54-58` — `configure_services()` does not pass `embedding=`. `ContextService._embedding` stays `None`.
- `src/context_service/api/app.py` lifespan — no call to `apply_all_indexes()`. `db/indexes.py::ALL_INDEX_QUERIES` exists but is dead.
- `src/context_service/db/indexes.py` — `ALL_INDEX_QUERIES` defined; needs an `apply_all_indexes(client)` async helper if not present.
- `src/context_service/services/context.py:912-919` — `link()` f-string-interpolates `relationship` with no enum check.
- `src/context_service/services/context.py:999-1002` — `graph_traversal()` builds `IN ['A|B']` instead of `IN ['A','B']`.
- `src/context_service/services/context.py:516-537` — `reason()` uses `CREATE` for ReasoningChain (N-008).
- `src/context_service/services/context.py:171-173` — idempotency cache written after Qdrant (N-009).
- `src/context_service/clustering/service.py:372` — unpacks `embed()` as `(vectors, _usage)` but client returns `list[list[float]]` (R-004).
- `src/context_service/extraction/service.py:396-397` — job marked `COMPLETED` even when all writes failed (N-010).
- `src/context_service/extraction/filter/wikidata.py:32-33` — SPARQL injection via unescaped quotes/newlines (S-005).
- `src/context_service/api/app.py:97-99` — `/docs`, `/redoc`, `/openapi.json` always exposed unauthenticated (S-006).
- `src/context_service/engine/queries.py:953-973` and `src/context_service/models/inference.py:52-72` — `compute_claim_id` duplicated with diverging signatures (NF-002).
- `src/context_service/engine/queries.py:1086-1091` — `CREATE_PROMOTED_FROM_EDGE` uses CREATE not MERGE (N-001/N-011).
- `src/context_service/stores/memgraph.py:118-133` — `transaction()` no retry on transient errors (N-012).
- `src/context_service/mcp/tools/context_get.py:30`, `context_query.py:122` — `as_of` accepted, ignored (F-06).
- `src/context_service/mcp/tools/context_get.py:51-65` — `silo_id` validated, then ignored in favor of derived silo (F-12).
- `src/context_service/mcp/tools/context_get.py:75-85` — response missing `layer`/`summary`/`confidence`/`tags`/`created_at` (F-05).
- `src/context_service/mcp/tools/context_assert.py:97-112` — `source_tier` not a tool param (F-07).
- `context/api-examples.md` — stale tool names + param names (F-01..F-04).
- `pyproject.toml` — `pydantic-ai` missing from `[project.dependencies]` (B1).
- `src/context_service/core/service_factory.py` — `ServiceFactory` defined but never instantiated (NF-004).

## Tasks (priority order, bite-sized)

### Stage 1 — gating P0 unblockers

These five are independent. Land each as its own commit; can be parallelized in separate worktrees if desired, but easier to do sequentially in one branch.

0. **S-001: stop the auth split-brain so MCP tools don't `RuntimeError` on every call.**
   - Problem: `mcp/auth.py::get_mcp_auth()` reads a ContextVar that `MCPAuthMiddleware` never populates (middleware not mounted), so all 13 MCP tools raise on entry. Meanwhile `mcp/server.py` already exposes `get_mcp_auth_context()` returning the startup-resolved context that *does* work.
   - Cheapest fix (this stage): point all tool callsites at `get_mcp_auth_context()` from `mcp/server.py`. Do NOT mount the middleware here — that's the wrong long-term path; β1 will rewrite to per-request auth.
   - Files: every `src/context_service/mcp/tools/*.py` that imports `get_mcp_auth`. Replace the import and the call. Confirm the returned shape is the same `AuthContext` callers expect; if it differs, adapt at the callsite, not in the helper.
   - Leave `mcp/auth.py::get_mcp_auth` + the ContextVar in place (β1 will rebuild around it). Add a short module docstring noting "do not import — use `mcp.server.get_mcp_auth_context()` until β1 lands per-request auth."
   - Verify: run any MCP tool end-to-end (e.g. `context_get`) under dev settings; assert no `RuntimeError`. Add a regression unit test that patches the auth dep and calls one tool.
   - Commit: `fix(mcp): route tools to startup auth context to unblock MCP surface (S-001)`.

1. **B1: add `pydantic-ai` to deps.**
   - File: `pyproject.toml`. Add `pydantic-ai` (latest compatible) under `[project.dependencies]`. Match version pin style of neighboring deps.
   - Run `just lock` then `just sync`.
   - Verify: `uv run python -c "import context_service.custodian"` exits 0.
   - Verify: `just test` — confirm previously blocked custodian tests now collect.
   - Commit: `chore(deps): add pydantic-ai for custodian agents (B1)`.

2. **N-003: validate `relationship` inside `link()`.**
   - File: `src/context_service/services/context.py:912-919`. Read the function first to get the exact arg name.
   - Find the `RelationshipType` enum (likely `engine/models.py` or `db/queries.py`). If a similar allowlist constant doesn't exist, import the enum and check `relationship in {e.value for e in RelationshipType}`; raise `ValueError` on miss.
   - Add a test in `tests/test_context_service_link.py` (new or existing) asserting `link(relationship="DROP TABLE foo")` raises `ValueError`.
   - Verify: `uv run pytest tests/test_context_service_link.py -v`.
   - Commit: `fix(security): validate link() relationship against enum to close cypher injection (N-003)`.

3. **R-001: apply indexes at startup.**
   - File: `src/context_service/db/indexes.py`. If `apply_all_indexes(client)` doesn't exist, add an `async def apply_all_indexes(client) -> None` that iterates `ALL_INDEX_QUERIES` and runs each via `client.execute_write` (or whatever the canonical write path is — match what `bootstrap_custodian_schema` does). Log at INFO; tolerate "already exists" errors per query.
   - File: `src/context_service/api/app.py` lifespan. After memgraph connection comes up and before yielding, `await apply_all_indexes(memgraph)`. Also call `await bootstrap_custodian_schema(memgraph)` if it isn't already invoked.
   - Verify: start `just dev`, watch logs for "applied N indexes". Then `EXPLAIN MATCH (c:Claim {silo_id: 'x'}) RETURN c` in Memgraph console — should show index hit, not LabelScan.
   - Commit: `fix(db): apply ALL_INDEX_QUERIES + bootstrap_custodian_schema on startup (R-001)`.

4. **R-002: wire embedding service in app.**
   - File: `src/context_service/api/app.py:54-58`. Build the embedding service. Two paths:
     - (a) Construct directly: instantiate the configured client (Jina/Vertex per `settings.embedding_provider`) and the `EmbeddingService` wrapper. Mirror the construction `ContextService` would expect.
     - (b) Use `core/service_factory.py::ServiceFactory._create_embedding_service` if present and wired. Confirm it's not dead code first (NF-004); if it is, prefer (a).
   - Pass `embedding=...` into `configure_services(...)`.
   - Verify: write or extend a smoke test that submits a document and queries it back. Or, exercise via MCP client; `context_query` should return non-empty when documents exist.
   - Commit: `fix(api): wire embedding service into ContextService at startup (R-002)`.

**Checkpoint:** at this point all 13 MCP tools should be functionally testable (modulo auth, which β1 will fix). Run `just check && just test` and confirm green.

### Stage 2 — correctness P1s (not auth, not extraction batching)

5. **R-004: fix `embed()` unpack in clustering.**
   - File: `src/context_service/clustering/service.py:372`. Change `(vectors, _usage) = embed(...)` to `vectors = embed(...)`. Confirm the embedding client return type — if some clients do return a tuple, normalize at the client wrapper instead, not here.
   - Add a unit test that exercises `_embed_summaries` (or whatever wraps line 372) with a stub client returning `list[list[float]]`. Assert no crash.
   - Verify: `uv run pytest tests/test_clustering*.py -v`.
   - Commit: `fix(clustering): unwrap embed() result correctly (R-004)`.

6. **N-004: fix `graph_traversal` relationship filter.**
   - File: `src/context_service/services/context.py:999-1002`. Replace `"|".join(types)` going into `IN [$rel_filter]` with passing the list directly: `WHERE type(r) IN $rel_types`. Update the parameter binding accordingly.
   - Add a test exercising `graph_traversal` with two relationship types; assert both kinds are returned.
   - Verify: targeted pytest.
   - Commit: `fix(graph): pass relationship filter as list, not pipe-joined string (N-004)`.

7. **N-010: don't mark extraction job COMPLETED on total write failure.**
   - File: `src/context_service/extraction/service.py:396-397`. Track per-triple write success; if all writes failed, mark `FAILED` with error count. If partial, `COMPLETED_WITH_ERRORS` (add status if not present) or keep `COMPLETED` but record the failure count in the job record.
   - Test: stub `apply_claims_to_graph` to raise; assert job status is not `COMPLETED`.
   - Commit: `fix(extraction): mark job FAILED when all claim writes fail (N-010)`.

8. **N-008: `reason()` MERGE not CREATE.**
   - File: `src/context_service/services/context.py:516-537`. Change `CREATE (rc:ReasoningChain {...})` to `MERGE (rc:ReasoningChain {chain_id: $chain_id}) ON CREATE SET rc += $props`. Requires a deterministic `chain_id` — likely already computed; verify.
   - Test: call `reason()` twice with identical input; assert single ReasoningChain node exists.
   - Commit: `fix(reason): MERGE ReasoningChain to avoid duplicates on retry (N-008)`.

9. **N-009: write idempotency cache before Qdrant.**
   - File: `src/context_service/services/context.py:171-173`. Move the Redis idempotency-cache write to before the Qdrant upsert. Trade-off: a Redis hit without a Qdrant write means a "ghost" idempotency record — but that's strictly less bad than duplicate Memgraph nodes on Redis failure. Document the trade-off in a one-line comment.
   - Test: stub Qdrant to raise after Memgraph write; retry the same call; assert no second Memgraph node.
   - Commit: `fix(store): write idempotency key before Qdrant to prevent duplicate nodes on Redis failure (N-009)`.

10. **N-001/N-011: `CREATE_PROMOTED_FROM_EDGE` MERGE not CREATE.**
    - File: `src/context_service/engine/queries.py:1086-1091`. Change `CREATE (claim)-[:PROMOTED_FROM]->(fact)` to `MERGE (claim)-[:PROMOTED_FROM]->(fact)` (or the actual relationship name — read first).
    - Test: trigger promotion twice for the same claim; assert one edge.
    - Commit: `fix(promotion): MERGE PROMOTED_FROM edge for retry safety (N-001/N-011)`.

### Stage 3 — MCP tool contract gaps

11. **F-07: expose `source_tier` as MCP param on `context_assert`.**
    - File: `src/context_service/mcp/tools/context_assert.py:97-112`. Add `source_tier: str | None = None` (or the enum type) to the tool signature. Pass through to the service. Default behavior unchanged when `None`.
    - Update tool docstring to document accepted values.
    - Test: assert with `source_tier="primary"` reaches R1 promotion path.
    - Commit: `feat(mcp): expose source_tier on context_assert to enable Claim->Fact promotion (F-07)`.

12. **F-05: include documented fields in `context_get` response.**
    - File: `src/context_service/mcp/tools/context_get.py:75-85`. Add `layer`, `summary`, `confidence`, `tags`, `created_at` to the response dict. Pull from the underlying node properties — confirm they exist on `:Claim`/`:Fact`/`:Document` schemas first.
    - Update the MCP response type / TypedDict if one exists.
    - Test: `context_get` round-trip; assert all five fields present.
    - Commit: `feat(mcp): return layer/summary/confidence/tags/created_at from context_get (F-05)`.

13. **F-12: respect explicit `silo_id` in `context_get`.**
    - File: `src/context_service/mcp/tools/context_get.py:51-65`. If caller passes `silo_id` and it differs from derived, prefer caller-supplied (after `validate_silo_ownership` — coordination point with β1; if β1 hasn't landed yet, document the TODO).
    - Test: get a node from silo A while auth'd to org with both A and B; assert correct silo used.
    - Commit: `fix(mcp): honor explicit silo_id parameter in context_get (F-12)`.

14. **F-06: implement or explicitly reject `as_of`.**
    - Files: `src/context_service/mcp/tools/context_get.py:30`, `context_query.py:122`. Decision: do we have time-travel querying yet? If not, raise `NotImplementedError` (or remove the param) instead of silently ignoring. Prefer: keep the param but raise `ValueError("as_of not yet supported")` if non-null. Track in `meta-memory-roadmap.md` that the wiring is the open piece.
    - Test: passing `as_of="2026-01-01"` raises.
    - Commit: `fix(mcp): reject as_of explicitly until time-travel is wired (F-06)`.

### Stage 4 — security mop-up (non-auth)

15. **S-005: parameterize SPARQL or escape input.**
    - File: `src/context_service/extraction/filter/wikidata.py:32-33`. Replace string interpolation with proper escaping: at minimum strip/escape `\n`, `'`, `"`, `\\`, `\r`. Better: switch to `SPARQLWrapper`'s parameter binding if available. Add a regex test with adversarial input.
    - Commit: `fix(security): escape SPARQL inputs to wikidata filter (S-005)`.

16. **S-006: gate `/docs`, `/redoc`, `/openapi.json` in prod.**
    - File: `src/context_service/api/app.py:97-99`. If `settings.environment == "production"` (or whichever flag is canonical), pass `docs_url=None, redoc_url=None, openapi_url=None` to `FastAPI(...)`. In dev/staging keep enabled.
    - Test: smoke test under prod settings asserts `/docs` returns 404.
    - Commit: `fix(security): disable OpenAPI docs in production (S-006)`.

### Stage 5 — architecture cleanup (orphan only)

17. **NF-002: deduplicate `compute_claim_id`.**
    - Files: `src/context_service/engine/queries.py:953-973` and `src/context_service/models/inference.py:52-72`. Pick one canonical location (preference: `engine/queries.py` since IDs are storage-layer concern, or move to a shared `engine/identity.py`). Delete the other; update imports. Verify the two implementations agree before deletion — diff them and reconcile if signatures differ.
    - Test: existing claim-id tests still pass.
    - Commit: `refactor: consolidate compute_claim_id to single canonical implementation (NF-002)`.

18. **NF-004: delete `ServiceFactory` if unused.**
    - File: `src/context_service/core/service_factory.py`. Confirm via grep: `rg "ServiceFactory\b" src/`. If only the definition appears, delete the file. If R-002 ended up using one of its methods (`_create_embedding_service`), promote that method to a module function and delete the rest.
    - Commit: `chore: remove dead ServiceFactory (NF-004)` or `refactor: extract embedding factory and remove dead ServiceFactory wrapper`.

19. **N-012: add transient-error retry to `transaction()`.**
    - File: `src/context_service/stores/memgraph.py:118-133`. Wrap the transaction body in a retry loop catching the neo4j-driver transient-error class (e.g. `TransientError`, `ServiceUnavailable`) with bounded backoff (3 attempts, 100ms/300ms/900ms). Do not retry on logical errors.
    - Test: stub the driver to raise `TransientError` once then succeed; assert call returns successfully.
    - Commit: `feat(memgraph): retry transactions on transient driver errors (N-012)`.

### Stage 6 — docs

20. **F-01..F-04: refresh `context/api-examples.md`.**
    - File: `context/api-examples.md`. Diff against actual MCP tool surface (`mcp/tools/*.py`):
      - Replace `context_store` / `context_lookup` / `context_store_chain` with the actual verbs (`context_remember`, `context_query`, `context_reason`, etc.) per CLAUDE.md.
      - Fix params: `from_node_id` → `from_node`, `top_k` → `max_nodes`, etc. Read each tool's signature and update.
      - Fix `silo_create` example to match actual params.
      - Update the perf-targets table to use current tool names.
    - Verify: every code example references a real tool and a real param name.
    - Commit: `docs: refresh api-examples.md to current MCP tool surface (F-01..F-04)`.

### Stage 7 — record handoff to other plans

21. **Cross-link auth findings into β1 plan.**
    - File: `context/plans/v1b-auth-finish.md`. Append a short "Findings to absorb (from review 2026-04-28)" section listing S-001, S-002, S-003, S-004, S-007, S-008 with one-line scopes. Do not duplicate the prose — link back to `context/review/codebase-review-2026-04-28.md`.
    - Commit: `docs(plans): cross-link review findings into v1b-auth-finish (β1)`.

22. **Cross-link extraction/clustering batching into β2 plan.**
    - File: `context/plans/v1b-dagster.md`. Same pattern: list R-003 (β2a), R-005 (β2b), R-006/R-007 (β2c) and R-004 (already fixed in stage 2 above, mark "absorbed").
    - Commit: `docs(plans): cross-link review findings into v1b-dagster (β2)`.

### Stage 8 — P3 polish (optional, batch as one commit)

Combine into a single sweep PR if desired:

23. **P3 polish sweep.**
    - N-005: clamp confidence to [0,1] in `custodian/supersession_parser.py:87`.
    - N-006: move `asyncio.Lock()` into a coroutine-local in `extraction/filter/circuit_breaker.py:14` (or document the single-loop assumption).
    - N-007: drop redundant `TimeoutError` clause in `extraction/filter/llm_classifier.py:85`.
    - S-009: change default bind from `0.0.0.0` to `127.0.0.1` in `config/settings.py:25`; document override for prod containers.
    - NF-007: normalize import sites in `context_get.py` / `context_provenance.py` (runtime → module-level where safe).
    - NF-008: replace f-string-built `_ALLOWED_NODE_TYPES` literal with parameterized form (`services/context.py:130-142`).
    - B4: remove or populate empty `signals/__init__.py`.
    - B5: delete commented-out factory methods in `core/service_factory.py` (subsumed by task 18 if that one fully deletes the file).
    - One commit, message: `chore: P3 review polish sweep (N-005..NF-008, B4-B5)`.

## Done criteria

- All Stage 1–7 commits land on `phase-eag-c-review-cleanup` and `just check && just test` are green.
- `pydantic-ai` resolves; `import context_service.custodian` works.
- `apply_all_indexes` runs at startup (visible in logs); `EXPLAIN` shows index hits on `silo_id` lookups.
- `context_query` against a populated silo returns non-empty results (semantic retrieval working).
- `link("DROP TABLE")` raises `ValueError` before reaching Cypher.
- `api-examples.md` matches the actual tool surface.
- β1 and β2 plans have absorbed their owned findings.
- The 5 P0s from the review are either fixed in this branch (R-001, R-002, N-003) or formally re-homed (S-001 → β1, R-003 → β2a).

## Deferred (track but don't do here)

- NF-003 / NF-006 / NF-009: full migration of `services/context.py` and `custodian/` to `engine/protocols.py`. Big enough to deserve its own plan; size-up under β6 hygiene.
- F-10: `detect_contradiction` wiring (already deferred, owned by `meta-memory-roadmap.md`).
- B2: dual `Settings` classes consolidation (`config/settings.py` vs `core/settings.py`) — defer to β6.
- B3: WorkOS-against-real-tenant verification — owned by β1.

## Verification commands cheat sheet

```bash
just check                                   # ruff + mypy
just test                                    # pytest
uv run pytest tests/path::test -v            # single test
uv run python -c "import context_service.custodian"   # B1 smoke
just dev                                     # eyeball lifespan logs for R-001/R-002
```
