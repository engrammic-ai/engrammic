# Phase 1: Embedding Cache + TEI

**Spec:** [2026-05-19-recall-optimization.md](../specs/2026-05-19-recall-optimization.md)
**Status:** implementation-complete
**Priority:** high (500ms embedding bottleneck)

## Goal

Replace Vertex AI embedding at query time with a Redis-cached local backend (TEI sidecar or FastEmbed) to cut recall embedding latency from ~500ms to <50ms.

## Background

The current flow in `_context_query` calls `ctx_svc.query()`, which calls `self._embedding.embed_query(query)` inside `ContextService`. The embedding service is `LiteLLMEmbeddingService` backed by `vertex_ai/text-embedding-005`. That round-trip costs ~500ms.

An `EmbeddingCache` class already exists at `src/context_service/cache/embedding_cache.py` and is wired into `LiteLLMEmbeddingService` on the write/document path. It is **not** used at query time, because `embed_query` delegates to `embed_single` which uses the hardcoded task key `"passage"` - the same key used for document ingestion. The `models.yaml` already has a `hybrid` tier with `provider: tei` defined, but `build_embedding_service` reads from `config/embeddings.yaml` (a flat file with `provider: litellm`) and ignores `models.yaml`.

## File Map

| File | Role |
|------|------|
| `config/embeddings.yaml` | Primary embedding config read by `build_embedding_service` |
| `config/models.yaml` | Tier-based model config (has `hybrid` tier with TEI, unused by embedding factory) |
| `src/context_service/embeddings/__init__.py` | `build_embedding_service` factory |
| `src/context_service/embeddings/litellm_embeddings.py` | LiteLLM-backed embedding service |
| `src/context_service/embeddings/base.py` | `EmbeddingService` protocol |
| `src/context_service/cache/embedding_cache.py` | Redis cache (`cache:embed:{task}:{sha256}`) |
| `src/context_service/api/app.py` | Composition root - wires `EmbeddingCache` -> `build_embedding_service` |
| `src/context_service/services/context.py` | `ContextService.query` - calls `embed_query` |
| `src/context_service/config/settings.py` | `embedding_cache_ttl` field (default 604800 = 7 days) |

## Tasks

### Task 1: Fix `embed_query` to use a separate cache task key

**Context:** `embed_query` currently delegates to `embed_single` which uses task key `"passage"`. Query embeddings should use task key `"query"` to avoid key collisions with document embeddings and to allow different TTLs per task in future.

**Files:**
- `src/context_service/embeddings/litellm_embeddings.py`
- `tests/cache/test_embedding_cache_query_task.py` (new)

**Changes:**

1. Override `embed_query` in `LiteLLMEmbeddingService` to bypass the inherited `embed`/`embed_single` path and directly use `task="query"`:

```python
async def embed_query(self, query: str) -> list[float]:
    """Generate query embedding with 'query' cache task key."""
    if self._embedding_cache:
        cached = await self._embedding_cache.get(query, "query")
        if cached is not None:
            return cached
        vector = (await self._embed_batch([query]))[0]
        await self._embedding_cache.set(query, "query", vector)
        return vector
    return (await self._embed_batch([query]))[0]
```

Cache key becomes `cache:embed:query:{sha256(query)}` - separate from `cache:embed:passage:{sha256(text)}`.

**Test:** `tests/cache/test_embedding_cache_query_task.py`

- `test_embed_query_uses_query_task_key` - mock `EmbeddingCache.get/set`, assert called with `task="query"`
- `test_embed_query_cache_hit_skips_batch` - inject cached vector, assert `_embed_batch` not called
- `test_embed_query_cache_miss_populates_cache` - no cached vector, assert `set` called with `task="query"`

- [ ] Write failing tests
- [ ] Run: `uv run pytest tests/cache/test_embedding_cache_query_task.py -v` - expected FAIL
- [ ] Implement `embed_query` override
- [ ] Run tests: expected PASS
- [ ] `uv run just check`

### Task 2: Add `TEIEmbeddingService`

**Context:** The `hybrid` tier in `models.yaml` specifies `provider: tei` but no implementation exists. `TEIEmbeddingService` calls TEI's `POST /embed` endpoint, implements the `EmbeddingService` protocol, and uses task key `"query"` in `embed_query` (same fix as Task 1).

**Files:**
- `src/context_service/embeddings/tei_embeddings.py` (new)
- `src/context_service/embeddings/__init__.py`
- `src/context_service/config/settings.py`

**Changes:**

