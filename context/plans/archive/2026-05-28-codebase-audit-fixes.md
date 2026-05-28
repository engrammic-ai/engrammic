# Codebase Audit Fixes

**Goal:** Address gaps found in the May 28 codebase review — unwired code, behavior mismatches, dead code, and mcp-client drift.

**Branch:** `fix/codebase-audit-may28`

---

## Phase 1: Critical Fixes (context-service)

### Task 1.1: Register Orphan Dagster Jobs

**Files:** `src/context_service/pipelines/definitions.py`

**Problem:** `orphan_chain_recovery_job`, `orphan_recovery_schedule`, `usage_retention_job`, `usage_retention_schedule` are exported from `jobs/__init__.py` but not registered in `definitions.py`. These jobs never run.

- [ ] Import missing jobs and schedules from `context_service.pipelines.jobs`
- [ ] Add jobs to `jobs=[]` list in `dg.Definitions`
- [ ] Add schedules to `schedules=[]` list
- [ ] Verify `usage.retention_enabled` defaults to `False` (safe by default)
- [ ] Run `just check`

**Effort:** LOW (15 min)

---

### Task 1.2: Fix Commitment Multi-Label

**Files:** `src/context_service/services/context.py`

**Problem:** `commit_belief()` stores with `node_type="Commitment"` but schema requires `:Claim:Commitment` dual label. Commitments are invisible to custodian Cypher matching `:Claim:Commitment`.

- [ ] Update `store()` signature to accept `extra_labels: list[str] | None = None`
- [ ] Modify CREATE Cypher to include extra labels: `CREATE (n:Node:{node_type}{extra_label_str} {...})`
- [ ] Update `commit_belief()` call to pass `extra_labels=["Claim"]`
- [ ] Add `"Commitment"` to `_KNOWLEDGE_LAYER_TYPES` (or switch to `KnowledgeLabel` enum)
- [ ] Write test verifying Commitment nodes have both `:Claim:Commitment` labels
- [ ] Run `just check && just test -k commit`

**Effort:** MEDIUM (1-2 hr)

---

### Task 1.3: Fix Groundskeeper Cron

**Files:** `src/context_service/pipelines/schedules.py`

**Problem:** Spec says every 15 minutes, code has `0 * * * *` (hourly).

- [ ] Change `cron_schedule="0 * * * *"` to `cron_schedule="*/15 * * * *"` on `sage_groundskeeper_schedule`
- [ ] Update docstring/description from "hourly" to "every 15 minutes"
- [ ] Update comment at line 6
- [ ] Run `just check`

**Effort:** LOW (10 min)

---

## Phase 2: MCP-Client Sync

**Repo:** `../mcp-client/`

### Task 2.1: Delete Stale Tools

**Problem:** 4 tools post to non-existent REST routes — runtime 404.

- [ ] Delete `src/engrammic_mcp/tools/context_accept_belief.py`
- [ ] Delete `src/engrammic_mcp/tools/context_reject_belief.py`
- [ ] Delete `src/engrammic_mcp/tools/context_belief_state.py`
- [ ] Delete `src/engrammic_mcp/tools/context_admin.py`
- [ ] Remove imports from `tools/__init__.py`
- [ ] Remove tool wrappers from `server.py`
- [ ] Remove `instructions=` string references to these tools
- [ ] Remove test cases from `tests/test_tools.py`
- [ ] Run tests

**Effort:** MEDIUM (30-45 min)

---

### Task 2.2: Add Missing Tools

**Problem:** `forget`, `dismiss`, `tick` exist on server but not in client.

For each tool:
- [ ] Create `src/engrammic_mcp/tools/{tool}.py` with correct signature
- [ ] Add to `tools/__init__.py`
- [ ] Add wrapper to `server.py`
- [ ] Add basic test

**Signatures:**
- `forget(node_id: str, reason: str | None = None, cascade: bool = False)`
- `dismiss(marker_id: str, reason: str, silo_id: str | None = None)`
- `tick(about_hint: list[str] | None = None, silo_id: str | None = None, session_id: str | None = None, recent_context: str | None = None)`

**Effort:** LOW (30 min)

---

### Task 2.3: Fix Parameter Mismatches

**Problem:** Several tools have param drift.

- [ ] Add `supersedes: str | None = None` to `remember`, `learn`, `believe`
- [ ] Fix `believe` `about` type: `list[str] | str`
- [ ] Fix `recall`: remove `as_of`, add `include_hypotheses`, `bypass_cache`, `max_age_seconds`
- [ ] Fix `patterns`: remove `namespace`/`limit`/`offset`, add `profile`
- [ ] Update `server.py` wrappers for all changes
- [ ] Run tests

**Effort:** LOW (45 min)

---

### Task 2.4: Update README

- [ ] Remove `accept` and `reject` from tool table (SAGE-internal)
- [ ] Verify `forget`, `dismiss`, `tick` descriptions are accurate

