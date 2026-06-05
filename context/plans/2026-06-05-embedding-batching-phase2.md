# Plan: Embedding Batching Phase 2 (Token Budget)

**Spec:** `docs/superpowers/specs/2026-06-05-embedding-batching-design.md`  
**Depends on:** Phase 1 complete + metrics showing underutilized batches  
**Effort:** 3-4 hours  
**Status:** Complete

## Goal

Replace count-based batching with token-budget batching. Instead of "batch up to 32 texts", batch "up to ~8000 tokens worth of text". This maximizes API utilization when text lengths vary significantly.

## Why Token Budget?

Count-based batching has a mismatch problem:

| Scenario | Count-Based | Problem |
|----------|-------------|---------|
| 32 short texts (50 chars each) | 1 batch, 32 texts, ~400 tokens | Wastes 95% of token capacity |
| 32 long texts (2000 chars each) | 1 batch, 32 texts, ~16k tokens | May exceed model limits |
| Mixed lengths | Unpredictable utilization | Inconsistent latency |

Token-budget batching adapts to content:
- Short texts: pack more per batch
- Long texts: fewer per batch, stays within limits
- Mixed: optimal packing automatically

## Prerequisites

- [ ] Phase 1 deployed to dev
- [ ] Metrics show median batch size < 4 OR significant text length variance
- [ ] Review Vertex AI text-embedding-005 token limits (currently ~8192 tokens per text, batch limit TBD)

## Design

### Token Counting via LiteLLM

LiteLLM provides `token_counter()` which:
- Works with Vertex AI embedding models
- Fast: ~0.03ms per text
- Supports batch counting: `token_counter(model, text=[list])`
- Model-aware (uses correct tokenizer internally)

```python
import litellm

def count_tokens(model: str, text: str) -> int:
    """Count tokens using LiteLLM's model-aware tokenizer."""
    return litellm.token_counter(model=model, text=text)

def count_tokens_batch(model: str, texts: list[str]) -> int:
    """Count total tokens for a batch."""
    return litellm.token_counter(model=model, text=texts)
```

No heuristics needed - LiteLLM handles model-specific tokenization.

### Custom Batcher

The `batched` library doesn't support token-budget mode. We'll implement a minimal async batcher using LiteLLM for token counting:

```python
import litellm

class TokenBudgetBatcher:
    """Batches async calls by token count using LiteLLM's tokenizer."""
    
    def __init__(
        self,
        model: str,
        embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
        token_budget: int = 8000,
        max_batch_size: int = 64,
        timeout_ms: int = 100,
    ):
        self._model = model
        self._embed_fn = embed_fn
        self._token_budget = token_budget
        self._max_batch_size = max_batch_size
        self._timeout_s = timeout_ms / 1000
        
        self._pending: list[tuple[str, int, asyncio.Future]] = []  # (text, tokens, future)
        self._current_tokens: int = 0
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
    
    async def embed_single(self, text: str) -> list[float]:
        """Add text to batch, return its embedding when batch completes."""
        tokens = litellm.token_counter(model=self._model, text=text)
        future: asyncio.Future[list[float]] = asyncio.get_event_loop().create_future()
        
        async with self._lock:
            # Would this text push us over budget?
            if self._current_tokens + tokens > self._token_budget or len(self._pending) >= self._max_batch_size:
                await self._flush_locked()
            
            self._pending.append((text, tokens, future))
            self._current_tokens += tokens
            
            # Start timeout if this is first item
            if len(self._pending) == 1:
                self._flush_task = asyncio.create_task(self._flush_after_timeout())
        
        return await future
    
    async def _flush_after_timeout(self) -> None:
        await asyncio.sleep(self._timeout_s)
        async with self._lock:
            if self._pending:
                await self._flush_locked()
    
    async def _flush_locked(self) -> None:
        """Flush pending batch. Caller must hold lock."""
        if not self._pending:
            return
        
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        
        texts = [t for t, _, _ in self._pending]
        futures = [f for _, _, f in self._pending]
        token_count = self._current_tokens
        
        self._pending = []
        self._current_tokens = 0
        
        # Record utilization before flush
        record_embedding_token_utilization(token_count, self._token_budget)
        
        try:
            embeddings = await self._embed_fn(texts)
            for future, embedding in zip(futures, embeddings):
                future.set_result(embedding)
        except Exception as e:
            for future in futures:
                if not future.done():
                    future.set_exception(e)
```

## Tasks

### Task 1: Add TokenBudgetBatcher class (45 min) - DONE

New file: `src/context_service/embeddings/token_budget_batcher.py`

Implement the batcher class with:
- Token estimation
- Budget tracking
- Timeout handling
- Lock-protected flush
- Error propagation to all waiters

### Task 2: Update config schema (10 min) - DONE

File: `config/embeddings.yaml`

```yaml
batching:
  mode: count  # "count" (Phase 1) or "token_budget" (Phase 2)
  # Count mode settings (Phase 1)
  batch_size: 32
  timeout_ms: 100
  small_batch_threshold: 4
  # Token budget mode settings (Phase 2)
  token_budget: 8000
  max_batch_size: 64
  # No chars_per_token needed - LiteLLM handles tokenization
```

### Task 3: Update LiteLLMEmbeddingService (30 min) - DONE

File: `src/context_service/embeddings/litellm_embeddings.py`

