# Plan: Address P0/P1 findings from 2026-05-14 codebase review

## Context

The 2026-05-14 codebase review (`context/review/codebase-review-2026-05-14.md`) surfaced 5 P0s and 21 P1s. After a verification pass:

**False positives removed:**
- L-01, L-02, L-03 (SAGE consolidation) — work is complete; review flagged stale state. `pipelines/schedules.py` defines `sage_custodian_schedule` / `sage_synthesizer_schedule` / `sage_groundskeeper_schedule`; old 7 sensors deleted; `heat_diffusion` + `prewarm_sweep` wired into groundskeeper.
- P-08 (depth-2 traversal index) — single-column indexes on `id` and `silo_id` already exist (`db/indexes.py:31,72,81…`); Memgraph can use them.
- AI-05 (silent truncation in extraction) — `extraction/service.py:114-117` explicitly raises `ExtractionError` on token overflow rather than truncating.
- S-03 (CORS middleware) — MCP runs as a separate ASGI app; CORS absence on FastAPI isn't the gap claimed.

**Partial (downgrade):** AI-08 cost budgeting — infrastructure exists in `custodian/agents.py:75-83` but no per-silo enforcement at MCP / service layer. Worth a follow-up plan, not in this bundle.

**Net remaining P0s (3):** S-01, E-01, AI-01.
**P1 bundle:** N+1 sweep (4 sites), provider-level LLM timeout, claim-promotion error visibility, retry on 429/503.

This plan groups everything into a single PR so review effort amortizes across 3 quick P0s and a focused P1 sweep. Test impact is limited (no schema/API surface change); `just check` + `just test` must pass.

## Scope

### P0 fixes

**1. S-01 — Admin auth bypass via `None` default**
- **File:** `src/context_service/api/routes/admin.py:26-36`
- **Current:** `if configured_key is None: return` silently allows access.
- **Fix:** Use existing `settings.is_production` property (confirmed at `config/settings.py:699-700`):
  ```python
  if configured_key is None:
      if settings.is_production:
          raise HTTPException(503, "admin_api_key required in production")
      return
  ```
- **Why this shape:** keep dev DX (no key required for local), fail-fast in prod, no startup-side change.

**2. E-01 — Reflection rate limiter fails open on Redis exception**
- **File:** `src/context_service/engine/reflection_triggers.py:60-87`
- **Current:** `except Exception: ... return True` removes the rate limit when Redis blips.
- **Fix:** Fail closed: `return False`. Keep the warning log. Caller treats this as "skip this reflection" — acceptable degradation; cost is bounded.
- **Note:** A proper circuit breaker is the right long-term answer but adds a dependency; defer to a separate plan. Fail-closed is the right short-term posture (cost > availability for an autonomous reflection trigger).

**3. AI-01 — Unbounded content fed to embedding API**
- **File:** `src/context_service/pipelines/assets/embedding.py:120-195`
- **Current:** `texts = [str(r["content"]) for r in batch]` then `await embed_svc.embed(texts)` — no per-item size cap.
- **Fix:** Truncate each text to a configurable char cap (default `8000`) before embedding. Add `MAX_EMBED_CHARS` constant near `_BATCH_SIZE`. Log when truncation happens (info level, count only, not content).
- **Why char-based:** simple, deterministic, no tokenizer dep on the hot path. Embedding models commonly accept ~8K tokens; 8K chars is conservative and matches finding AI-04's recommendation.

### P1 bundle

**4. P-01..P-04 — N+1 sweep (4 assets, all single-template UNWIND rewrites)**

Each follows the same pattern: extract IDs, single `UNWIND $ids` query, group results client-side.

- `pipelines/assets/llm_pattern_detection.py:137-165` — `GET_FACTS_IN_CLUSTER` → batch all `cluster_ids` in one query; return `(cluster_id, facts)` rows.
- `pipelines/assets/custodian_finalize.py:74-102` — `GET_CHAINS_FOR_COMMITMENT` → batch all `commitment_ids`.
- `pipelines/assets/auto_tagging.py:156-176` — `_UPDATE_NODE_TAGS_CYPHER` → single Cypher with `UNWIND $updates AS u MATCH (n {id: u.node_id}) SET n.tags = u.tags, n.auto_tagged_at = u.now`.
- `pipelines/assets/extraction.py:130-151` — `_MARK_DOC_EXTRACTED` → batch all extracted `doc_ids` after the per-doc loop (the LLM call itself stays per-doc; only the mark-write batches).

Add new batched Cypher templates next to their existing siblings in `db/queries.py` (no new file). Naming: `BATCH_GET_FACTS_BY_CLUSTERS`, `BATCH_GET_CHAINS_BY_COMMITMENTS`, `BATCH_UPDATE_NODE_TAGS`, `BATCH_MARK_DOCS_EXTRACTED`.

**5. E-03/E-04/E-05/AI-02 — Provider-level default timeout (collapses 6 findings)**

- **Files:**
  - `src/context_service/llm/litellm_provider.py:42-101` — `_build_kwargs()` and both `acompletion` / `aembedding` call sites
  - `src/context_service/embeddings/litellm_embeddings.py:142-150` — `aembedding` call site
- **Fix:** Default `timeout=60.0` in `_build_kwargs()` when caller passes None. Single line: `kwargs.setdefault("timeout", timeout if timeout is not None else 60.0)`. Apply same default in `litellm_embeddings.py:144` as an explicit `timeout=60.0` argument.
- **Why provider-level:** the 4 disparate call-site fixes (`engine/revision.py:357,521`, `engine/summarization.py:97`, `expansion/generator.py:59`) all become non-issues once the default exists. Per-call override still works.
- **Make configurable:** add `llm_default_timeout_seconds` to `config/settings.py` (default 60.0) so ops can tune without a deploy.

