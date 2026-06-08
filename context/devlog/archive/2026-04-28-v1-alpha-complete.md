# 2026-04-28: v1-α complete — paradigm gaps closed

## Summary

Closed the v1-α track in five PRs. The repo went from "MCP surface shipped, but the EAG paradigm has unfilled holes" to "every paradigm contract has a working implementation, and the production surface (Dagster assets, REST admin, SPLADE) can be built on solid ground in v1-β."

Test count: 116 → 131 unit (live); +6 integration tests requiring docker (assert→fact, migration script).

Linecount: 5 PRs, 12 commits, ~1500 lines net.

## What landed

### PR #2 — `feat(db): migrate BELONGS_TO → MEMBER_OF + v1-α plan set`

- Wrote four v1-α plan files under `context/plans/`. Each scoped to "close paradigm gap N", with an explicit out-of-scope list to keep them lean.
- Idempotent migration script `scripts/migrate_belongs_to.py` with `--silo-id`, `--all-silos`, `--verify` (later: `--dry-run`). Discovery uses `Cluster.silo_id DISTINCT` rather than `:Silo` nodes — source-of-truth for what the migration actually touches.
- Dropped the `[r:BELONGS_TO|MEMBER_OF]` dual-read pattern from every query that carried it. Lint guard test (`tests/test_no_belongs_to_writes.py`) prevents the regex `(MERGE|CREATE).*:BELONGS_TO` from coming back.
- Self-review caught a pre-merge bug: `--all-silos` discovery via `:Silo` nodes could miss legacy data. Switched to cluster-property discovery before merge.

### PR #3 — `feat(custodian): finish validator Phase B — split metrics`

- Single OTEL `custodian.claim_rejections` counter became three: `structural_rejections`, `citation_rejections`, `business_rejections`. Per-layer dashboards no longer have to filter on a freeform `reason` attribute.
- Old counter retained as a deprecated dual-emit alias with a `TODO(2026-Q3)` removal target. Existing dashboards keep working.
- `record_claim_rejection` and `CustodianRejectionMetrics.increment_claim_rejection` now type their reason as the union and dispatch via `isinstance` — call-sites unchanged.
- `_pre_check_edge` audit: as of 2026-04-28 every production path constructs `ProposedEdge` via Pydantic, so the schema + confidence checks are belt-and-suspenders. Documented the audit + warning against deletion.
- `validator-refactor.md` Phase A + B marked complete; Phase C (recovery monkey-patch migration) and Phase D (`ValidationPipeline` abstraction) explicitly deferred to post-v1-α with rationale.

### PR #4 — `feat(auth): toggleable WorkOS auth`

- Greenfield introduction of WorkOS auth with the toggle baked in from day one. `AUTH_ENABLED=false` (default) returns a fixed dev `AuthContext`; `=true` extracts a Bearer token and calls WorkOS.
- Boot-time guard: `Settings(environment="production", auth_enabled=False)` raises at construction. Bypass cannot ship to prod.
- WorkOS SDK imported lazily inside the verify function, so the dev path doesn't need the `auth` extra installed.
- Self-review caught a security regression: `resolve_mcp_auth` was silently returning a dev `AuthContext` on missing/invalid token under `AUTH_ENABLED=true`. That defeats the boot-time prod-guard. Both paths now raise `MCPAuthError`. Regression tests pin the fail-closed behaviour.
- Test isolation: every `Settings(...)` constructor in tests now passes `_env_file=None` so a developer's local `.env` can't bleed into validator assertions.

### PR #5 — `chore: prompts README, audit cleanup, migrate --dry-run + tests`

Bundles four small chores that had been queued:

- `config/prompts/custodian/README.md` documents the two prompt-loading mechanisms (custodian YAML + lens composition vs extraction/clustering provider presets) and why they're kept separate.
- Closed audit TODO #2 (the "23 pre-existing ruff errors" item) — `just check` is currently 0-error across 135 source files; resolved in PR #1.
- `scripts/migrate_belongs_to.py --dry-run` flag for the destructive migration. Read-only via `execute_query`.
- `tests/integration/test_migrate_belongs_to.py` exercises the script against live Memgraph: convert legacy edges, idempotency, dry-run no-mutation.

### PR #6 — `feat(eag): :Claim → :Fact promotion via primitives epistemology`

The largest PR of the track. Activated `primitives.eag.epistemology.promotion` for the first time in this codebase.

