# Plan: SPLADE Hybrid Retrieval

**Status:** Built, not wired (verified 2026-05-02). All components implemented. Two lines needed to activate at runtime — see Critical Gap below.
**Branch:** `phase-splade`
**Workstream:** v1-β phase 3

## Goal

Add the sparse retrieval channel. Today the engine does dense retrieval via Qdrant only; the v1 wiki page expects hybrid (dense + sparse) ranking. Sparse complements dense on rare-term queries (proper nouns, acronyms) where dense embeddings underperform.

## Why

The repo already references SPLADE in plans but has no implementation. Adding it now (rather than v1.0) keeps the read-path stable for design partners — switching retrieval modes after onboarding would invalidate cached eval results.

## Current state (anchored from audit on 2026-04-28)

- `src/context_service/embeddings/` has Jina + Vertex dense embedders behind a protocol in `base.py`. No sparse embedder.
- `src/context_service/engine/qdrant_store.py` performs dense queries. No sparse-vector handling.
- Qdrant 1.10+ supports both dense and sparse vectors in the same collection (named vectors), with native fusion via the Query API. Confirm Qdrant version pinned in docker config + `pyproject.toml`.
- `src/context_service/services/context.py::query` and `lookup` are the read-path entrypoints; both currently call into `qdrant_store` for vector search.
- MCP tools `context_query` (and `context_get` / `context_graph`) drive the read path.

## Tasks (priority order)

1. **Design pass: model + index strategy.**
   - Pick SPLADE variant. Default recommendation: `naver/splade-v3` or `prithivida/Splade_PP_en_v1` (the latter is smaller and has proven inference latency). Confirm CPU vs GPU at kickoff — if CPU-only is viable for our throughput, the lighter model wins.
   - Decide index strategy. Default recommendation: **Qdrant sparse vectors in the same collection as dense**. Single store, native fusion, no extra operational surface.
   - Document fusion strategy: RRF (reciprocal rank fusion) by default; weighted-sum as a configurable alternative per silo.

2. **`embeddings/splade.py`** — encoder wrapper.
   - Async batch interface matching the existing `EmbeddingService` protocol shape, but returning `dict[int, float]` (sparse vectors) instead of `list[float]`.
   - Lazy model loading (don't load at import; load on first `embed_batch` call).
   - Configurable backend: local Transformers vs hosted endpoint (e.g. via Vertex AI custom container). Default local for dev; hosted for prod.

3. **Qdrant collection schema migration.**
   - Update `engine/qdrant_store.py::ensure_collection` to declare both dense and sparse named vectors in the collection config.
   - Migration script `scripts/migrate_qdrant_sparse.py` — for existing collections without sparse vectors, run a backfill: scan existing dense-vector points, re-encode their content via SPLADE, upsert the sparse vector alongside. Same shape as `migrate_belongs_to.py`.

4. **Read-path hybrid fusion.**
   - Extend `engine/qdrant_store.py::query` to accept a `search_mode: Literal["hybrid", "dense", "sparse"]` parameter. For "hybrid", build a Qdrant Query with `prefetch=[dense_query, sparse_query]` and `query=Fusion(fusion=FusionMethod.RRF)`.
   - Default `search_mode="hybrid"` on production silos; allow per-silo override via `Settings`.

5. **MCP `context_query` `search_mode` param.**
   - Edit `src/context_service/mcp/tools/context_query.py` to accept and pass through `search_mode`. Default "hybrid".
   - Update `models/mcp.py` if there's a request model.

6. **Write-path: emit both dense and sparse on every store.**
   - Edit `services/context.py::store` (the embedding upsert block at lines 124-137) to call both dense and sparse encoders, upsert both named vectors.
   - Embedding cache (in `cache/`) extended to cache both — separate keys per modality.

7. **Backfill script** (`scripts/backfill_splade.py`).
   - Scan all silos / nodes that have a dense vector but no sparse vector. Encode + upsert. Idempotent. CLI shape mirrors `migrate_belongs_to.py`: `--silo-id`, `--all-silos`, `--dry-run`, `--verify`.

8. **Tests.**
   - `tests/test_splade_encoder.py` — unit. Pass synthetic text, assert sparse-vector dict shape.
   - `tests/integration/test_hybrid_retrieval.py` — seed a corpus with 5+ docs containing rare-term queries (proper nouns, acronyms), run dense-only and hybrid queries, assert hybrid recall on rare-term queries is ≥ dense-only recall.

## Out of scope

- Re-ranker on top of hybrid (cross-encoder, ColBERT-style). Defer to v1.0.
- Per-query learned fusion weights (simple RRF + configurable static weights only).
- Late-interaction models.
- Adapting to query intent (no query-classification → mode-switching).

## Critical gap (2026-05-02 audit)

All tasks 1–8 are complete. The feature is not running because `SpladeEncoder` is never
instantiated and `ContextService` never receives it. Two fixes required:

1. `mcp/server.py` — instantiate `SpladeEncoder` when `settings.hybrid_search_enabled` and pass
   as `splade=` to `ContextService(...)`.
2. `api/app.py` — pass `hybrid=settings.hybrid_search_enabled` to
   `qdrant_client.ensure_collection()` so sparse vector config is provisioned.

Once these land, the done criteria below are satisfied.

## Done criteria

- `context_query` returns hybrid-ranked results by default.
- New embeddings written via the pipeline (β2) carry both dense and sparse vectors.
- Backfill script exists, is idempotent, and documented.
- Hybrid retrieval integration test passes; recall improvement on rare-term queries demonstrable.
- `just check` + `just test` green.
