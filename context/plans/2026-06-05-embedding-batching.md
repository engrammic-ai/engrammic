# Plan: Embedding Batching (Phase 1)

**Spec:** `docs/superpowers/specs/2026-06-05-embedding-batching-design.md`  
**Effort:** 3-4 hours  
**Status:** Ready to execute

## Goal

Batch multiple `embed_single()` calls into single Vertex AI API calls using the `batched` library. Target: >50% reduction in API calls during burst operations.

## Prerequisites

- [ ] Confirm `batched` library is compatible with Python 3.12+
- [ ] Review `batched` library shutdown behavior

## Tasks

### Task 1: Add dependency (5 min)

File: `pyproject.toml`

```toml
dependencies = [
    # ... existing ...
    "batched>=0.2.0",
]
```

Run: `uv sync`

### Task 2: Update embeddings config (10 min)

File: `config/embeddings.yaml`

Add:
```yaml
# Batching config
batching:
  enabled: true
  batch_size: 32
  timeout_ms: 100
  small_batch_threshold: 4
```

### Task 3: Add batching config to settings (15 min)

File: `src/context_service/config/settings.py`

Add dataclass:
```python
@dataclass
class EmbeddingBatchingConfig:
    enabled: bool = True
    batch_size: int = 32
    timeout_ms: int = 100
    small_batch_threshold: int = 4
```

Update `ModelRateLimitConfig` or create parallel config loading in `config_loader.py`.

### Task 4: Implement batching wrapper (45 min)

File: `src/context_service/embeddings/litellm_embeddings.py`

4.1 Add module-level batched function holder:
```python
import batched

_batched_embed_fn = None

def _get_batched_embed(embed_batch_fn, batch_size: int, timeout_ms: int, small_batch_threshold: int):
    global _batched_embed_fn
    if _batched_embed_fn is None:
        @batched.aio.dynamically(
            batch_size=batch_size,
            timeout_ms=timeout_ms,
            small_batch_threshold=small_batch_threshold,
        )
        async def _batched_embed(texts: list[str]) -> list[list[float]]:
            return await embed_batch_fn(texts)
        _batched_embed_fn = _batched_embed
    return _batched_embed_fn
```

4.2 Update `__init__` to accept batching params:
```python
def __init__(
    self,
    model: str,
    dimensions: int = 768,
    max_input_chars: int = 30000,
    rate_limit: ModelRateLimitConfig | None = None,
    _embedding_cache: EmbeddingCache | None = None,
    batching_enabled: bool = True,
    batch_size: int = 32,
    timeout_ms: int = 100,
    small_batch_threshold: int = 4,
) -> None:
    # ... existing ...
    self._batching_enabled = batching_enabled
    self._batch_size = batch_size
    self._timeout_ms = timeout_ms
    self._small_batch_threshold = small_batch_threshold
```

4.3 Update `embed_single`:
```python
async def embed_single(self, text: str) -> list[float]:
    if self._batching_enabled:
        batched_fn = _get_batched_embed(
            self._embed_batch, 
            self._batch_size, 
            self._timeout_ms, 
            self._small_batch_threshold
        )
        results = await batched_fn([text])
        return results[0]
    return (await self._embed_batch([text]))[0]
```

4.4 Update `from_config`:
```python
@classmethod
def from_config(cls, _embedding_cache: EmbeddingCache | None = None) -> LiteLLMEmbeddingService:
    config = load_config("embeddings")
    rate_limit_dict = config.get("rate_limit", {})
    rate_limit = ModelRateLimitConfig(**rate_limit_dict)
    
    batching = config.get("batching", {})
    
    return cls(
        model=config["model"],
        dimensions=config["dimensions"],
        max_input_chars=config.get("max_input_chars", 30000),
        rate_limit=rate_limit,
        _embedding_cache=_embedding_cache,
        batching_enabled=batching.get("enabled", True),
        batch_size=batching.get("batch_size", 32),
        timeout_ms=batching.get("timeout_ms", 100),
        small_batch_threshold=batching.get("small_batch_threshold", 4),
    )
```

### Task 5: Add observability metrics (30 min)

File: `src/context_service/telemetry/metrics.py`

Add:
```python
embedding_batch_size = Histogram(
    "embedding_batch_size",
    "Number of texts per embedding batch",
    buckets=[1, 2, 4, 8, 16, 32, 64],
)

embedding_batch_trigger = Counter(
    "embedding_batch_trigger",
    "How batches were triggered",
    ["trigger"],  # timeout, full, threshold
)
```

File: `src/context_service/embeddings/litellm_embeddings.py`

Update `_embed_batch` to record metrics:
```python
async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
    record_embedding_batch_size(len(texts))
    # ... existing code ...
```

### Task 6: Unit tests (45 min)

New file: `tests/test_embedding_batching.py`

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from context_service.embeddings.litellm_embeddings import LiteLLMEmbeddingService


