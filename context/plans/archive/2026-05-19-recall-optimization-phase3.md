# Phase 3: Qdrant Optimizations

**Spec:** [2026-05-19-recall-optimization.md](../specs/2026-05-19-recall-optimization.md)
**Status:** planning
**Priority:** medium
**Depends on:** Phase 1 (embedding cache + TEI)

## Goal

Reduce Qdrant search latency from ~100ms to ~50ms by enabling scalar quantization on existing collections and validating Matryoshka 512-dim query compatibility, with optional sparse vector support for hybrid BM25+dense retrieval.

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/stores/qdrant.py` | Collection creation: add quantization config |
| `src/context_service/engine/qdrant_store.py` | `EngineQdrantStore._ensure_collection`: add quantization to node and cluster collections |
| `src/context_service/config/settings.py` | `QdrantConfig` + `Settings` flat shims: add quantization feature flags |
| `config/settings.yaml` | Default values for new quantization settings |
| `scripts/migrate_qdrant_quantization.py` | One-time online migration: apply quantization to existing collections |
| `tests/stores/test_qdrant_quantization.py` | Unit tests for quantization config and Matryoshka compatibility |

## Tasks

### Task 1: Add Quantization Settings to Config

**Files:**
- `src/context_service/config/settings.py`

**Note:** `config/settings.yaml` does not exist - repo uses flat shims on Settings class only.

**Changes:**

1. Extend `QdrantConfig` in `settings.py` (around line 195):

```python
class QdrantConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    api_key: SecretStr | None = None
    scalar_quantization_enabled: bool = False
    quantization_always_ram: bool = True
```

2. Add flat shims to `Settings` class (around line 850):

```python
qdrant_scalar_quantization_enabled: bool = Field(default=False)
qdrant_quantization_always_ram: bool = Field(default=True)
```

Maps to env vars `QDRANT_SCALAR_QUANTIZATION_ENABLED` and `QDRANT_QUANTIZATION_ALWAYS_RAM`.

**Test:** `tests/stores/test_qdrant_quantization.py::test_quantization_settings_defaults`

**Note:** Create `tests/stores/__init__.py` first - directory may not exist.

- [ ] Add config fields to Settings
- [ ] Create tests/stores/ if needed
- [ ] Write test
- [ ] `uv run just check`

### Task 2: Apply Scalar Quantization in Collection Creation

**Files:**
- `src/context_service/stores/qdrant.py`
- `src/context_service/engine/qdrant_store.py`

**Changes:**

1. Update `QdrantClient.__init__` and `ensure_collection` in `stores/qdrant.py`:

```python
from qdrant_client.models import (
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
)

async def ensure_collection(self, *, hybrid: bool = False) -> None:
    ...
    quant_config = (
        ScalarQuantization(
            scalar=ScalarQuantizationConfig(
                type=ScalarType.INT8,
                always_ram=self._always_ram,
            )
        )
        if self._scalar_quantization
        else None
    )
    await client.create_collection(
        collection_name=self._collection_name,
        vectors_config=...,
        quantization_config=quant_config,
    )
```

2. Wire settings into `QdrantClient.from_settings` - pass through constructor, not post-construction:

```python
@classmethod
def from_settings(cls, settings: Settings) -> QdrantClient:
    ...
    return cls(
        ...,
        scalar_quantization=settings.qdrant_scalar_quantization_enabled,
        always_ram=settings.qdrant_quantization_always_ram,
    )
