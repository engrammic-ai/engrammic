# Embedding Batching Design

**Date:** 2026-06-05  
**Status:** Approved  
**Author:** Claude + NovusEdge

## Problem

The reaction worker processes `compute_embedding` tasks one node at a time. Each task calls `embed_single()`, making one Vertex AI API call per text. This is inefficient:

- Vertex AI supports batching (up to ~100 texts per call)
- With 4 workers making single-text requests, we use 4 API calls where 1 batched call could suffice
- Rate limits (250 RPM) become the bottleneck during burst operations (seeding, backfills)

## Goals

1. **API efficiency:** Maximize texts per API call
2. **Throughput:** Faster bulk operations during bursts
3. **Minimal disruption:** No changes to task handlers or event emission

## Non-Goals

- Cross-worker coordination (deferred, likely unnecessary)
- Interactive latency optimization (embedding is already async)

## Design

### Phase 1: Count-Based Batching with `batched` Library

Use the [`batched`](https://pypi.org/project/batched/) Python library to auto-batch concurrent `embed_single()` calls.

#### Core Changes

**Dependency:** Add `batched` to `pyproject.toml`

**Modified module:** `src/context_service/embeddings/litellm_embeddings.py`

```python
import batched

class LiteLLMEmbeddingService:
    def __init__(self, ..., batching_enabled: bool = True, batch_size: int = 32,
                 timeout_ms: int = 100, small_batch_threshold: int = 4):
        # ... existing init ...
        
        self._batching_enabled = batching_enabled
        
        if batching_enabled:
            @batched.aio.dynamically(
                batch_size=batch_size,
                timeout_ms=timeout_ms,
                small_batch_threshold=small_batch_threshold,
            )
            async def _batched_embed(texts: list[str]) -> list[list[float]]:
                return await self._embed_batch(texts)
            
            self._batched_embed = _batched_embed
    
    async def embed_single(self, text: str) -> list[float]:
        if self._batching_enabled:
            results = await self._batched_embed([text])
            return results[0]
        return (await self._embed_batch([text]))[0]
```

**Task handler:** `reactions/tasks.py` unchanged. Still calls `embed_single()`, batching is transparent.

#### Configuration

**New section in `config/embeddings.yaml`:**

```yaml
# Existing config...
provider: litellm
model: vertex_ai/text-embedding-005
dimensions: 768

# Batching config
batching:
  enabled: true
  batch_size: 32              # max texts per API call
  timeout_ms: 100             # max wait before firing partial batch
  small_batch_threshold: 4    # fire early if this many waiting
```

**Feature flag:** `batching.enabled` allows disabling if issues arise.

#### Embedding Cache Before Upsert

**Problem identified in review:** If embedding succeeds for a batch of 32 but Qdrant upsert fails for node 17, that node retries and re-embeds solo (wasted API call).

**Fix:** Cache embeddings in Redis immediately after batch completes, before Qdrant upsert.

```python
# In compute_embedding_task (tasks.py)
embedder = build_embedding_service()
vector = await embedder.embed_single(content)

# Cache embedding before upsert (new)
if embedding_cache:
    await embedding_cache.set(content, "passage", vector)

# Then upsert to Qdrant
await qdrant.upsert(...)
```

This way, if Qdrant fails and the task retries, the embedding is served from cache.

#### Graceful Shutdown Handler

**Problem identified in review:** On SIGTERM, pending batches may be lost.

**Fix:** Add shutdown handler to flush pending batches.

```python
# In worker.py
import signal
import atexit

def _flush_pending_embeddings():
    """Flush any pending embedding batches on shutdown."""
    # batched library flushes on event loop close, but we ensure
    # worker waits for pending tasks before exiting
    logger.info("worker_shutdown_flushing_embeddings")

atexit.register(_flush_pending_embeddings)
```

Note: The `batched` library handles flush on event loop close. The worker should use graceful shutdown (wait for in-flight tasks) rather than hard kill.

#### Data Flow

```
Worker 1: compute_embedding(node_A) ─┐
Worker 1: compute_embedding(node_B) ─┼─► batched decorator ─► embed([A,B,C]) ─► Vertex AI
Worker 1: compute_embedding(node_C) ─┘      (same worker)         single call
                                           collects up to 100ms

Worker 2: compute_embedding(node_D) ─┐
Worker 2: compute_embedding(node_E) ─┴─► separate batch ─► embed([D,E]) ─► Vertex AI
```

Each worker process has its own `batched` instance. Batching only occurs within a single worker's concurrent tasks.

#### Error Handling

| Scenario | Behavior |
|----------|----------|
| API error (rate limit, timeout) | Existing retry logic in `_embed_batch` handles it |
| Batch failure | All callers get exception, Taskiq retries original tasks |
| Partial batch (timeout) | Fires with available texts, no error |
| Worker shutdown | Graceful shutdown flushes pending, hard kill may lose in-flight |
| Qdrant upsert fails | Embedding cached in Redis, retry serves from cache |

#### Observability

**New metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `embedding_batch_size` | Histogram | Actual texts per batch (track fill rate) |
| `embedding_batch_timeout_ratio` | Counter | Batches that fired on timeout vs full |
| `embedding_batch_per_worker` | Counter | Batch count per worker (detect uneven distribution) |
| `embedding_small_batch_bypass` | Counter | Batches that fired early via small_batch_threshold |

**Logging:**

```python
log.info("embedding_batch_fired", 
    batch_size=len(texts),
    trigger="timeout|full|threshold",
    wait_ms=actual_wait,
    worker_id=worker_id,
)
```

**Instrumentation requirement:** Before assuming batching helps, validate that actual batch sizes are >1 in typical workloads. If median batch size is <4, the overhead may not justify complexity.

#### Testing

**Unit tests** (`tests/test_embedding_batching.py`):

| Test | Validates |
|------|-----------|
| `test_single_text_batched` | Single call works, returns correct vector |
| `test_multiple_concurrent_batched` | N concurrent calls → 1 API call with N texts |
| `test_timeout_fires_partial_batch` | After 100ms, partial batch fires |
| `test_small_batch_threshold_fires_early` | 4+ waiting fires immediately |
| `test_batching_disabled_fallback` | `enabled: false` bypasses batching |
| `test_error_propagates_to_all_callers` | API error fails all tasks in batch |
| `test_cache_hit_on_retry` | After Qdrant failure, retry serves embedding from cache |

**Integration test** (`tests/integration/test_batch_embedding_flow.py`):

- Emit 20 `COMPUTE_EMBEDDING` events rapidly
- Assert: fewer than 20 API calls made (mock Vertex AI)
- Assert: all 20 nodes have vectors in Qdrant

**Benchmark** (manual):

- Seed 1000 nodes, measure total time and API call count
- Compare: batching enabled vs disabled
- Record: actual batch size distribution

#### Files Changed

1. `pyproject.toml` — add `batched` dependency
2. `config/embeddings.yaml` — add `batching` section
3. `src/context_service/embeddings/litellm_embeddings.py` — wrap with `@batched.aio.dynamically`
4. `src/context_service/reactions/tasks.py` — add embedding cache before Qdrant upsert
5. `src/context_service/reactions/worker.py` — add shutdown handler
6. `src/context_service/telemetry/metrics.py` — add batch metrics
7. `tests/test_embedding_batching.py` — new test file

**Estimated effort:** 3-4 hours

---

### Phase 2: Token-Budget Batching

**Trigger:** Implement when metrics show underutilized batches (short texts wasting capacity) or timeout issues (long texts).

**Design:**

Replace count-based batching with token-budget approach:

```python
class TokenBudgetBatcher:
    def __init__(
        self,
        token_budget: int = 8000,
        max_batch_size: int = 64,
        timeout_ms: int = 100,
        chars_per_token: float = 4.0,
    ): ...
    
    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // int(self.chars_per_token))
```

**Config:**

```yaml
batching:
  mode: token_budget  # or "count" for Phase 1 behavior
  token_budget: 8000
  chars_per_token: 4.0
  max_batch_size: 64
  timeout_ms: 100
```

**Estimated effort:** 3-4 hours

---

### Phase 3: Cross-Worker Coordination (Investigate If Needed)

**Status:** Deferred. Review concluded this is likely overkill for 2-4 workers. Simpler alternative: increase worker count + decrease timeout.

**Trigger:** Only investigate if Phase 1 metrics show workers frequently firing batch_size=1-2 while others are idle.

**If needed, design:**

Opportunistic Redis drain with SETNX lock:

1. Task arrives → worker LPUSHes to `embed:pending`
2. Worker attempts `SETNX embed:lock` with 200ms TTL
3. If acquired: drain list, batch embed, upsert, release
4. If not: return (another worker handles it)

**Complexity:** Requires tracking which task waits for which embedding (Redis pub/sub or polling).

**Simpler alternative first:** Scale workers from 4 to 8, reduce timeout from 100ms to 50ms.

**Estimated effort (if implemented):** 6-8 hours

---

### Phase 4: TEI Embedding Batching

**Trigger:** When TEI (Text Embeddings Inference) becomes primary provider.

**Design:** Same pattern as Phase 1, different parameters:

```python
# TEI: local GPU, no API rate limits
@batched.aio.dynamically(batch_size=64, timeout_ms=50)
async def _batched_embed(texts: list[str]) -> list[list[float]]:
    return await self._raw_embed(texts)
```

**Config:**

```yaml
# When provider: tei
batching:
  enabled: true
  batch_size: 64    # larger, GPU can handle it
  timeout_ms: 50    # shorter, local = lower latency target
```

**Estimated effort:** 1-2 hours

---

## Phase Summary

| Phase | Scope | Trigger | Effort | Status |
|-------|-------|---------|--------|--------|
| **1** | `batched` library, count-based, per-worker, cache+shutdown fixes | Now | 3-4h | Ready |
| **2** | Token-budget batching | Metrics show underutilized batches | 3-4h | Planned |
| **3** | Cross-worker Redis coordination | Workers firing tiny batches | 6-8h | Investigate if needed |
| **4** | TEI batching | TEI becomes primary | 1-2h | Planned |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| `batched` library unmaintained (last release 2023) | Wrap in thin adapter, easy to swap. Monitor for issues. |
| Process isolation limits batching benefit | Instrument actual batch sizes. If median <4, reconsider. |
| Shutdown loses pending embeddings | Graceful shutdown + atexit handler |
| Qdrant partial failure wastes re-embedding | Cache embeddings in Redis before upsert |
| Batch error fails all callers | Taskiq retries individual tasks, embeddings cached |

---

## Success Criteria

**Phase 1 success:**

1. During 1000-node seeding, API call count drops by >50% vs current
2. Median batch size >4 during burst workloads
3. No increase in embedding-related errors
4. p95 embedding latency unchanged or improved

---

## Open Questions

1. Should we proactively increase workers (4→8) alongside Phase 1 to improve batch fill rate?
2. Is the `batched` library's 2023 release date a concern, or is it stable/feature-complete?
3. Should Phase 2 (token budget) be part of Phase 1 given variable text lengths?

---

## References

- [batched PyPI](https://pypi.org/project/batched/)
- [async-batcher GitHub](https://github.com/hussein-awala/async-batcher) (alternative considered)
- [Taskiq Consumer Batching Discussion](https://github.com/orgs/taskiq-python/discussions/406)
- [Python Asyncio for LLM Concurrency](https://www.newline.co/@zaoyang/python-asyncio-for-llm-concurrency-best-practices--bc079176)
