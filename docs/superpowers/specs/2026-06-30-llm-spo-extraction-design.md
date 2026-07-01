# LLM-Powered SPO Extraction Design

## Goal

Extract meaningful Subject-Predicate-Object triples from content so conflict detection works correctly: same-topic claims share subjects (enabling real contradiction detection) while different topics get different subjects (avoiding garbage contradictions).

## Problem

Current naive extraction uses `{doc_id}_{role}` as subject, which either:
- Creates garbage contradictions (shared subjects across unrelated content)
- Creates zero contradictions (unique subjects per chunk, no overlap)

Real conflict detection requires semantic understanding of what entity a claim is about and what it's asserting.

## Architecture

Single-pass LLM extraction with Instructor + Pydantic for guaranteed structured output:

```
Content → LLM (Instructor + Pydantic) → list[SPOTriple]
```

### Why Single-Pass

Two-pass (extract then normalize) adds latency without benefit — the LLM needs the target vocabulary to extract correctly anyway. Provide predicate vocab and entity hints in one prompt.

### Structured Output with Instructor

Use Instructor library wrapping litellm for reliable structured output:

```python
import instructor
from pydantic import BaseModel, Field
from litellm import completion

class SPOTriple(BaseModel):
    subject: str = Field(description="Entity being described, lowercase, underscore-separated")
    predicate: str = Field(description="One of the canonical predicates")
    object: str = Field(description="Value or target of the predicate")
    is_negated: bool = Field(default=False, description="True if claim negates the relationship")

class ExtractionResult(BaseModel):
    triples: list[SPOTriple] = Field(description="All facts in the content, one triple per fact")

client = instructor.from_litellm(completion)
result = client.chat.completions.create(
    model="gemini/gemini-2.5-flash-preview-05-20",
    response_model=ExtractionResult,
    max_retries=3,  # Auto-retries on ValidationError with error feedback
    messages=[{"role": "user", "content": prompt}],
)
```

Instructor catches Pydantic validation failures, injects the error into a correction prompt, and retries automatically. Tool mode (default) has lower malformation rates than JSON mode.

### Multi-Triple Extraction

A single claim may contain multiple facts:
- "API uses Redis for caching and Postgres for persistence" → 2 triples
- Return `list[SPOTriple]`, not single triple

### Negation Handling

Explicit `is_negated` boolean field:
- "API uses OAuth2" → `is_negated=False`
- "API does NOT use OAuth2" → `is_negated=True`

Conflict detection: same (subject, predicate) with different `is_negated` = contradiction

## Canonical Predicate Vocabulary

~25 verbs covering common claim types. Pydantic validates against this enum:

```python
from enum import Enum

class Predicate(str, Enum):
    # Dependency
    USES = "uses"
    REQUIRES = "requires"
    DEPENDS_ON = "depends_on"
    IMPORTS = "imports"
    # Data
    STORES = "stores"
    RETURNS = "returns"
    CONTAINS = "contains"
    TRANSFORMS = "transforms"
    # Interface
    EXPOSES = "exposes"
    IMPLEMENTS = "implements"
    SUPPORTS = "supports"
    INHERITS_FROM = "inherits_from"
    # Security
    AUTHENTICATES = "authenticates"
    AUTHORIZES = "authorizes"
    VALIDATES = "validates"
    # Lifecycle
    CREATES = "creates"
    DELETES = "deletes"
    ENABLES = "enables"
    DISABLES = "disables"
    # Integration
    CONNECTS_TO = "connects_to"
    TRIGGERS = "triggers"
    PROCESSES = "processes"
    # Config
    CONFIGURES = "configures"
    CACHES = "caches"
    LOGS = "logs"
    LIMITS = "limits"
    # Generic fallback
    RELATES_TO = "relates_to"
```

## Conflict Detection

Conflict fires when:
- Same `subject` (string equality after normalization)
- Same `predicate`
- Different `object` OR different `is_negated`