1. Create `src/context_service/embeddings/tei_embeddings.py`. TEI API: `POST /embed` with `{"inputs": ["text1", "text2"]}` -> `[[float, ...], ...]`. Use `httpx.AsyncClient`. Implement `embed`, `embed_single`, `embed_query`, `close`. Wire `EmbeddingCache` with `task="passage"` on `embed` and `task="query"` on `embed_query`.

2. Add `tei_url: str | None = Field(default=None, ...)` to `Settings` in `src/context_service/config/settings.py`. Maps to env var `TEI_URL` via pydantic-settings.

3. Export `TEIEmbeddingService`, `TEIEmbeddingError` from `src/context_service/embeddings/__init__.py`.

**Note:** Create `tests/embeddings/__init__.py` first - directory doesn't exist.

**Test:** `tests/embeddings/test_tei_embeddings.py`

- `test_tei_embed_calls_endpoint` - mock httpx, verify `{"inputs": [...]}` body
- `test_tei_embed_returns_vectors` - mock returning `[[0.1, 0.2]]`, assert output
- `test_tei_embed_query_uses_query_task_key` - verify cache `task="query"` on `embed_query`
- `test_tei_embed_raises_on_http_error` - 500 response -> `TEIEmbeddingError`
- `test_tei_embed_cache_hit_skips_http` - cached vector, assert HTTP call skipped

- [ ] Write failing tests
- [ ] Run: `uv run pytest tests/embeddings/ -v` - expected FAIL
- [ ] Create `tei_embeddings.py`, add `tei_url` setting, update `__init__.py`
- [ ] Run tests: expected PASS
- [ ] `uv run just check`

### Task 3: Update `build_embedding_service` to dispatch on `provider`

**Context:** `build_embedding_service` always returns `LiteLLMEmbeddingService` regardless of `provider` in `embeddings.yaml`. Add a `provider: tei` branch.

**Files:**
- `src/context_service/embeddings/__init__.py`

**Changes:**

```python
def build_embedding_service(
    embedding_cache: "EmbeddingCache | None" = None,
) -> EmbeddingService:
    config = load_config("embeddings")
    provider = config.get("provider", "litellm")

    if provider == "tei":
        from context_service.config.settings import get_settings
        from context_service.embeddings.tei_embeddings import TEIEmbeddingService

        settings = get_settings()
        if not settings.tei_url:
            raise RuntimeError(
                "embeddings.yaml sets provider=tei but TEI_URL is not configured."
            )
        return TEIEmbeddingService(
            base_url=settings.tei_url,
            dimensions=config.get("dimensions", 768),
            _embedding_cache=embedding_cache,
        )

    return LiteLLMEmbeddingService.from_config(_embedding_cache=embedding_cache)
```

**Test:** `tests/embeddings/test_build_embedding_service.py`

- `test_build_litellm_when_provider_litellm`
- `test_build_tei_when_provider_tei` (mock settings with `tei_url`)
- `test_build_tei_raises_without_tei_url`

- [ ] Write failing tests
- [ ] Update factory
- [ ] Run tests: expected PASS
- [ ] `uv run just check`

### Task 4: Add TEI -> LiteLLM fallback wrapper

**Context:** TEI is a sidecar. If it is unavailable, recall must not error. `TEIWithFallbackEmbeddingService` wraps TEI as primary and LiteLLM as fallback, catching `TEIEmbeddingError` on every call.

**Files:**
- `src/context_service/embeddings/tei_embeddings.py`
- `src/context_service/embeddings/__init__.py`

**Changes:**

1. Add `TEIWithFallbackEmbeddingService` to `tei_embeddings.py`. Implements `EmbeddingService` protocol. All three methods (`embed`, `embed_single`, `embed_query`) try primary, catch `TEIEmbeddingError`, log `tei_fallback_triggered`, delegate to fallback.

2. Update `build_embedding_service` to wrap: when `provider=tei`, return `TEIWithFallbackEmbeddingService(primary=tei_svc, fallback=LiteLLMEmbeddingService.from_config(...))`.

**Test:** `tests/embeddings/test_tei_fallback.py`

- `test_fallback_triggered_on_tei_error` - TEI raises, fallback called
- `test_no_fallback_on_success` - TEI succeeds, fallback never called
- `test_fallback_all_paths` - covers `embed`, `embed_single`, `embed_query`

- [ ] Write failing tests
- [ ] Implement and update factory
- [ ] Run tests: expected PASS
- [ ] `uv run just check`

### Task 5: Add cache hit/miss metrics

**Context:** No observability on query-time embedding cache hit rate. Need Prometheus counters to measure impact and validate <50ms target.

**Files:**
- `src/context_service/telemetry/metrics.py`
- `src/context_service/cache/embedding_cache.py`

**Changes:**

