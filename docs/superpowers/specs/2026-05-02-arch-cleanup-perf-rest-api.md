# Design: Architecture Cleanup, Performance, and REST API

**Date:** 2026-05-02
**Status:** Approved
**Drivers:** Technical debt paydown (D), market expansion via REST API (C)

## Overview

Three workstreams to solidify the foundation and expand access beyond MCP:

1. Architecture cleanup (settings consolidation, protocol adoption)
2. Performance optimizations (orjson, N+1 batching, pool tuning)
3. REST API surface for non-agent consumers (Silt data layer replacement scenario)

## Sequencing

**Approach: Quick wins then parallel**

- Phase 1a: Quick wins (settings, orjson, batching)
- Phase 1b: Protocol adoption + REST API design in parallel
- Phase 2: REST API implementation
- Deferred: Pool tuning (needs load test data)

## Phase 1a: Quick Wins

Three focused PRs, each independently shippable.

### 1. Settings Consolidation

- Merge `core/settings.py` into `config/settings.py`
- Keep nested models (InfraConfig, RetrievalTuning) as sub-configs on canonical Settings
- Expose deprecated field aliases during migration (`@property` with removal TODO for Q3)
- Delete `core/settings.py` once empty

**Done:** Single `get_settings()` everywhere, `just check` green.

### 2. orjson Swap

- Replace stdlib `json` with `orjson` on hot paths
- Target modules: `services/context.py`, `engine/`, `mcp/tools/`, `api/`
- Keep stdlib for non-perf paths (config loading, one-time serialization, tests)
- Add `orjson` to dependencies

Migration gotchas:
- `datetime`: use `orjson.OPT_NAIVE_UTC` or serialize to ISO string before encoding
- No `default=` function: pre-convert non-native types (UUID, Enum, dataclass)
- Returns `bytes` not `str`: use `.decode()` where string needed, or keep bytes for HTTP responses
- `orjson.dumps()` options via bitwise OR: `OPT_SERIALIZE_NUMPY | OPT_NAIVE_UTC`

**Done:** ~67 call sites migrated, benchmarks show improvement on serialization-heavy paths.

### 3. N+1 Batching

Two locations:

- `extraction/service.py:354-416`: batch claim writes with UNWIND
- `engine/memgraph_store.py:629-655`: batch hyperedge participant writes with UNWIND

**Done:** No single-row writes in ingest hot path.

## Phase 1b: Parallel Workstreams

### Workstream A: Protocol Adoption

Migrate `services/context.py` and `custodian/` to depend on `engine/protocols.py` instead of raw `MemgraphClient`.

**Tasks:**

1. Audit `engine/protocols.py`, identify missing methods (transactions, execute_write variants)
2. Add missing protocol methods with strict type annotations
3. Migrate `services/context.py` (~19 inline Cypher queries) to protocol, method by method, green at each commit
4. Migrate `custodian/` (19 files) to protocol, grouped by subsystem (validators, write_path, promotion, etc.)
5. Add in-memory protocol fake in `tests/fakes/memgraph_fake.py`
   - Dict-backed node/edge storage
   - Transaction support (begin/commit/rollback with snapshot isolation)
   - Basic Cypher subset: MATCH, CREATE, MERGE, DELETE, SET, WHERE, RETURN
   - No query optimizer or index semantics (tests should not depend on perf)
6. Migrate one integration test to use fake as demo
7. Add CI check: fail on direct `MemgraphClient` imports outside `engine/`, `stores/`, `db/`

**Done:**
- All service/custodian code depends on protocol type, not concrete client
- In-memory fake exists and one test uses it
- CI boundary check prevents regression

### Workstream B: REST API Design

Contract-first design, no implementation.

**Deliverables:**
- `docs/api/openapi.yaml` - full OpenAPI 3.0 spec
- `docs/api/REST-CONTRACT.md` - design rationale, auth flow, webhook contract

**Contract scope:**

Core endpoints (mirror MCP tools):
- `GET /v1/context/{id}` - context_get
- `POST /v1/context/query` - context_query
- `POST /v1/context/graph` - context_graph
- `GET /v1/context/{id}/history` - context_history (time-travel)
- `GET /v1/context/{id}/provenance` - context_provenance (lineage)
- `POST /v1/context/remember` - context_remember
- `POST /v1/context/assert` - context_assert
- `POST /v1/context/commit` - context_commit
- `POST /v1/context/reason` - context_reason (multi-step chains)
- `POST /v1/context/reflect` - context_reflect
- `POST /v1/context/link` - context_link

Bulk endpoints:
- `POST /v1/ingest` - batch document/memory ingestion, returns job ID
- `GET /v1/ingest/{job_id}` - poll job status (includes per-item success/failure)
- `POST /v1/query/bulk` - multiple queries in one request

