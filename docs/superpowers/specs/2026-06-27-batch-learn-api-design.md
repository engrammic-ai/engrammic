# Batch API Design

Batch endpoints for bulk ingestion, supporting benchmarks (BEAM, AMB) and customer migrations.

## Problem

Current MCP-based seeding: 1 HTTP call per item = 1.5M calls for BEAM 1M. Takes 17+ hours. The "fast seeder" bypasses Engrammic entirely, producing invalid benchmark results.

## Solution

Two-phase implementation:
- **Phase 1:** `POST /api/v1/batch/remember` — Memory layer, simpler (~1 day)
- **Phase 2:** `POST /api/v1/batch/learn` — Knowledge layer with supersession (~2-3 days)

---

# Phase 1: batch/remember

## API Contract

```
POST /api/v1/batch/remember

Headers:
  Authorization: Bearer <token>
  X-Silo-ID: <silo_id>              # optional, defaults to auth-derived

Request:
{
  "items": [
    {
      "content": str,                  // required
      "user_id": str | null,           // stored in metadata, used for filtering
      "timestamp": str | null,         // ISO-8601
      "document_id": str | null,       // external ID for dedup
      "tags": list[str] = [],
      "metadata": dict = {}
    }
  ],
  "options": {
    "conflict_mode": "skip" | "error" = "skip"
  }
}

Response:
{
  "request_id": str,                   // UUID for log correlation
  "created": int,
  "skipped": int,
  "failed": int,
  "results": [
    {"node_id": str, "document_id": str | null, "status": "created" | "skipped"},
    {"error": str, "index": int, "document_id": str | null}
  ],
  "elapsed_ms": float
}

Note: Partial success returns HTTP 200 with failed > 0. Full failure returns 500.
```

## Processing Flow

```
1. Validate auth + silo ownership

2. Dedup check (if document_id provided)
   - Batch query existing document_ids in silo
   - Mark duplicates for skip/error based on conflict_mode

3. Batch embed all non-skipped items
   - Chunked: 64 items per embedding call (TEI limit)
   - Timeout: 30s per chunk (fail chunk, not whole batch)
   - Parallelized (semaphore: 4)
   - Store embeddings alongside items

4. Process items in chunks of 100
   - Call store_memory() with pre-computed embedding
   - Collect results/errors

5. Return aggregated response
```

## Changes to store_memory()

```python
async def store_memory(
    store: HyperGraphStore,
    content: str,
    silo_id: str,
    agent_id: str,
    *,
    # ... existing params ...
    embedding: list[float] | None = None,       # NEW: pre-computed embedding
    document_id: str | None = None,             # NEW: external ID for dedup
) -> MemoryResult:
    """If embedding is provided, skip compute."""
```

## Files to Create/Modify (Phase 1)

1. `src/context_service/api/routes/batch.py` (new)
   - Shared infra: BatchRequest base, chunking, error handling
   - BatchRememberRequest/Response models
   - `/batch/remember` endpoint

2. `src/context_service/services/batch_processor.py` (new)
   - Batch embedding with chunking
   - Dedup checker
   - Chunked graph writer

3. `src/context_service/sage/transactions.py`
   - Add `embedding` param to `store_memory()`
   - Add `document_id` param

4. `src/context_service/engine/graph_store.py`
   - Add `query_document_ids()` for dedup check

---

# Phase 2: batch/learn

Builds on Phase 1 infrastructure, adds:
- Evidence validation
- SPO fields
- Supersession detection
- SAGE bypass

## API Contract

```
POST /api/v1/batch/learn

Headers:
  Authorization: Bearer <token>
  X-Silo-ID: <silo_id>
  X-Bypass-SAGE: true               # internal only, skips custodian/synthesizer
  X-Admin-Override: true            # required for skip_evidence_validation

Request:
{
  "items": [
    {
      // Core (required)
      "content": str,
      "evidence": list[str],           // URIs or node:<id>
      
      // AMB-compatible (from Phase 1)
      "user_id": str | null,
      "timestamp": str | null,
      "document_id": str | null,
      
      // Knowledge-specific
      "confidence": float = 0.8,
      "tags": list[str] = [],
      "source_tier": str | null,       // authoritative|validated|community|unknown
      "subject": str | null,           // SPO for supersession detection
      "predicate": str | null,
      "object": str | null,
      "supersedes": str | null,        // explicit supersession
      "metadata": dict = {}
    }
  ],
  "options": {
    "skip_evidence_validation": bool = false,  // requires X-Admin-Override
    "conflict_mode": "skip" | "supersede" | "error" = "skip"
  }
}

Response:
{
  "request_id": str,
  "created": int,
  "skipped": int,
  "failed": int,
  "results": [
    {"node_id": str, "document_id": str | null, "status": "created" | "skipped"},
    {"error": str, "index": int, "document_id": str | null}
  ],
  "elapsed_ms": float,
  "sage_deferred": bool                // true if X-Bypass-SAGE was set
}
```