**Effort:** LOW (10 min)

---

## Phase 3: Dead Code Cleanup

### Task 3.1: Delete EpistemicStore

**Files:** 
- `src/context_service/engine/epistemic_store.py` — DELETE
- `src/context_service/engine/protocols.py` — remove `EpistemicStore` protocol if defined
- `src/context_service/config/settings.py` — remove `use_epistemic_store` field
- `src/context_service/db/queries.py` — remove `EPISTEMIC_*` queries

**Problem:** Class has broken transaction API (`tx.execute_write()` on raw bolt transaction) AND is never instantiated.

- [ ] Grep for all `EPISTEMIC_` query constants, verify none are used elsewhere
- [ ] Delete `epistemic_store.py`
- [ ] Remove `use_epistemic_store` from settings
- [ ] Remove unused `EPISTEMIC_*` queries
- [ ] Run `just check && just test`

**Effort:** LOW (30 min)

---

### Task 3.2: Delete SynthesizerIdentity

**Files:**
- `src/context_service/custodian/identities/synthesizer.py` — DELETE
- `src/context_service/custodian/identities/__init__.py` — remove export

**Problem:** Class is never instantiated. Pipeline uses `engine/synthesis.py` instead.

- [ ] Grep to confirm no instantiation: `SynthesizerIdentity(`
- [ ] Delete `synthesizer.py`
- [ ] Remove from `__init__.py` exports
- [ ] Keep `SynthesizerIdentityConfig` in settings (used by pipeline)
- [ ] Run `just check && just test`

**Effort:** LOW (15 min)

---

### Task 3.3: Clean Legacy register() Functions

**Files:**
- `src/context_service/mcp/tools/context_store.py`
- `src/context_service/mcp/tools/context_crystallize.py`
- `src/context_service/mcp/tools/context_link.py`
- `src/context_service/mcp/tools/context_update_belief.py`

**Problem:** Dead `register()` functions that would register old `context_*` tools if called.

- [ ] Remove `register()` function from each file (keep the `_impl` functions — they're used by intent-based tools)
- [ ] Run `just check`

**Effort:** LOW (20 min)

---

### Task 3.4: Add forget to __init__.py

**File:** `src/context_service/mcp/tools/__init__.py`

**Problem:** `forget` module missing from exports (cosmetic, runtime works).

- [ ] Add `from context_service.mcp.tools import forget` and `"forget"` to `__all__`

**Effort:** LOW (5 min)

---

## Phase 4: Test Harness (Optional for Beta)

### Task 4.1: Rewrite E2E Test Harness

**File:** `tests/e2e/test_mcp_tools.py`

**Problem:** 61 tests skipped because they use old `context_*` tool names.

- [ ] Update helpers to use new verb-based tools:
  - `store()` → split by layer: `remember()`, `learn()`, `believe()`, etc.
  - `recall()` → `recall()`
  - `link()` → `link()`
  - `admin()` → remove or split into `trace()`
- [ ] Remove `pytestmark = pytest.mark.skip`
- [ ] Fix failing tests iteratively
- [ ] Target: at least 30 of 61 tests passing

**Effort:** HIGH (4-6 hr)

---

## Phase 5: Low-Priority Fixes (Post-Beta)

### Task 5.1: Fix _node_to_knowledge_node Case

**File:** `src/context_service/engine/memgraph_store.py`

**Problem:** Map uses lowercase keys, node.type is title-case. Currently no impact (methods not called).

- [ ] Change line 58 to: `layer = _layer_map.get((node.type or node.label or "").lower(), Layer.MEMORY)`
- [ ] Add missing types: `"fact"`, `"commitment"`, `"belief"`, etc.

**Effort:** LOW — defer until primitives protocol is actually used.

---

### Task 5.2: Remove Dead Synthesizer Config

**File:** `src/context_service/config/identities.yaml`

- [ ] Remove `schedule_cron` and `threshold_pending_nodes` from synthesizer section (never read)

**Effort:** LOW — cosmetic cleanup.

---

## Done Criteria

- [ ] Phase 1 complete: orphan jobs registered, commitment label fixed, groundskeeper cron fixed
- [ ] Phase 2 complete: mcp-client in sync with server surface
- [ ] Phase 3 complete: dead code removed
- [ ] `just ci` passes
- [ ] No new test failures introduced

---

## Priority for Beta

1. **Task 1.1** (orphan jobs) — jobs exist but never run
2. **Task 1.2** (commitment label) — silent data bug
3. **Task 2.1** (stale mcp-client tools) — runtime 404s
4. **Task 1.3** (groundskeeper cron) — one-line fix
5. **Task 2.2-2.4** (mcp-client sync) — feature parity
6. **Phase 3** (dead code) — cleanup
7. **Phase 4** (tests) — optional for beta launch