Bulk ingest error semantics:
- Partial success model: each item processed independently, failures don't block others
- Response includes `succeeded: []`, `failed: [{index, error}]` arrays
- Caller decides whether to retry failed items
- No atomic rollback (too expensive at scale; use single-item endpoint if atomicity needed)

Webhooks:
- `POST /v1/webhooks` - register callback URL + event filter
- `GET /v1/webhooks` - list registered webhooks
- `DELETE /v1/webhooks/{id}` - unregister
- Events: `context.created`, `context.updated`, `claim.promoted`, `cluster.updated`

Webhook delivery contract:
- Signed payloads: HMAC-SHA256 signature in `X-Delta-Signature` header, secret set at registration
- Retry policy: exponential backoff (1s, 5s, 30s, 5m, 30m), max 5 attempts
- Dead letter: failed webhooks after retries logged to `webhook_failures` table, surfaced via `GET /v1/webhooks/{id}/failures`
- Timeout: 10s per delivery attempt

Silo management:
- `POST /v1/silos` - create silo
- `GET /v1/silos` - list silos for org (includes archived if `?include_archived=true`)
- `GET /v1/silos/{id}` - silo details + stats
- `DELETE /v1/silos/{id}` - soft delete (sets `archived_at`, data retained 30 days)
- `DELETE /v1/silos/{id}?hard=true` - hard delete (immediate purge, requires admin role)
- `POST /v1/silos/{id}/restore` - restore archived silo (within 30-day window)
- `POST /v1/silos/{id}/export` - trigger export job (uses existing beta4 JSONL format)
- `POST /v1/silos/import` - import from JSONL (beta4 format, with schema version check)

Org management (metadata layer over WorkOS):
- `GET /v1/org` - current org details (synced from WorkOS + local settings)
- `GET /v1/org/members` - list users in org (reads from WorkOS, enriches with local roles)
- `PATCH /v1/org/members/{id}` - update Delta Prime role (admin/member/viewer, stored locally)

User lifecycle (invite/remove) handled via WorkOS dashboard or their API directly. We store only role assignments and preferences, not user records.

Usage/Stats:
- `GET /v1/org/usage` - node counts, query volume, storage
- `GET /v1/silos/{id}/stats` - per-silo metrics

**Design decisions:**
- Auth: WorkOS flow, Bearer tokens (same as MCP)
- Versioning: `/v1/` prefix, additive changes only
- Silo ID derived from auth context (same as MCP)

## Phase 2: REST API Implementation

Build on protocol layer from 1b, implement OpenAPI contract.

**Implementation approach:**
- Handlers call same service layer as MCP tools (no logic duplication)
- Routes in `api/routes/v1/` mirroring the endpoint structure
- Bulk operations use Dagster for async job tracking
- Webhooks use Redis pub/sub for event dispatch
- Rate limiting via Redis (existing infra)

**Endpoints by priority:**

1. Core context operations (highest - Silt needs these)
2. Silo management (high - partner onboarding)
3. Bulk ingest/query (high - data layer replacement)
4. Webhooks (medium - enables reactive integrations)
5. Org/user management (medium - self-service)
6. Usage/stats (lower - nice-to-have for dashboards)

## Deferred: Pool Tuning

Current state: fixed Memgraph pool of 50 connections.

**Approach:**
1. Add Prometheus metrics: pool utilization, wait time, exhaustion events
2. Load test with realistic partner workload
3. Tune based on observed data

**Likely outcomes:** Dynamic pool sizing or per-silo connection pools.

**Timing:** After Phase 2 ships and we have real load patterns.

## Testing Strategy

- **Phase 1a:** Unit tests for each change, existing integration suite validates no regression
- **Phase 1b protocol:** In-memory fake enables fast unit tests for entire service layer
- **Phase 2 REST:** Contract tests against OpenAPI spec, integration tests against real stack
- **Bulk/webhook:** Dedicated scenarios added to `e2e-test-scenarios.md`

## Rollout

- REST API behind feature flag (`REST_API_ENABLED=false` by default)
- Silt gets early access branch for feedback
- MCP remains primary surface; REST is additive, not replacement
- No breaking changes to MCP during this work

## Documentation

- REST API docs auto-generated from OpenAPI via Redoc or similar
- Integration guide for partners: auth flow, webhook setup, bulk ingest patterns
- Migration guide: MCP to REST for teams that want HTTP-only

## Success Criteria

**Phase 1a:**
- Single Settings class, all callers migrated
- orjson on hot paths, measurable serialization improvement
- No N+1 writes in ingest path

**Phase 1b:**
- Protocol adoption complete, CI enforces boundary
- OpenAPI spec reviewed by Silt, no blocking feedback

**Phase 2:**
- Silt successfully integrates via REST API
- Bulk ingest handles 10k documents in single request
- Webhook delivery within 5s of event