## Processing Flow (extends Phase 1)

```
1. Validate auth + silo ownership
   - Check X-Admin-Override if skip_evidence_validation requested

2. Dedup check (reuse Phase 1)

3. Batch embed (reuse Phase 1)

4. Validate evidence (unless skip_evidence_validation)      # NEW
   - Dedupe URIs across items
   - Parallel validation, max 100 concurrent

5. Pre-pass: Auto-detect supersession (FULL REQUEST)        # NEW
   a. Query existing (S, P) pairs from database (paginated, 10k per page)
   b. Build in-memory index: (subject, predicate) -> [items]
   c. Sort by: timestamp -> document_id -> array_index (null sorts LAST)
   d. Later item supersedes earlier if object differs
   e. Handle existing DB nodes per conflict_mode
   - Memory bound: 100k SPO entries max; if exceeded, return 400 error
     (caller should chunk by user_id or conversation_id)

6. Process items in chunks of 100
   - Call store_claim() with pre-computed embedding
   - Skip SAGE triggers if X-Bypass-SAGE set
   - Collect results/errors

7. Return aggregated response
```

## Supersession Detection

**Key behaviors:**
- Intra-batch: items in same batch with same (S,P) are linked (later supersedes earlier)
- Existing DB: items supersede existing nodes with same (S,P) different (O)
- Explicit wins: if `supersedes` field is set, skip auto-detection for that item
- TOCTOU safety: use `ON CONFLICT` at write time to handle concurrent batches

```python
async def detect_supersession(
    items: list[BatchItem],
    silo_id: str,
    conflict_mode: Literal["skip", "supersede", "error"],
) -> None:
    """Pre-pass: detect and set supersedes field for all items.
    
    Mutates items in place. Must run BEFORE chunking.
    """
    # 1. Extract SPO items
    spo_items = [i for i in items if i.subject and i.predicate]
    if not spo_items:
        return
    
    # 2. Query existing (S, P) pairs from DB
    sp_pairs = {(i.subject, i.predicate) for i in spo_items}
    existing = await graph_store.query_spo_pairs(silo_id, sp_pairs)
    
    # 3. Build combined index: existing + new items
    index: dict[tuple[str, str], list[SPOEntry]] = defaultdict(list)
    
    for (s, p), nodes in existing.items():
        for node in nodes:
            index[(s, p)].append(SPOEntry(
                node_id=node["node_id"],
                object=node["object"],
                timestamp=node["timestamp"],
                is_existing=True,
                item=None,
            ))
    
    for item in spo_items:
        index[(item.subject, item.predicate)].append(SPOEntry(
            node_id=None,
            object=item.object,
            timestamp=item.timestamp,
            is_existing=False,
            item=item,
        ))
    
    # 4. Within each (S, P) group, determine supersession
    for (s, p), entries in index.items():
        sorted_entries = sorted(entries, key=lambda e: (
            e.timestamp or "9999-99-99",  # null sorts LAST (oldest)
            e.item.document_id if e.item else "",
            e.item.array_index if e.item else -1,
        ))
        
        for i in range(1, len(sorted_entries)):
            current = sorted_entries[i]
            previous = sorted_entries[i - 1]
            
            if current.is_existing:
                continue
            if current.object == previous.object:
                continue
            
            if previous.is_existing:
                if conflict_mode == "error":
                    current.item.error = f"Existing (S,P) found: {previous.node_id}"
                    continue
                elif conflict_mode == "skip":
                    current.item.skip = True
                    continue
            
            if previous.is_existing:
                current.item.supersedes = previous.node_id
            else:
                current.item.supersedes_document_id = previous.item.document_id
```

## Changes to store_claim() (Phase 2)

```python
async def store_claim(
    store: HyperGraphStore,
    content: str,
    evidence_refs: list[str],
    silo_id: str,
    agent_id: str,
    *,
    embedding: list[float] | None = None,       # from Phase 1 pattern
    skip_sage_triggers: bool = False,           # NEW
    document_id: str | None = None,             # from Phase 1 pattern
) -> tuple[StoreClaimResult, list[ReactionEvent]]:
```