1. Add `record_embedding_cache_hit(task: str)` and `record_embedding_cache_miss(task: str)` to `metrics.py`. Follow the existing `record_embedding` pattern.

2. In `EmbeddingCache.get`: call `record_embedding_cache_hit(task)` on non-None return.

3. In `LiteLLMEmbeddingService.embed` and `TEIEmbeddingService.embed`: call `record_embedding_cache_miss(task)` once per uncached text (not per batch). Track count of uncached texts before `_embed_batch`, then call `record_embedding_cache_miss(task)` that many times.

**Test:** `tests/cache/test_embedding_cache_metrics.py`

- `test_cache_hit_records_hit_metric` - pre-populate cache, call `get`, assert metric called
- `test_cache_miss_does_not_record_hit` - empty cache, assert hit metric not called

- [ ] Write failing tests
- [ ] Add metric functions and wire calls
- [ ] Run tests: expected PASS
- [ ] `uv run just check`

### Task 6: Integration smoke test - cache prevents duplicate embedding calls

**Context:** Unit-level integration test. Two identical `embed_query` calls on the same service instance should call `_embed_batch` only once.

**Files:**
- `tests/mcp/test_recall_embedding_cache.py` (new)

**Changes:**

```python
async def test_second_query_hits_cache():
    # Use AsyncMock for cache - InMemoryEmbeddingCache doesn't exist
    cache = AsyncMock(spec=EmbeddingCache)
    cache.get = AsyncMock(side_effect=[None, [0.1, 0.2]])  # miss, then hit
    cache.set = AsyncMock()
    svc = LiteLLMEmbeddingService(model="...", _embedding_cache=cache)
    svc._embed_batch = AsyncMock(return_value=[[0.1, 0.2]])

    await svc.embed_query("what is the revenue target?")
    await svc.embed_query("what is the revenue target?")

    svc._embed_batch.assert_called_once()

async def test_query_and_passage_cache_keys_do_not_collide():
    # embed_query and embed_single on the same text should each call _embed_batch once
    # because they use different task keys ("query" vs "passage")
    ...
```

- [ ] Write tests
- [ ] Run: `uv run pytest tests/mcp/test_recall_embedding_cache.py -v` - expected PASS
- [ ] `uv run just check`

### Task 7: Operational validation

**Context:** Measure actual latency improvement. No code changes.

**Steps:**

1. Start TEI sidecar:

```bash
docker run --rm -p 8080:80 \
  -e MODEL_ID=nomic-ai/nomic-embed-text-v1.5 \
  ghcr.io/huggingface/text-embeddings-inference:cpu-1.6 \
  --model-id nomic-ai/nomic-embed-text-v1.5
```

2. Set env `TEI_URL=http://localhost:8080`, change `config/embeddings.yaml` to `provider: tei`.

3. Run `just dev`, issue 20 `recall` calls via MCP client.

4. Check SigNoz for `embedding.tei` span durations. Target: p50 <50ms.

5. Repeat the same query twice - confirm second span shows cache hit (no HTTP call to TEI sidecar).

6. Revert `config/embeddings.yaml` to `provider: litellm` before merging.

- [ ] Run TEI locally, measure p50/p95
- [ ] Confirm cache hit on second identical query
- [ ] Document observed latencies as a comment on the spec

## Rollout

**Development:** All tasks are behind a config switch (`provider` in `embeddings.yaml`). Existing behavior (Vertex LiteLLM) is unchanged until the operator changes config. Merge when Tasks 1-6 tests pass and `just check` is clean.

**Staging:** Set `TEI_URL` and switch `embeddings.yaml` to `provider: tei`. Monitor `tei_fallback_triggered` log events and `embedding.tei` OTEL spans.

**Production:** Promote after staging shows <50ms p50 and no recall quality regression. The Vertex fallback remains active - TEI downtime causes automatic fallback with no user-visible errors.

**Docker Compose note:** Add `healthcheck` and `depends_on` for TEI sidecar to ensure it's ready before context-service starts. First embed call will fallback silently if TEI isn't healthy yet.

## Success Criteria

- p50 `embed_query` latency: <50ms with TEI running (down from ~500ms)
- Embedding cache hit rate: >60% after warm-up (metric from Task 5)
- `just test` passes with no new failures
- `just check` passes (mypy strict + ruff)
- Second identical `recall` does not call `_embed_batch` (Task 6 test)
- TEI unavailable: fallback to Vertex automatic, no recall errors (Task 4 test)

## Non-Goals (Deferred)

- Tiered result cache (Phase 2)
- Matryoshka 512-dim truncation (Phase 3)
- Qdrant scalar quantization (Phase 3)
- Similarity / cosine near-match cache (Phase 4)
- Single-flight / stampede protection (Phase 2)