3.1 Add mode parameter to `__init__`:
```python
def __init__(
    self,
    # ... existing params ...
    batching_mode: str = "count",  # "count" or "token_budget"
    token_budget: int = 8000,
):
```

3.2 Update `_get_or_create_batched_fn` to branch on mode:
```python
async def _get_or_create_batched_fn(self) -> Any:
    if self._batched_fn is not None:
        return self._batched_fn
    
    async with self._batched_fn_lock:
        if self._batched_fn is not None:
            return self._batched_fn
        
        if self._batching_mode == "token_budget":
            self._batched_fn = TokenBudgetBatcher(
                model=self._model,  # LiteLLM uses this for tokenization
                embed_fn=self._embed_batch,
                token_budget=self._token_budget,
                max_batch_size=self._batch_size,
                timeout_ms=self._timeout_ms,
            )
        else:
            # Existing count-based batching
            @batched.aio.dynamically(...)
            async def _batched_embed(texts: list[str]) -> list[list[float]]:
                return await self._embed_batch(texts)
            self._batched_fn = _batched_embed
        
        return self._batched_fn
```

3.3 Update `embed_single` to handle both interfaces:
```python
async def embed_single(self, text: str) -> list[float]:
    # ... cache check ...
    
    if self._batching_enabled:
        batcher = await self._get_or_create_batched_fn()
        if self._batching_mode == "token_budget":
            vector = await batcher.embed_single(text)
        else:
            results = await batcher([text])
            vector = results[0]
    else:
        vector = (await self._embed_batch([text]))[0]
    
    # ... cache store ...
    return vector
```

3.4 Update `from_config` to load new params.

### Task 4: Add token utilization metrics (20 min) - DONE

File: `src/context_service/telemetry/recorder.py`

```python
def record_embedding_token_utilization(tokens_used: int, budget: int) -> None:
    """Record token budget utilization for batching analysis."""
    if _buffer is None:
        return
    utilization_pct = int((tokens_used / budget) * 100)
    _buffer.record(
        metric_name=f"embedding.token_utilization.{utilization_pct // 10 * 10}",
        silo_id="system",
    )
```

Update `TokenBudgetBatcher._flush_locked` to call this metric.

### Task 5: Unit tests (45 min) - DONE

New file: `tests/test_token_budget_batcher.py`

| Test | Validates |
|------|-----------|
| `test_single_text_returns_embedding` | Basic functionality |
| `test_budget_triggers_flush` | Batch flushes when token budget exceeded |
| `test_max_batch_size_triggers_flush` | Batch flushes at max count |
| `test_timeout_flushes_partial` | Partial batch flushes after timeout |
| `test_concurrent_calls_batched` | Multiple concurrent calls batch together |
| `test_long_text_solo_batch` | Text near budget limit batches alone |
| `test_error_propagates_to_all` | API error fails all waiters |
| `test_litellm_token_counter_used` | Verifies LiteLLM tokenizer is called |

### Task 6: Integration test (20 min) - DONE

Update: `tests/integration/test_batch_embedding_flow.py`

Add test for token-budget mode:
```python
@pytest.mark.integration
async def test_token_budget_batching_efficiency():
    """Mixed-length texts batch efficiently by token count."""
    # 10 short texts (50 chars) + 2 long texts (2000 chars)
    # Count-based: might do 12 texts in 1 batch
    # Token-based: should do ~10 short + 1 long, then 1 long
    ...
```

### Task 7: Update existing tests (15 min) - DONE

Ensure Phase 1 tests still pass with `mode: count` (default).

## Verification

```bash
just check                                    # lint + typecheck
just test -k token_budget                     # new unit tests
just test tests/integration/test_batch_embedding_flow.py  # integration
```

Manual:
1. Set `batching.mode: token_budget` in config
2. Seed 100 nodes with varied text lengths
3. Check logs for token utilization metrics
4. Verify batch sizes adapt to text length

## Files Changed

| File | Change |
|------|--------|
| `src/context_service/embeddings/token_budget_batcher.py` | NEW: TokenBudgetBatcher class |
| `src/context_service/embeddings/litellm_embeddings.py` | Mode branching, new params |
| `config/embeddings.yaml` | Add `mode`, `token_budget` |
| `src/context_service/telemetry/recorder.py` | Token utilization metric |
| `src/context_service/telemetry/metrics.py` | Export new metric |
| `tests/test_token_budget_batcher.py` | NEW: unit tests |
| `tests/integration/test_batch_embedding_flow.py` | Token-budget integration test |

## Success Criteria

- [ ] `just check` passes
- [ ] All new tests pass
- [ ] Existing Phase 1 tests pass with `mode: count`
- [ ] During mixed-length seeding, token utilization >70%
- [ ] No increase in embedding errors

## Risks

| Risk | Mitigation |
|------|------------|
| LiteLLM token_counter slow for some models | Benchmarked at 0.03ms/text; acceptable overhead |
| Custom batcher has bugs | Thorough testing, keep `mode: count` as fallback |
| Flush race conditions | Lock-protected flush, comprehensive concurrency tests |

## Open Questions

1. Should we add a `min_batch_wait_ms` to avoid single-text batches even when budget is full?
2. Should the batcher expose a `close()` for graceful shutdown, or rely on GC?

## Post-Implementation

- [ ] A/B test: count vs token_budget mode on same workload
- [ ] Tune `token_budget` based on observed utilization distribution
- [ ] Consider Phase 3 (cross-worker) if workers still underutilize
