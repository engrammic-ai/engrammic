# TX1 EXTRACT Pipeline Spec

**Status:** Draft (reviewed)  
**Date:** 2026-06-11  
**Depends on:** Phase 8 reactions infrastructure (complete)

---

## Overview

TX1 EXTRACT transforms unstructured Memory content into structured Knowledge (Claims). When an agent stores a long observation via `remember`, the system extracts verifiable propositions and creates Claim nodes linked to the source Memory.

This is the automatic Memory -> Knowledge promotion path.

---

## Trigger

Already wired in `sage/transactions.py`:

```python
IF content.length > EXTRACTION_THRESHOLD:
    ENQUEUE check_extraction_trigger(node_id)
```

Currently `check_extraction_trigger` is notification-only (no handler).

---

## Pipeline Design

### Worker-based (Taskiq)

Extraction is a reaction task, not a Dagster job:
- Triggered by existing event dispatch
- Low latency requirement (extract within seconds of store)
- Per-node granularity, not batch

### Handler: `extract_claims_task`

```python
from primitives.schema.labels import PersistenceLayer
from primitives.schema.edges import CITEEdgeType

# CITE v2 credibility constants
SOURCE_TIER_DERIVED = 0.6  # "community" tier for system-extracted content
METHOD_WEIGHT_EXTRACTOR = 0.75  # standard extractor method weight

@broker.task(task_name=ReactionEventType.CHECK_EXTRACTION_TRIGGER, timeout=30_000)
async def extract_claims_task(node_id: str, silo_id: str, **_payload: Any) -> None:
    """Extract structured claims from Memory content."""
    
    # 1. Fetch source Memory
    memory = await graph_store.get_node(node_id, silo_id)
    if not memory or memory.layer != PersistenceLayer.MEMORY:
        return  # Not a memory node, skip
    
    # 2. Check extraction eligibility
    if len(memory.content) < EXTRACTION_THRESHOLD:
        return  # Too short, skip
    if await _already_extracted(node_id, silo_id):
        return  # Idempotency: already processed
    
    # 3. LLM extraction
    claims = await _extract_claims_llm(memory.content, silo_id)
    
    # 4. Check for duplicates and store each claim
    for claim in claims:
        # Check for existing similar claim (dedup via CORROBORATES)
        existing = await _find_similar_claim(claim.content, silo_id, threshold=0.95)
        
        if existing:
            # Create CORROBORATES edge instead of duplicate
            await graph_store.create_edge(
                from_id=node_id,
                to_id=existing.id,
                edge_type=CITEEdgeType.CORROBORATES,
                silo_id=silo_id,
                metadata={"source": "extraction", "independence": 0.3},  # Low independence (same memory tree)
            )
            continue
        
        # Compute credibility per CITE v2: source_tier * method_weight * raw_confidence
        credibility = SOURCE_TIER_DERIVED * METHOD_WEIGHT_EXTRACTOR * claim.raw_confidence
        
        claim_id = await store_claim_transaction(
            content=claim.content,
            evidence_refs=[f"engrammic://node/{node_id}"],  # Link to source Memory
            silo_id=silo_id,
            agent_id="system:extractor",
            credibility=credibility,  # Scaled credibility, not raw confidence
        )
        
        # 5. Create EXTRACTED_FROM edge (already exists in CITEEdgeType)
        await graph_store.create_edge(
            from_id=claim_id,
            to_id=node_id,
            edge_type=CITEEdgeType.EXTRACTED_FROM,
            silo_id=silo_id,
        )
    
    # 6. Mark Memory as processed
    await _mark_extracted(node_id, silo_id)
```

---

## LLM Extraction

### Prompt Structure

```
Extract verifiable claims from this observation. Each claim should be:
- A single factual proposition
- Independently verifiable
- Not an opinion or speculation

Observation:
{content}

Return JSON array of claims:
[
  {"content": "claim text", "raw_confidence": 0.0-1.0},
  ...
]
```

### Model Selection

Use `llm.completion()` with:
- Primary: configured LLM provider (Gemini/Claude/OpenAI)
- Fallback: local model if configured
- Cost control: use smaller/faster model (this is high-volume)

### Extraction Threshold

```python
EXTRACTION_THRESHOLD = 200  # characters
MAX_CLAIMS_PER_MEMORY = 10  # prevent runaway extraction
```

---

## Credibility Model (CITE v2)

Extracted claims use the two-factor credibility model:

```
credibility = source_tier * method_weight * raw_confidence
```

For extraction:
- `source_tier = 0.6` (community tier - system-derived, not authoritative)
- `method_weight = 0.75` (standard extractor)
- `raw_confidence` = LLM's confidence (0.0-1.0)

This gives extracted claims credibility in range **0.0-0.45**, appropriately below agent-provided claims which use authoritative (1.0) or validated (0.85) tiers.