## Additional Files (Phase 2)

5. `src/context_service/services/supersession.py` (new)
   - `detect_supersession()` implementation
   - `query_spo_pairs()` helper

6. `src/context_service/api/routes/_auth.py`
   - Add `require_admin_override()` dependency
   - Add `check_internal_service()` for SAGE bypass

7. `somnus/somnus/memory/engrammic.py` (new)
   - AMB provider implementation

---

# Shared Infrastructure

Built in Phase 1, reused in Phase 2:

| Component | Location | Purpose |
|-----------|----------|---------|
| `BatchProcessor` | `services/batch_processor.py` | Embedding chunking, dedup, graph writes |
| `batch_embed()` | `services/batch_processor.py` | 64-item chunks, semaphore 4, 30s timeout |
| `dedup_check()` | `services/batch_processor.py` | Batch query document_ids |
| `chunked_write()` | `services/batch_processor.py` | 100-item chunks, error collection |
| `BatchRequest` | `api/routes/batch.py` | Base request model |
| `BatchResponse` | `api/routes/batch.py` | Shared response format |

---

# AMB Integration

Maps to Agent Memory Benchmark provider interface:

| AMB Document | batch field |
|--------------|-------------|
| `id` | `document_id` |
| `content` | `content` |
| `user_id` | `user_id` |
| `timestamp` | `timestamp` |
| `messages` | Flattened to items |

Somnus implements `EngrammicProvider(MemoryProvider)`:
- `ingest()` calls `POST /api/v1/batch/learn` (or `/batch/remember` for simple cases)
- `retrieve()` calls existing recall endpoint

---

# Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| Batch embed (1000 items) | < 2s | 64-item chunks, parallel |
| Dedup check (1000 items) | < 500ms | Batch query |
| Evidence validation | SKIP | For benchmarks; ~2h if enabled |
| Supersession pre-pass | < 30s | For 100k SPO entries |
| Graph writes (1000 items) | < 10s | Chunked transactions |
| **batch/remember (1000)** | **< 12s** | No evidence, no supersession |
| **batch/learn (1000)** | **< 15s** | With SAGE bypass |

**BEAM 1M estimate:** ~3-4 hours (with conversation batching)

---

# Rate Limiting

- 10 concurrent requests per silo (semaphore)
- 10,000 items per request max
- 100 req/min per silo (existing decorator)

---

# Security

| Control | Implementation |
|---------|----------------|
| `skip_evidence_validation` | Requires `X-Admin-Override` header |
| `X-Bypass-SAGE` | Internal service accounts only |
| `X-Admin-Override` | Admin role in JWT claims |
| Audit logging | All batch operations logged |

---

# Error Handling

- **Partial success is permanent**: Chunks 1-4 committed, chunk 5 fails = 1-4 stay
- Failed items include `index`, `error`, and `document_id` for retry identification
- Transaction boundary: per graph-write chunk (100 items)
- Abort remaining graph-write chunks if >50% of current chunk fails
- Embedding failures mark items as failed, don't abort batch
- Use `document_id` + `conflict_mode: "skip"` for safe retries

---

# SAGE Catchup (Phase 2)

For bulk imports with `X-Bypass-SAGE`:

```
POST /api/v1/admin/sage/catchup
{
  "silo_id": str,
  "batch_size": int = 1000,
  "max_nodes": int | null
}
```

Processes nodes with `sage_pending: true` through custodian/synthesizer.

---

# Implementation Order

**Phase 1 (~1 day):**
1. `services/batch_processor.py` — shared infra
2. `api/routes/batch.py` — endpoint scaffold
3. `sage/transactions.py` — add embedding param to store_memory
4. `engine/graph_store.py` — query_document_ids
5. Tests + integration test with small dataset

**Phase 2 (~2-3 days):**
1. `services/supersession.py` — detection logic
2. `api/routes/batch.py` — add /batch/learn endpoint
3. `sage/transactions.py` — add params to store_claim
4. `api/routes/_auth.py` — admin override, SAGE bypass
5. `somnus/memory/engrammic.py` — AMB provider
6. Tests + BEAM 100K benchmark run

---

# Out of Scope

- SPO extraction (caller responsibility, use LLM)
- Streaming response
- `conflict_mode: "upsert"` (update in place)