@pytest.fixture
def mock_litellm():
    with patch("context_service.embeddings.litellm_embeddings.litellm") as mock:
        mock.aembedding = AsyncMock(return_value=MockResponse([...]))
        yield mock


class TestEmbeddingBatching:
    async def test_single_text_batched(self, mock_litellm):
        """Single call works and returns correct vector."""
        service = LiteLLMEmbeddingService(model="test", batching_enabled=True)
        result = await service.embed_single("test text")
        assert len(result) == 768

    async def test_multiple_concurrent_batched(self, mock_litellm):
        """N concurrent calls result in 1 API call."""
        service = LiteLLMEmbeddingService(
            model="test", 
            batching_enabled=True,
            batch_size=10,
            timeout_ms=100,
        )
        
        # Fire 5 concurrent embed_single calls
        results = await asyncio.gather(*[
            service.embed_single(f"text {i}") for i in range(5)
        ])
        
        # Should have made 1 API call with 5 texts
        assert mock_litellm.aembedding.call_count == 1
        assert len(mock_litellm.aembedding.call_args[1]["input"]) == 5

    async def test_timeout_fires_partial_batch(self, mock_litellm):
        """After timeout, partial batch fires."""
        service = LiteLLMEmbeddingService(
            model="test",
            batching_enabled=True,
            batch_size=32,
            timeout_ms=50,
        )
        
        result = await service.embed_single("single text")
        assert result is not None
        # Waited ~50ms then fired with 1 text

    async def test_batching_disabled_fallback(self, mock_litellm):
        """enabled=false bypasses batching."""
        service = LiteLLMEmbeddingService(model="test", batching_enabled=False)
        
        await asyncio.gather(*[
            service.embed_single(f"text {i}") for i in range(3)
        ])
        
        # Should have made 3 separate API calls
        assert mock_litellm.aembedding.call_count == 3

    async def test_error_propagates_to_all_callers(self, mock_litellm):
        """API error fails all tasks in batch."""
        mock_litellm.aembedding.side_effect = Exception("API error")
        service = LiteLLMEmbeddingService(
            model="test",
            batching_enabled=True,
            batch_size=10,
            timeout_ms=100,
        )
        
        with pytest.raises(Exception):
            await asyncio.gather(*[
                service.embed_single(f"text {i}") for i in range(3)
            ])
```

### Task 7: Integration test (30 min)

New file: `tests/integration/test_batch_embedding_flow.py`

```python
import pytest
from unittest.mock import AsyncMock, patch

from context_service.reactions.events import ReactionEvent, ReactionEventType, emit_reaction


@pytest.mark.integration
async def test_batch_embedding_reduces_api_calls():
    """Emit 20 COMPUTE_EMBEDDING events, verify fewer than 20 API calls."""
    api_call_count = 0
    
    async def mock_aembedding(**kwargs):
        nonlocal api_call_count
        api_call_count += 1
        texts = kwargs["input"]
        return MockResponse([[0.1] * 768 for _ in texts])
    
    with patch("litellm.aembedding", mock_aembedding):
        # Emit 20 embedding events rapidly
        events = [
            ReactionEvent(
                event_type=ReactionEventType.COMPUTE_EMBEDDING,
                node_id=f"node-{i}",
                silo_id="test-silo",
            )
            for i in range(20)
        ]
        
        for event in events:
            await emit_reaction(event)
        
        # Wait for processing
        await asyncio.sleep(0.5)
        
        # Should have made fewer than 20 API calls
        assert api_call_count < 20
        assert api_call_count >= 1
```

## Verification

```bash
just check                           # lint + typecheck
just test -k embedding_batch         # batching unit tests
just test tests/integration/test_batch_embedding_flow.py  # integration
```

Manual verification:
1. Start local stack: `just up`
2. Start worker: `just worker`
3. Seed 100 nodes rapidly via MCP
4. Check logs for `embedding_batch_fired` with `batch_size > 1`
5. Check metrics: `embedding_batch_size` histogram shows batches

## Files Changed

| File | Change |
|------|--------|
| `pyproject.toml` | Add `batched` dependency |
| `config/embeddings.yaml` | Add `batching` section |
| `src/context_service/embeddings/litellm_embeddings.py` | Batching wrapper, new params |
| `src/context_service/telemetry/metrics.py` | Batch size histogram, trigger counter |
| `tests/test_embedding_batching.py` | NEW: unit tests |
| `tests/integration/test_batch_embedding_flow.py` | NEW: integration test |

## Success Criteria

- [ ] `just check` passes
- [ ] All new tests pass
- [ ] During 100-node seeding, API call count < 50 (vs 100 without batching)
- [ ] Metrics show batch sizes > 1 during bursts

## Post-Implementation

- [ ] Deploy to dev, run benchmark seeding
- [ ] Verify batch size distribution in metrics
- [ ] If median batch size < 4, consider Phase 2 (token-budget) or more workers
- [ ] Update beta worker count from 2 to 4 if batching effective