- `architecture/README.md` documents the `:Finding` (RAG-era cluster/silo synthesis) vs `:Fact` (per-claim EAG promotion) semantic split. They coexist, are not interchangeable, and `:Fact` is implemented as a multi-label set on the existing `:Claim` node so all incoming/outgoing edges (REFERENCES, SUPERSEDES, DERIVED_FROM) survive the promotion.
- `custodian/fact_promotion.py` is a pure adapter: builds `ClaimForPromotion` from Memgraph row dicts, calls `should_promote_r1` for single-source, `should_promote_r2` for multi-source corroboration. Distinct from `consensus_promotion.py` (the older `Claim:Commitment → Finding` path).
- Cypher `PROMOTE_CLAIM_TO_FACT` uses idempotent multi-label set: `WHERE NOT c:Fact SET c:Fact, c.promoted_at = datetime(), c.promotion_rule = $rule`.
- `services/context.py::promote_claim_to_fact` orchestrates the read + decide + write.
- `mcp/tools/context_assert.py` triggers promotion best-effort after a successful assert. Promotion failure does not fail the assert. Response carries `promoted_to_fact: bool`.
- `pipelines/assets/fact_promotion.py` ships a Dagster asset for batch promotion, partitioned by `silo_id`. Not scheduled in v1-α.

The single biggest contribution in PR #6 was a required underlying fix that nobody had flagged before: `services/context.py::store()` was writing `CREATE (n:Node {fixed fields})` regardless of `node_type`, and the `properties` dict was attached only to the in-memory return value — never persisted to Memgraph. Phase 5 author surfaced this when they noticed `promote_claim_to_fact` would always read empty props back. The fix:

- Validates `node_type` against `ALL_CITE_LABELS | {"MetaObservation"}` (Cypher injection guard).
- Multi-label create: `CREATE (n:Node:{node_type} { ... })`. `:Node` retained for backwards-compat.
- `SET n += $extra_props` for arbitrary metadata.
- `remember()` now maps content_type strings (`"text"` / `"utterance"` / `"event"`) to schema labels.

Self-review caught a final bug pre-merge: the auto-evidence-count query in `promote_claim_to_fact` and the Dagster asset matched only `:REFERENCES` edges, but `assert_claim` writes `:DERIVED_FROM`. Effect: omitting `evidence_count` always returned 0, so the Dagster batch path could never promote MCP-asserted claims. Fixed both queries to match `[:REFERENCES|DERIVED_FROM]`. Regression test added.

## Self-review observations

Pattern that paid off across the track: every PR got a hostile self-review before merge, not after. PRs #2, #4, and #6 each had pre-merge fixes that addressed real bugs (Silo discovery, silent auth bypass, edge-type mismatch). The auth bypass in PR #4 in particular would have been a security regression in production — boot-time prod-guard makes the bypass refuse to construct, but the *runtime* layer was silently degrading to dev identity on missing tokens. Caught by reading the resolver paths against the actual semantics rather than just trusting that the tests passed.

## What's open / deferred

- **WorkOS SDK method name** — `workos_client.verify_session` calls `authenticate_with_session_token`; needs verification against a real tenant + SDK ≥4.0. TODO in source.
- **Per-request MCP auth via FastMCP transport headers** — currently a `MCP_DEV_TOKEN` env-var stop-gap. Documented TODO.
- **Silo ownership enforcement** (`silo.org_id == auth_ctx.org_id` on every read/write) — separate plan, v1-β.
- **Dagster asset scheduling** — `claim_to_fact_promotion` is shipped but not scheduled. Wire into a `ScheduleDefinition` in v1-β.
- **`primitives.eag.epistemology.supersession` and `.confidence` integration** — separate plans, post-v1-α.
- **Validator refactor Phase C/D** (recovery monkey-patch migration, `ValidationPipeline` abstraction) — explicitly deferred.
- **Legacy `custodian.claim_rejections` counter** — TODO 2026-Q3 removal.
- **Audit `RelationshipType.CAUSES` vs `CITEEdgeType.CAUSES`** — alignment opportunity, low priority.

## Process notes

- Two-PR split via stash + branch dance worked — cleanup chores landed independently of the bigger paradigm work, even though both teammates worked off the same checkout.
- Worktree isolation flag for the cleanup teammate didn't take effect (both teammates ended up writing to the same working tree). Files happened not to overlap so no integration headache, but worth verifying in the next session whether the flag works for team-spawned agents.
- Phase-5 teammate committed mid-task despite a clear "don't commit" instruction. Caught at integration time and reset via `git reset --mixed origin/main`. Worth making the "don't commit" instruction more emphatic in future team prompts.
- Spawning teammates with the `superpowers:writing-plans` skill at plan time meant each phase started with an actually-readable plan file in `context/plans/`, not a freeform prompt. Each teammate could `cat context/plans/v1a-...md` to bootstrap their context.