Confidence is then computed via propagation, not set directly.

---

## Deduplication Strategy

When an extracted claim matches an existing Claim (embedding similarity > 0.95):

1. **Don't create duplicate** - wastes storage, fragments provenance
2. **Create CORROBORATES edge** from source Memory to existing Claim
3. **Weight by independence** - same memory tree = low independence (0.3)

This preserves provenance while avoiding duplicates.

---

## Schema Notes

### EdgeType

`EXTRACTED_FROM` already exists in `primitives.schema.edges.CITEEdgeType`. No addition needed.

### Primitives Gap

`Observation` node type is referenced in brain-transactions but missing from `MemoryLabel`. Either:
- Add `OBSERVATION = "Observation"` to `MemoryLabel`, or
- Document that `remember()` creates `Utterance` nodes

### Node Metadata

Track extraction state on Memory nodes:

```python
extracted_at: datetime | None  # When extraction ran
extraction_version: str | None  # Prompt/model version for re-extraction
```

---

## Idempotency

Extraction must be idempotent:
1. Check `extracted_at` before processing
2. If set and `extraction_version` matches current, skip
3. If version differs, re-extract (allows prompt improvements)

---

## Re-extraction Policy

**Manual trigger via config flag**, not automatic.

Rationale: Automatic re-extraction causes cascading side effects (new claims, potential conflicts, staleness propagation).

Implementation:
```yaml
EXTRACTION_REEXTRACT_BEFORE_VERSION: "v2"  # Re-extract nodes with version < this
```

When set, nodes with `extraction_version < X` are re-extracted on next access or via batch job.

---

## Observability

### Metrics

- `extraction_triggered_total` - Events received
- `extraction_skipped_total{reason}` - Skipped (too short, already done, etc.)
- `extraction_claims_total` - Claims created
- `extraction_corroborates_total` - Dedup via CORROBORATES
- `extraction_latency_seconds` - End-to-end time
- `extraction_llm_cost_usd` - LLM spend (if trackable)

### Structured Logs

```python
logger.info(
    "extraction_complete",
    node_id=node_id,
    claims_extracted=len(claims),
    corroborates_created=corroborate_count,
    content_length=len(content),
    latency_ms=elapsed,
)
```

---

## Configuration

```yaml
# config/extraction.yaml or env vars
EXTRACTION_ENABLED: true
EXTRACTION_THRESHOLD: 200
EXTRACTION_MAX_CLAIMS: 10
EXTRACTION_MODEL: "gemini-1.5-flash"  # Cost-optimized
EXTRACTION_TIMEOUT_MS: 25000
EXTRACTION_REEXTRACT_BEFORE_VERSION: null  # Set to trigger re-extraction
```

---

## Testing

### Unit Tests

1. `test_extract_skips_short_content` - Below threshold
2. `test_extract_creates_claims` - Happy path
3. `test_extract_idempotent` - No duplicate claims
4. `test_extract_links_to_source` - EXTRACTED_FROM edge exists
5. `test_extract_handles_llm_error` - Graceful failure
6. `test_extract_dedup_creates_corroborates` - Existing claim gets CORROBORATES
7. `test_extract_credibility_scaled` - Credibility < 0.45

### Integration Tests

1. `test_remember_triggers_extraction` - End-to-end flow
2. `test_extracted_claims_appear_in_recall` - Searchable

---

## Implementation Tasks

1. [ ] Add `OBSERVATION` to `MemoryLabel` in primitives (or document Utterance usage)
2. [ ] Add `extracted_at`, `extraction_version` to Memory node metadata
3. [ ] Implement `_extract_claims_llm()` with prompt
4. [ ] Implement `_find_similar_claim()` for dedup
5. [ ] Implement `extract_claims_task` handler with credibility scaling
6. [ ] Register handler with broker (remove notification-only comment)
7. [ ] Add config flags
8. [ ] Add metrics/logging
9. [ ] Write tests

---

## Resolved Questions

1. **Re-extraction on prompt change:** Manual trigger via `EXTRACTION_REEXTRACT_BEFORE_VERSION` config flag.

2. **Claim deduplication:** Create CORROBORATES edge to existing claim with low independence weight (0.3). Don't create duplicate.

3. **Confidence passthrough:** Scale via CITE v2 credibility formula: `0.6 * 0.75 * raw_confidence`. Max credibility ~0.45, appropriately below agent-provided claims.

---

## Related

- `context/specs/brain-transactions-pseudocode.md` - TX1 definition
- `context/specs/cite-v2-epistemology.md` - Credibility model
- `src/context_service/reactions/tasks.py` - Other handlers
- `src/context_service/sage/transactions.py` - Dispatch site
- `primitives/src/primitives/schema/edges.py` - CITEEdgeType (EXTRACTED_FROM exists)