Examples:
- "API uses OAuth2" vs "API uses BasicAuth" → CONTRADICTS (different object)
- "API uses OAuth2" vs "API does NOT use OAuth2" → CONTRADICTS (different negation)

## Model Selection

- Primary: Gemini 2.5 Flash (`gemini/gemini-2.5-flash-preview-05-20`)
- Fallback: Gemini 3.1 Flash
- Never use: Gemini 2.0 (deprecated, worse quality)

Via litellm with Instructor wrapper.

## Batch API Integration

Inline extraction during `/api/v1/batch/learn`:

```python
async def process_batch_item(item: BatchLearnItem) -> list[ProcessedItem]:
    # If SPO provided, use it; otherwise extract
    if item.subject and item.predicate and item.object:
        triples = [SPOTriple(
            subject=item.subject,
            predicate=item.predicate,
            object=item.object,
            is_negated=item.is_negated or False,
        )]
    else:
        result = await extract_spo(item.content)
        triples = result.triples
    
    # One claim may produce multiple triples
    return [
        ProcessedItem(
            content=item.content,
            subject=t.subject,
            predicate=t.predicate,
            object=t.object,
            is_negated=t.is_negated,
            ...
        )
        for t in triples
    ]
```

Note: Multi-triple extraction means one batch item may produce multiple nodes.

## Subject Normalization

Subjects normalized at extraction time via prompt engineering:
- Lowercase, underscore-separated
- Singular form
- Known entities injected into prompt when available

Entity resolution (Qdrant nearest-neighbor lookup) deferred to v2 — start with string matching, add semantic matching if conflicts miss too many.

## Performance Considerations

### Latency

- Single Gemini Flash call: ~1.0-1.5s (TTFT ~300-500ms + ~50 token generation)
- Instructor retries: up to 3x on validation failure (rare with good schema)
- Sequential extraction would drop throughput from 1.5 → 0.6-1.0 items/sec

### Cost (BEAM 1M scale = 298,820 items)

| Component | Tokens | Rate | Cost |
|-----------|--------|------|------|
| Input | 149.4M (~500/item) | $0.15/1M | $22.41 |
| Output | 14.9M (~50/item) | $0.60/1M | $8.94 |
| **Total** | | | **~$31** |

### Rate Limits (Gemini paid tier)

- QPM: 2,000 (binding constraint)
- TPM: 4M (164M needed / 2.5 hours = ~1.1M TPM avg, well under)

### Throughput with Parallelism

Fan out with `asyncio.Semaphore(30)` to stay under 2K QPM:
- 298,820 items / 33 QPS = ~2.5 hours total
- This is faster than current sequential embedding (~55 hours)

### Verification Needed

These numbers are estimates. Before full BEAM run:
1. Test 100 items to measure actual latency
2. Confirm Gemini rate limits match paid tier
3. Validate Instructor retry rate on real data

## Files to Modify

- `src/context_service/llm/spo_extractor.py` — rewrite with Instructor + Pydantic, multi-triple output
- `src/context_service/llm/schemas.py` — new file for Pydantic models (SPOTriple, ExtractionResult, Predicate enum)
- `src/context_service/api/v1/batch.py` — integrate extraction into batch/learn
- `src/context_service/config/settings.py` — add Gemini model config
- `pyproject.toml` — add `instructor` dependency

## Dependencies

```toml
# pyproject.toml
[project.dependencies]
instructor = ">=1.0.0"
```

## Error Handling

Instructor handles validation retries automatically. For unrecoverable failures:
1. Log warning with claim content
2. Return empty triple list (claim stored without SPO)
3. SAGE Custodian can backfill later

Never block ingestion on extraction failure.

## Out of Scope (v2)

- Semantic entity resolution (Qdrant nearest-neighbor for subject matching)
- Semantic object comparison (embed objects, similarity threshold)
- Async extraction queue (if throughput matters)
- Eval dataset (50-item labeled set for accuracy measurement)
- Hot path optimization for single `learn()` calls
