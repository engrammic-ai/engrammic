# 2026-04-28: v1-β phase 0 — codebase review remediation

## Summary

Spent the day landing the orphan findings from the 2026-04-28 codebase review (`context/review/codebase-review-2026-04-28.md`) — the items that didn't already have a home in another v1-β phase plan. Two PRs: **#9** (β0 review-cleanup, 26 commits) and **#10** (prompt-loader hotfix). Tests went from 134 → 179. `just check` (ruff + mypy strict) green throughout.

The review flagged 52 findings across logic/perf/errors/security/architecture/testing. We decided which were owned by other v1-β phase plans (auth → β1, batching → β2, paradigm completion → β6) and which were orphans needing this branch. The orphan set: 5 P0 + 17 P1 + 18 P2 + 12 P3 — most of them landed; the rest got absorbed into the owning plan or deferred with an explicit home.

## What landed

### PR #9 — `β0: review cleanup — 26 findings from 2026-04-28 codebase review`

26 commits structured as 8 stages:

#### Stage 1 — gating P0 unblockers (5 commits)

These four findings made the rest of the work testable. None were independent of each other in practice — the MCP surface couldn't run, indexes weren't applied, semantic search silently returned empty.

- **S-001 (`2c68e1a`)** — every MCP tool was raising `RuntimeError` on entry because `get_mcp_auth()` read a ContextVar that `MCPAuthMiddleware` never populated (middleware wasn't mounted). Routed all 13 tools at `get_mcp_auth_context()` from `mcp/server.py` instead, which returns the startup-resolved AuthContext. β1's per-request auth rewrite supersedes this; left `mcp/auth.py::get_mcp_auth` in place as the migration target with a docstring directing callers elsewhere. Tests patches updated to target the new symbol locations; new parametrized regression test asserts no tool re-introduces the broken import.

- **B1 (`0fd2552`)** — `pydantic-ai` was missing from `pyproject.toml` despite four custodian modules importing it. `import context_service.custodian` raised `ModuleNotFoundError` at runtime. Added the dep, swept stale `# type: ignore[import-not-found]` markers across custodian files, and cleaned up two newly-unused `import-untyped` markers in `vertex.py` / `vertex_gemini.py` that fell out of the dep tree expansion.

- **N-003 (`ed827ae`)** — `services/context.py::link()` interpolated the caller-supplied `relationship` string directly into the Cypher CREATE clause. The MCP tool already validated against `RelationshipType` enum, but any non-MCP caller (services, tests, future API surfaces) could inject. Now `link()` itself validates the enum before issuing the query. Six adversarial test cases pin it.

- **R-001 (`f7cb464`)** — `db/indexes.ALL_INDEX_QUERIES` (28+ DDL statements) was defined but never called. Every `:Claim/:Fact/:Document(silo_id)` lookup was a full label scan. Added `apply_all_indexes()` mirroring the existing `bootstrap_custodian_schema` pattern (per-statement try/except since CREATE INDEX is idempotent in Memgraph), wired both into the FastAPI lifespan after the driver connects.

- **R-002 (`8bb20ea`)** — `api/app.py::configure_services()` was passing no `embedding=` argument to `ContextService`, so `_embedding` stayed `None` and every `context_query` silently returned empty. Inlined the construction (Vertex when `vertex_project_id` is set, else Jina when `jina_api_key` is set, else None with a warning log). Did not route through `core/service_factory.py::ServiceFactory` because that wrapper expected the parallel `core.settings.Settings` shape (B2 split) and was about to be deleted in NF-004 anyway.

#### Stage 2 — P1 correctness (6 commits)

- **R-004 (`86baa4c`)** — `clustering/service.py:372` unpacked `embed()` as `(vectors, _usage)` but every implementation returns `list[list[float]]`. The except in the surrounding loop swallowed the `ValueError` so the failure mode was "summaries silently never embed."

- **N-004 (`a4a4b06`)** — `graph_traversal()` built relationship filter as `"|".join(types)` and embedded the result inside `IN ['REFERENCES|SUPPORTS']`. Pipe-joined string never matched a real edge type; relationship filtering returned empty. Now passes the list as a `$rel_types` parameter.

- **N-010 (`b879d03`)** — extraction job marked `COMPLETED` even when every claim write hit an exception inside the per-triple try/except. Now: empty `kept_triples` after filtering still completes (legitimate "nothing to extract"); kept_triples non-empty + zero claim_node_ids returned = `FAILED` with `job.error` pointing at the prior warning logs.

- **N-008 (`24cb758`)** — `services/context.py::reason()` issued `CREATE (n:ReasoningChain)` with a deterministic `chain_id`. Retrying after a transient driver error produced two ReasoningChain nodes sharing the same id. Switched to `MERGE ... ON CREATE SET ... ON MATCH SET ...` so retries are idempotent.

- **N-009 (`883b686`)** — `services/context.py::store()` wrote Memgraph node, then Qdrant vector, then Redis idempotency key. Qdrant failure left the Redis key unwritten, so the next caller retry minted a fresh node uuid → duplicate Memgraph node. Reordered: idempotency key now writes immediately after the Memgraph commit, before Qdrant. Trade-off (a Qdrant failure leaves a node without a vector — invisible to semantic search but recoverable by reconciliation, vs. duplicate Memgraph nodes which aren't) is documented inline.

- **N-001/N-011 (`a6d8524`)** — `engine/queries.py::CREATE_PROMOTED_FROM_EDGE` used `CREATE (f)-[:PROMOTED_FROM]->(c)`. Retrying consensus_promotion produced parallel duplicate edges between the same nodes. `CREATE` → `MERGE`.

#### Stage 3 — MCP tool contract gaps (4 commits)

- **F-07 (`8ed2874`)** — `source_tier` (authoritative/validated/community/unknown) wasn't an MCP param, so `assert_claim` defaulted every claim to `UNKNOWN` (weight 0.4). R1 single-source promotion needs ≥0.7 raw confidence × tier weight, so the promotion path was dead code for standard agents. Added `source_tier` to the tool signature; passes through to `assert_claim` and lands in the claim's properties where `fact_promotion.py` reads it.

- **F-05 (`0bca1f5`)** — `context_get` response was missing five documented fields: `layer`, `summary`, `confidence`, `tags`, `created_at`. Pulled from `node.properties` (where `assert_claim` writes them) plus `node.created_at` (top-level field).

- **F-12 (`50ef0ca`)** — `context_get` accepted `silo_id`, validated ownership against it, then silently overwrote it with `derive_silo_id(org_id)`. Callers owning multiple silos in the same org couldn't get a node from anything other than their primary. Now: provided `silo_id` is honored after ownership validation.

- **F-06 (`9e4e834`)** — `as_of` accepted on both `context_get` and `context_query` but the storage layer ignored it. Callers got plausible-looking results that didn't reflect the requested point in time. Now returns `{"error": "as_of_not_supported"}` if non-null. Param stays in signature so callers can keep passing it once time-travel lands (tracked in `meta-memory-roadmap.md`).

#### Stage 4 — security mop-up (2 commits)

- **S-005 (`0a8996b`)** — `extraction/filter/wikidata.py::_build_sparql_ask` only escaped double-quotes when interpolating subject/object into the SPARQL ASK literal. Backslashes / newlines / tabs could break out of the string. New `_escape_sparql_literal` handles `\\`, `"`, `\n`, `\r`, `\t` per SPARQL 1.1 §19.7. Backslash-first ordering blocks the naive single-pass-escape attack.

- **S-006 (`f980eaf`)** — `/docs`, `/redoc`, `/openapi.json` always exposed and unauthenticated. Now disabled when `settings.environment == "production"`. Dev/staging keep them on.

#### Stage 5 — architecture (3 commits)

- **NF-002 (`866ea50`)** — three implementations of "claim id" (`engine/queries.py::compute_claim_id`, `models/inference.py::_compute_claim_id`, `extraction/identity.py::claim_id`). The engine version had zero callers and was a near-duplicate of the inference version (different default `label_tier` only). Deleted the engine copy. Inference version is now the single canonical implementation. The extraction version uses a different algorithm (sha-256, ":"-delimited, str inputs) for a different domain — left in place.

- **NF-004 (`87f26e4`)** — `core/service_factory.py::ServiceFactory` defined but never instantiated; R-002 inlined the only would-be caller. Deleted (220 lines), removed the re-export from `core/__init__.py`. The 8 commented-out factory-method stubs (B5) went with it.

- **N-012 (`2be7078`)** — `MemgraphClient.transaction()` is a context manager; once the body has run, retry is impossible without re-running user code. The four current callers (clustering, custodian/{write_path,promotion,consensus_promotion}) each handled deadlocks by raising upward. Added `run_in_transaction(callback)` which takes an async callable and retries on transient errors (`ServiceUnavailable` + the documented Memgraph/neo4j transient codes) with exponential backoff up to 3 attempts. Logical errors (constraint violations, syntax) are not retried. Existing `transaction()` left in place for callers needing explicit control; its docstring now points at the new helper.

#### Stage 6 — docs (1 commit)

- **F-01..F-04 (`95960ef`)** — `context/api-examples.md` was written against an earlier tool surface. References to `context_store`, `context_lookup`, `context_store_chain` (none exist). Param names like `from_node_id` / `top_k` disagreed with actual signatures. `silo_create` example listed `org_id` and `config` which aren't real params. Perf-targets table referenced retired tool names. Sonnet subagent did the rewrite (pure Read+Edit, no Bash needed — see memory note about subagent permission walls in this env). 471 lines added / 97 removed. Now covers all 13 tools with verified params and response shapes; integration patterns rewritten to use the actual write verbs.

#### Stage 7 — cross-link to other phase plans (2 commits)

The auth findings beyond S-001 (S-002, S-003, S-004, S-007, S-008) belong with β1's per-request auth rewrite. The batching findings (R-003, R-005, R-006, R-007) belong with β2's Dagster asset migrations since the asset rewrites supersede those code paths. Appended "Findings to absorb" sections to `v1b-auth-finish.md` and `v1b-dagster.md` so the deferred items don't fall through.

#### Stage 8 — P3 polish sweep (1 commit)

`dcba03a` bundles five low-priority cleanups:
- N-005: clamp confidence to [0, 1] in `supersession_parser.py` so noisy_or doesn't see NaN.
- N-006: documented the single-event-loop assumption for the module-level `asyncio.Lock` in `circuit_breaker.py`.
- N-007: dropped redundant `TimeoutError` from `except (TimeoutError, Exception)` — TimeoutError is a subclass.
- S-009: default `host` flipped from `0.0.0.0` to `127.0.0.1`. Container deployments override via `HOST` env var. **Heads-up: this is the riskiest change in the branch — if any deployment relies on the default, it'll regress.**
- NF-007: hoisted runtime imports in `context_get.py` and `context_provenance.py` to module level. Test patches updated to target tool-module symbols.

### PR #9 also added two new plan files

- `v1b-review-cleanup.md` — the plan that drove this branch.
- `v1b-architecture-cleanup.md` — captures the deferred work: NF-003/006/009 (storage protocol bypass, ~19 inline Cypher strings in `services/context.py`, 19 custodian files importing `MemgraphClient` directly) and B2 (dual `Settings` classes). Two parallel workstreams under β6+; recommended sequencing is B first (smaller, removes a sharp edge), then A (sets up unit testability for v1.0).

### PR #10 — `fix(custodian): repo-root-aware prompt loader`

A latent crash that the review didn't catch. Surfaced when I tried to verify B1's done criterion (`uv run python -c "import context_service.custodian"`) inside the worktree.

Three custodian modules each computed `config/prompts/custodian/` by counting `.parent` steps from `__file__`. `agents.py` walked **5** ups; `supersession_parser.py` and `silo_synthesis.py`, in the **same directory**, walked **4**. So `agents.py` looked for prompts at `<repo-parent>/config/...` which doesn't exist anywhere. The bug was masked in CI because no test imports `custodian.agents` directly — β2b running the Dagster custodian asset would have surfaced it in prod.

Initial proposal was a one-character fix (5 → 4). Pushed back on by user twice — once on the half-measure of just helper-extracting the path walk, once on the name-based loader hardcoding `prompts/custodian/`. Final shape:

- New `config/paths.py`: finds repo root by walking up to `pyproject.toml`. Depth-independent and worktree-safe.
- `prompt_loader.load_prompt(rel_path)` now takes a path **relative to `config/`**, e.g. `load_prompt("prompts/custodian/fast_pass.yaml")`. Lens fragments still resolve relative to the prompt's own directory.
- All three callers drop their `_PROMPTS_DIR` blocks. Zero `.parent` math anywhere outside `paths.py`.
- Parametrized regression test loads every prompt the production code references. Original bug would have failed it instantly.

The relative-path API matches how the directory is actually organized (`prompts/<consumer>/<name>.yaml`) and stays forward-compatible with future consumer subdirs.

## Counts

- **2 PRs**, 27 commits total (26 + 1 hotfix).
- **Tests: 134 → 179** (+45 new unit tests across S-001 routing, link enum validation, index DDL, graph filter, SPARQL escape, prod-docs disable, transaction retry, repo paths).
- **Linecount:** ~+2700 / -500 net. Of which `api-examples.md` rewrite is +471/-97 and `v1b-architecture-cleanup.md` is +160 — actual code delta is much smaller.
- **`just check` (ruff + mypy strict) green throughout** — every commit, no `# type: ignore` adds beyond cleanup of stale ones.

## What's next

### Sequencing for v1-β

The β-phase plans have absorbed the deferred review findings, so the queue is now self-contained:

1. **β1 — auth-finish.** Per-request MCP auth, silo ownership enforcement, WorkOS SDK verify. Now also responsible for S-002/3/4/7/8 from the review (cross-linked).
2. **β2 — Dagster asset migration** (sub-phased a/b/c). Extraction → embedding+custodian → clustering+scheduling. Now also responsible for R-003/5/6/7 batching.
3. **β3** — SPLADE sparse retrieval.
4. **β4** — silo portability.
5. **β5** — integration test pack.
6. **β6** — paradigm completion (`v1b-eag-completion.md`) + architecture cleanup (`v1b-architecture-cleanup.md`) as a parallel workstream.

The architecture cleanup (storage protocol adoption + Settings consolidation) is independent of β1-β5 and can run alongside any of them when there's bandwidth.

### Worth keeping in mind

- **S-009 host default change.** If any deployment relies on `HOST=0.0.0.0` as the default, β1 or β5 will need to set the env var explicitly. The risk note is in PR #9's self-review comment.
- **N-009 idempotency reorder** introduced a "node without vector" failure mode that is strictly less bad than duplicate Memgraph nodes but should eventually have a reconciliation worker. Not captured anywhere yet — worth adding to `v1b-architecture-cleanup.md` or β6 if it doesn't naturally come out of the protocol migration.
- **`api-examples.md` REST section** was deliberately not verified by the doc-rewrite subagent. The MCP section is accurate; the `/api/v1/...` block may still be stale.
- **Worktree quirk:** the editable `primitives` path source in `pyproject.toml` resolves to `../primitives` relative to the worktree dir, not the actual repo, so a worktree at `.claude/worktrees/<name>/` needs a `../primitives → /real/path/primitives` symlink for `uv sync` to work. The `agents.py` 5-ups bug was masking itself behind the same kind of issue; this one is a real environmental quirk that future worktree-based work will hit.

### Backlog items not blocking anything

- B3: WorkOS-against-real-tenant verification — owned by β1.
- F-10: `detect_contradiction` wiring — already deferred to `meta-memory-roadmap.md`.
- The reconciliation-worker concern from N-009 (not yet logged anywhere).
