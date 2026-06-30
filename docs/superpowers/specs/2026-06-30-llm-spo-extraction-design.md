# LLM-Powered SPO Extraction Design

## Goal

Extract meaningful Subject-Predicate-Object triples from content so conflict detection works correctly: same-topic claims share subjects (enabling real contradiction detection) while different topics get different subjects (avoiding garbage contradictions).

## Problem

Current naive extraction uses `{doc_id}_{role}` as subject, which either:
- Creates garbage contradictions (shared subjects across unrelated content)
- Creates zero contradictions (unique subjects per chunk, no overlap)

Real conflict detection requires semantic understanding of what entity a claim is about and what it's asserting.

## Architecture

Two-pass LLM extraction via extended `spo_extractor.py`:

```
Content → Pass 1 (raw extraction) → Pass 2 (normalization) → (entity_id, canonical_predicate, object)
```

### Pass 1: Raw Extraction

Extract raw triple from content using structured output:

```json
{
  "subject_raw": "the API",
  "predicate_raw": "uses",
  "object_raw": "OAuth2 with PKCE"
}
```

Prompt pattern:
- Chain-of-thought: "First identify the main entity being discussed, then what is being claimed about it"
- Few-shot examples showing extraction from conversational text
- Instruction to use singular lowercase for subjects

### Pass 2: Normalization

Normalize against existing graph state:

1. **Subject resolution**: 
   - Query Memgraph for existing entities with fuzzy match on subject_raw
   - If no match, embed subject_raw and find nearest neighbor in Qdrant entity index
   - If still no match (similarity < threshold), create new canonical entity
   - Return entity_id

2. **Predicate normalization**:
   - Map predicate_raw to canonical vocabulary via LLM
   - Closed set prevents drift

3. **Object normalization**:
   - Lowercase, strip whitespace
   - Keep as free text for conflict diffing

Output: `(entity_id, canonical_predicate, normalized_object)`

## Canonical Predicate Vocabulary

~25 verbs covering common claim types:

| Category | Predicates |
|----------|------------|
| Dependency | `uses`, `requires`, `depends_on`, `imports` |
| Data | `stores`, `returns`, `contains`, `transforms` |
| Interface | `exposes`, `implements`, `supports`, `inherits_from` |
| Security | `authenticates`, `authorizes`, `validates` |
| Lifecycle | `creates`, `deletes`, `enables`, `disables` |
| Integration | `connects_to`, `triggers`, `processes` |
| Config | `configures`, `caches`, `logs`, `limits` |

## Conflict Detection

Conflict fires when:
- Same `entity_id`
- Same `canonical_predicate`  
- Different `normalized_object`

Object comparison is string equality, not semantic. Flag as CONTRADICTS and let conflict resolver (human or Custodian) decide winner.

## Model Selection

- Primary: Gemini 2.5 Flash (`gemini-2.5-flash-preview-05-20` or latest)
- Fallback: Gemini 3.1 Flash
- Never use: Gemini 2.0 (deprecated, worse quality)

Both passes can use the same model. Second pass is cheaper (shorter prompt, structured output).

## Batch API Integration

Inline extraction during `/api/v1/batch/learn`:

```python
async def process_batch_item(item: BatchLearnItem) -> ProcessedItem:
    # If SPO provided, use it; otherwise extract
    if item.subject and item.predicate and item.object:
        spo = (item.subject, item.predicate, item.object)
    else:
        spo = await extract_and_normalize_spo(item.content)
    
    return ProcessedItem(
        content=item.content,
        subject=spo[0],
        predicate=spo[1],
        object=spo[2],
        ...
    )
```

This keeps the API simple — callers can provide pre-extracted SPO or let the server extract.

## Entity Index

New Qdrant collection for entity embeddings:

- Collection: `entities_{silo_id}`
- Vectors: embedded canonical entity names
- Payload: `{entity_id, canonical_name, aliases[]}`

Used for subject resolution in Pass 2. Updated when new entities are created.

## Performance Considerations

- Pass 1 + Pass 2: ~200-400ms total with Gemini Flash
- Entity lookup: ~50ms (Qdrant nearest neighbor)
- Batch extraction can parallelize across items

For benchmark seeding at 1.5 items/sec current rate, extraction adds ~300ms/item overhead. Acceptable for correctness. Can optimize later with batched LLM calls if needed.

## Files to Modify

- `src/context_service/llm/spo_extractor.py` — extend with two-pass logic
- `src/context_service/engine/entity_index.py` — new file for entity resolution
- `src/context_service/api/v1/batch.py` — integrate extraction into batch/learn
- `src/context_service/config/settings.py` — add Gemini model config

## Out of Scope

- Semantic object comparison (future: embed objects, similarity threshold)
- Async extraction queue (future: if throughput matters)
- Entity merging UI (future: manual entity resolution)
