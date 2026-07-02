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

### Structured Output (Native Prompt Engineering)

Use native litellm with embedded schema in prompt. Vertex AI `response_format` modes are unreliable; prompt engineering with JSON parsing is faster and cheaper.

```python
from litellm import acompletion
import json

PROMPT = '''Extract facts as JSON. Output ONLY: {"t":[{"s":"subject","p":"predicate","o":"object"}]}
p must be one of: uses,requires,stores,returns,implements,configures,relates_to
Add "n":true if negated.
Text: '''

async def extract_spo(content: str) -> list[dict]:
    resp = await acompletion(
        model="vertex_ai/gemini-2.5-flash",
        messages=[{"role": "user", "content": PROMPT + content[:600]}],
        temperature=0,
        max_tokens=1000,
    )
    text = resp.choices[0].message.content.strip()
    # Strip markdown code blocks
    if text.startswith("```"):
        text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```"))
    return json.loads(text).get("t", [])
```

Short keys (`s`, `p`, `o`, `n`) reduce output tokens. 99% success rate on benchmark.

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

## Performance Considerations (Verified 2026-07-02)

Tested on benchmark VM with 100 items. Native prompt engineering outperforms Instructor.

### Approach Comparison

| Metric | Instructor | Native (recommended) |
|--------|-----------|---------------------|
| Success rate | 100% | 99% |
| Latency (avg) | 6.8s | 3.9s |
| Latency (p95) | 24.3s | 7.1s |
| Output tokens/item | 1000 | 550 |

### Cost (BEAM 1M scale = 298,820 items)

| Approach | Cost |
|----------|------|
| Instructor | ~$200 |
| Native | ~$100 |

Native is 2x cheaper due to lower output verbosity.

### Throughput

- Items/sec @ 10 concurrency: 2.33
- Time @ 30 concurrency: ~12 hours (native)

### Implementation Notes

- Use native litellm `acompletion()` without `response_format` (Vertex AI json modes unreliable)
- Embed schema in prompt, parse JSON from response
- `max_tokens=1000` required for multi-triple extraction
- Strip markdown code blocks before JSON parse

## Files to Modify

- `src/context_service/llm/spo_extractor.py` — rewrite with native prompt engineering, multi-triple output
- `src/context_service/config/prompts.yaml` — add SPO extraction prompt (prompts live in config, not code)
- `src/context_service/api/v1/batch.py` — integrate extraction into batch/learn
- `src/context_service/config/settings.py` — add model config if not present

## Dependencies

No new dependencies. Uses existing `litellm` for LLM calls.

## Error Handling

Two-tier approach:

1. **Primary**: Native prompt + JSON parse (fast, cheap)
2. **Fallback**: Instructor library retry on parse failure (slower but reliable)

```python
try:
    triples = await extract_spo_native(content)
except json.JSONDecodeError:
    triples = await extract_spo_instructor(content)  # fallback
except Exception:
    triples = []  # store claim without SPO, Custodian backfills later
```

Instructor lib: `instructor>=1.0.0` (add to dev dependencies for fallback path).

Never block ingestion on extraction failure.

## Out of Scope (v2)

- Semantic entity resolution (Qdrant nearest-neighbor for subject matching)
- Semantic object comparison (embed objects, similarity threshold)
- Async extraction queue (if throughput matters)
- Eval dataset (50-item labeled set for accuracy measurement)
- Hot path optimization for single `learn()` calls