**6. AI-10 — Retry on 429/503 in litellm provider**

- **File:** `src/context_service/llm/litellm_provider.py:82-90` (both `acompletion` and `aembedding`)
- **Fix:** Wrap call in tenacity (already a project dep — check `pyproject.toml`):
  ```python
  @retry(
      retry=retry_if_exception_type((litellm.RateLimitError, litellm.ServiceUnavailableError)),
      stop=stop_after_attempt(3),
      wait=wait_exponential(multiplier=1, min=1, max=10),
      reraise=True,
  )
  ```
  Decorate internal helpers; keep top-level `LiteLLMError` translation.

**7. E-02 — Claim promotion error visibility**

- **File:** `src/context_service/mcp/tools/context_store.py:290-312`
- **Current:** exception during `promote_claim_to_fact` is logged; response still shapes as success with `promoted_to_fact=False` and no error field.
- **Fix:** On exception, set `promoted_error: str(exc)` in the response payload. Keep `promoted_to_fact=False`. Don't fail the whole store (write succeeded; promotion is post-hoc).

### Items deliberately deferred (file `context/review/false-positives.md` to be seeded)

- ARCH-01..04 (protocol violations) — known design debt; sized as a layered refactor, not a single fix. Track separately.
- ARCH-08 (return type discipline) — same; refactor scope.
- AI-08 (per-silo cost budget) — needs design (where to gate, what budget unit). Separate plan.
- AI-11 (anthropic cache_control) — touches every system-prompt site; bundle into a "prompt caching pass" plan.
- E-07 (silo creation race), E-08 (`CREATE INDEX` catch-all) — true bugs, P2; can pair with infra cleanup.

## Critical files (modified by this plan)

- `src/context_service/api/routes/admin.py`
- `src/context_service/engine/reflection_triggers.py`
- `src/context_service/pipelines/assets/embedding.py`
- `src/context_service/pipelines/assets/llm_pattern_detection.py`
- `src/context_service/pipelines/assets/custodian_finalize.py`
- `src/context_service/pipelines/assets/auto_tagging.py`
- `src/context_service/pipelines/assets/extraction.py`
- `src/context_service/llm/litellm_provider.py`
- `src/context_service/embeddings/litellm_embeddings.py`
- `src/context_service/mcp/tools/context_store.py`
- `src/context_service/db/queries.py` (4 new batched templates)
- `src/context_service/config/settings.py` (new `llm_default_timeout_seconds`)

## Reused utilities / patterns

- `settings.is_production` (`config/settings.py:699-700`) — for the admin auth guard.
- `tenacity.retry` — already used elsewhere in the codebase per the project deps; reuse rather than build custom retry.
- `db/queries.py` UNWIND pattern — sibling queries like `PROMOTE_PROPOSED_BELIEF` already exist; new templates follow the same module structure.
- `MemgraphClient.execute_query` / `execute_write` parameter binding — used as-is; no driver change.

## Verification

Run sequentially; each step must pass before the next:

1. **Static checks:** `just check` (ruff + mypy strict). Must remain at 0 issues.
2. **Unit tests:** `just test`. Existing suite (~851 passing per recent memory) must stay green.
3. **N+1 regression guard:** after batching, add 1 unit test per modified asset that records the query count via a mock `MemgraphClient` and asserts `<= 2 calls per silo run`. Place under `tests/pipelines/assets/test_<asset>_batching.py`.
4. **Admin auth:** add a test that asserts a request to `/admin/silos` with `environment=production` and no `admin_api_key` raises 503 (not 200). Place under `tests/api/test_admin_auth.py`.
5. **Reflection rate-limit:** add a test that simulates a Redis exception and asserts the limiter returns `False`. `tests/engine/test_reflection_triggers.py`.
6. **Embedding truncation:** add a test that passes a >9K char string and asserts `embed_svc.embed` receives a string of length `<= MAX_EMBED_CHARS`. `tests/pipelines/assets/test_embedding_truncation.py`.
7. **Timeout default:** add a test that calls `LiteLLMProvider.complete([...])` with `timeout=None` and asserts the litellm mock saw `timeout=60.0`. `tests/llm/test_litellm_provider_timeout.py`.
8. **Integration smoke:** `just test-integration` (requires live docker stack) — run if local docker stack is up; otherwise rely on CI. Validates that the batched Cypher queries actually parse on Memgraph.
9. **Manual:** start `just dev`, hit `/admin/silos` without auth from a non-production settings file → should still return 200 (dev). Set `ENVIRONMENT=production` → 503.

## Commit shape

One commit per logical group (4 commits total), all on `feat/heat-diffusion` (since SAGE just landed there and these are clean adjacent fixes):

1. `fix(security): require admin_api_key in production; fail-closed reflection rate-limit`
2. `fix(embedding): truncate node content before embedding to MAX_EMBED_CHARS`
3. `perf(pipelines): batch N+1 queries in 4 assets via UNWIND`
4. `feat(llm): default 60s timeout + retry on 429/503 for litellm provider; surface promotion errors`

## Out of scope (explicit non-goals)

- Layered service refactor (ARCH-01..04).
- Per-silo cost budgeting (AI-08).
- Prompt caching pass (AI-11).
- Silo creation atomicity (E-07).
- Tightening `db/indexes.py` exception catch (E-08).
- Touching any sensor or schedule — SAGE is done; this plan stays out of `pipelines/sensors/` and `pipelines/schedules.py`.