```

Add `scalar_quantization: bool = False` and `always_ram: bool = True` to `QdrantClient.__init__` parameters.

3. **Clarification:** `EngineQdrantStore` takes a `QdrantClient` instance, not `Settings`. The settings-to-store wiring happens at the `QdrantClient` level. `EngineQdrantStore` will use the quantization config from the `QdrantClient` it receives.

**Test:** `tests/stores/test_qdrant_quantization.py::test_create_collection_with_quantization`

- [ ] Update `stores/qdrant.py`
- [ ] Update `engine/qdrant_store.py`
- [ ] Write test
- [ ] `uv run just check`

### Task 3: Migration Script for Existing Collections

**Files:**
- `scripts/migrate_qdrant_quantization.py`

**Changes:**

Create migration script:

```python
"""Apply scalar quantization to existing Qdrant collections.

Usage:
    uv run python scripts/migrate_qdrant_quantization.py [--dry-run] [--prefix PREFIX]

Targets all collections matching ctx_* and ctx_clusters_* prefixes.
Calls update_collection with ScalarQuantization(INT8, always_ram=True).
Non-destructive: Qdrant rebuilds the quantized index incrementally.
"""
```

Script logic:
1. Connect to Qdrant using `get_settings()` (env-sourced).
2. List all collections matching `ctx_` and `ctx_clusters_` prefixes.
3. For each collection: inspect `collection_info.config.quantization_config`. If INT8 quantization is already present, skip with a log message.
4. Otherwise call `client.update_collection(collection_name=name, quantization_config=ScalarQuantization(...))`.
5. `--dry-run`: list targeted collections and current quantization status without applying changes.
6. `--prefix PREFIX`: scope to collections matching a specific prefix (useful for per-silo runs).
7. Exit non-zero if any update fails.

**Test:** `tests/stores/test_qdrant_quantization.py::test_migration_script_skips_already_quantized`

- [ ] Create migration script
- [ ] Write test
- [ ] `uv run just check`

### Task 4: Matryoshka 512-dim Compatibility Validation

**Files:**
- `src/context_service/stores/qdrant.py`
- `config/embeddings.yaml`
- `tests/stores/test_qdrant_quantization.py`

**Changes:**

1. Add dimension mismatch guard in `QdrantClient.from_settings`. Compare configured embedding dimensions against existing collection's vector size (if collection exists):

```python
# After determining vector_size from embed_config["dimensions"]
# If collection exists, check its declared size
collection_info = await client.get_collection(collection_name)
if collection_info and collection_info.config.params.vectors.size != vector_size:
    logger.warning(
        "qdrant_dimension_mismatch",
        configured=vector_size,
        existing=collection_info.config.params.vectors.size,
        hint="Re-embed all documents before switching Matryoshka dimensions. "
             "See context/specs/2026-05-19-recall-optimization.md Task 4.",
    )
```

2. Add documentation comment to `config/embeddings.yaml`:

```yaml
# IMPORTANT: Switching to Matryoshka 512-dim (Phase 1 of recall optimization)
# requires changing dimensions to 512 AND recreating all Qdrant collections with
# size=512 AND re-embedding all existing documents. See:
# context/specs/2026-05-19-recall-optimization.md
dimensions: 768
```

3. Write dimension mismatch test.

**Test:** `tests/stores/test_qdrant_quantization.py::test_matryoshka_dimension_mismatch_is_detected`

- [ ] Add dimension guard
- [ ] Add documentation comment
- [ ] Write test
- [ ] `uv run just check`

### Task 5: Sparse Vectors for Hybrid BM25+Dense (Optional)

**Files:**
- `tests/stores/test_qdrant_quantization.py`

**Changes:**

1. Write hybrid+quantization integration test to verify that when `hybrid=True` and `scalar_quantization=True`, `create_collection` is called with both `sparse_vectors_config` and `quantization_config`.

2. Confirm SPLADE model config (no code change). Add `# verified 2026-05-19` comment in settings if correct.

**Test:** `tests/stores/test_qdrant_quantization.py::test_hybrid_search_with_quantization`

- [ ] Write integration test
- [ ] Verify SPLADE config
- [ ] `uv run just check`

## Verification

- [ ] `just check` passes (mypy strict + ruff)
- [ ] `just test tests/stores/test_qdrant_quantization.py` passes
- [ ] `uv run python scripts/migrate_qdrant_quantization.py --dry-run` lists collections without error
- [ ] Qdrant search latency measured before/after quantization on staging; target ~50ms p50
- [ ] No regression on Somnus accuracy benchmarks (cosine recall quality)

## Rollout Order

1. Ship Tasks 1-4 with `qdrant_scalar_quantization_enabled=false` (zero behavior change).
2. Run migration script on staging with `--dry-run`, then live.
3. Flip `qdrant_scalar_quantization_enabled=true` on staging; confirm latency and accuracy.
4. Roll to production.
5. Task 5 (sparse + quantization verification) can ship in the same deploy; actual hybrid mode gated separately by `hybrid_search_enabled`.
6. The 512-dim Matryoshka switch (Task 4) is a breaking migration - defer until Phase 1 TEI is confirmed stable in production.

## Risk Notes

- INT8 scalar quantization causes <1% recall quality loss on text embeddings at 768-dim. Measure on Somnus scenarios before production rollout.
- The 512-dim Matryoshka migration is a full re-embed of all documents. Do not conflate with this phase.
- `update_collection` triggers an HNSW+quantization rebuild in the background. Expect a transient RAM spike on large collections; schedule during low-traffic window.

## Success Criteria

- Qdrant search latency: ~50ms p50 (down from ~100ms)
- Storage reduction: ~4x with INT8 quantization
- No regression on Somnus accuracy benchmarks
- `just check` passes
