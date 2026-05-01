# Scaling and Resilience Fixes

**Status:** Draft  
**Created:** 2026-05-01  
**Priority:** High (pre-production)

## Context

Codebase review identified 4 scaling risks and 4 performance issues that could cause production failures under load. This plan addresses the scaling/resilience issues; performance optimizations (batching, orjson) are tracked separately.

## Problems

### 1. Unbounded LLM Concurrency in Clustering
**Location:** `clustering/service.py:86`

`generate_cluster_summaries()` uses a per-batch semaphore (max 5) but spawns unbounded batches. With hundreds of clusters, this creates N concurrent `asyncio.gather()` calls, each with 5 LLM requests.

**Risk:** Memory exhaustion, API quota burnout.

### 2. Stale Service Singletons
**Location:** `mcp/server.py:23-50`

Module-level `_services` dict holds singleton instances. If a backing store (Memgraph, Redis, Qdrant) dies, the stale service object is never replaced. Callers execute queries against dead connections.

**Risk:** Silent failures, cascading degradation on store restart.

### 3. No Circuit Breaker on Access Event Emits
**Location:** `mcp/tools/context_query.py:86`

Access event emission uses bare `asyncio.gather(*emits)` with no timeout or error handling. If Redis is slow/down, all `context_query` responses block.

**Risk:** Cascading timeout failures.

### 4. Mutable Cached Settings
**Location:** `core/settings.py:700-706`

`@lru_cache get_settings()` returns a singleton that mutates in-place via `reload_from_yaml()`. Breaks cache contract; concurrent reloads cause partial state visibility.

**Risk:** Config drift, inconsistent behavior across requests.

---

## Implementation Plan

### Phase 1: Circuit Breakers and Timeouts (Low risk, high impact)

#### 1.1 Fire-and-forget access emits
- Wrap `asyncio.gather(*emits)` with `asyncio.wait_for(timeout=2.0)`
- Catch `TimeoutError` and `Exception`, log warning, continue
- Access events are observability, not correctness-critical

#### 1.2 Add global LLM concurrency semaphore
- Create `src/context_service/llm/concurrency.py` with module-level `asyncio.Semaphore(20)`
- Wrap all LLM calls in clustering/extraction through this semaphore
- Make limit configurable via settings

### Phase 2: Service Health and Recovery (Medium complexity)

#### 2.1 Add health check protocol
- Define `HealthCheckable` protocol in `engine/protocols.py`
- Implement `async def health_check() -> bool` on Memgraph, Qdrant, Redis stores
- Simple ping/echo, timeout 1s

#### 2.2 Service registry with health monitoring
- Replace module-level `_services` dict with `ServiceRegistry` class
- Add periodic health check (every 30s via background task)
- On failure: log error, mark service unhealthy, rebuild on next request
- Wire into FastAPI lifespan

### Phase 3: Settings Immutability (Breaking change, needs care)

#### 3.1 Make Settings frozen
- Add `model_config = ConfigDict(frozen=True)` to Settings
- Remove `reload_from_yaml()` mutation
- Reload creates new instance, atomically replaces cached value

#### 3.2 Settings reload via atomic swap
- Change `get_settings()` to use `contextvars.ContextVar` instead of `lru_cache`
- Provide `reload_settings()` that creates new instance and sets the contextvar
- All callers get consistent snapshot within a request

---

## Verification

- [ ] Load test clustering with 500+ clusters, confirm memory stable
- [ ] Kill Redis mid-request, confirm graceful degradation (logged warning, no hang)
- [ ] Kill Memgraph, confirm service recovers on reconnect within 60s
- [ ] Hot-reload settings under concurrent requests, confirm no partial state

## Not in Scope

- Performance optimizations (batching, orjson) - separate plan
- Connection pool tuning - separate config change
- Qdrant quantization - ops task, not code change
