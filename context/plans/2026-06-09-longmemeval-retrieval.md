# Plan: LongMemEval-V2 Retrieval Improvements

**Context:** Benchmark harness at `../longmemeval-harness/`  
**Baseline:** 31.7% accuracy (web-small, 240 questions)  
**Target:** 50-60% accuracy (match RAG+notes baseline)  
**Effort:** ~1 day  
**Status:** Ready to execute

## Problem

Engrammic scores 31.7% on LongMemEval-V2 web-small tier, below basic RAG (42.8%). Root causes:

1. **Naive chunking** - fixed 4KB splits ignore DOM structure
2. **No metadata filtering** - can't narrow by trajectory/URL
3. **No notes extraction** - missing goal/action/outcome summaries
4. **No reranking** - returning raw embedding similarity results

## Industry Baselines (web-small)

| Method | Accuracy |
|--------|----------|
| No retrieval | 1.3% |
| RAG: query to slice | 42.8% |
| RAG: query to slice + notes | 51.0% |
| AgentRunbook-R | 58.6% |
| Codex | 69.9% |
| AgentRunbook-C | 74.9% |

## Tasks

### Phase 1: Metadata + Filtering (2 hrs)

**1.1 Add structured tags to memories**

File: `../longmemeval-harness/memory_modules/engrammic.py`

Update `insert()` to include:
```python
tags = [
    f"trajectory:{trajectory_id}",
    f"state:{state_idx}",
    f"url:{urlparse(url).netloc}",
]
if goal:
    tags.append(f"goal:{goal[:50]}")
```

**1.2 Add metadata to content header**

Include trajectory context in each chunk:
```
Trajectory: {id} | State: {idx}/{total} | URL: {url}
Goal: {goal}
---
{chunk_content}
```

**1.3 Verify recall uses tag filtering**

Check that recall query can filter by trajectory or URL domain.

### Phase 2: Semantic DOM Chunking (3 hrs)

**2.1 Create DOM-aware chunker**

File: `../longmemeval-harness/memory_modules/engrammic.py`

New function:
```python
def chunk_accessibility_tree(a11y_tree: str, max_size: int = 4000) -> list[dict]:
    """Split accessibility tree at semantic boundaries.
    
    Boundaries (in priority order):
    1. Landmark roles: main, navigation, banner, contentinfo
    2. Headings: h1-h6
    3. Sections: article, section, form
    4. Lists: list with >5 items
    
    Returns list of {content: str, context: str} where context
    is the breadcrumb path to this chunk.
    """
```

**2.2 Preserve parent context**

Each chunk includes breadcrumb of containing landmarks:
```
[navigation > list] 
StaticText "Home"
link "Dashboard"
...
```

**2.3 Update insert() to use semantic chunker**

Replace `chunk_text()` with `chunk_accessibility_tree()`.

### Phase 3: Notes Extraction (3 hrs)

**3.1 Add trajectory summarizer**

File: `../longmemeval-harness/memory_modules/engrammic.py`

New function using reader model:
```python
async def extract_trajectory_notes(
    trajectory: dict,
    llm_client: AsyncOpenAI,
) -> str:
    """Extract structured notes from trajectory.
    
    Returns:
        Goal: {what the agent was trying to do}
        Actions: {key actions taken, in order}
        Outcome: {what happened, success/failure}
        Gotchas: {any unexpected behaviors or errors}
    """
```

**3.2 Store notes as separate memories**

For each trajectory, create one "notes" memory:
```python
self._post("/api/v1/remember", {
    "content": notes,
    "tags": [f"trajectory:{id}", "type:notes"],
})
```

**3.3 Link notes to state chunks**

Use `link` API to connect notes to their state chunks.

### Phase 4: Reranking (1 hr)

**4.1 Increase initial recall count**

Update `recall()` to fetch `top_k=50` instead of 20.

**4.2 Wire reranker**

Option A: Use Engrammic's built-in reranker (if exposed via API)
Option B: Add local reranker in harness using `sentence-transformers`

```python
def rerank(query: str, docs: list[str], top_k: int = 20) -> list[str]:
    from sentence_transformers import CrossEncoder
    model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    scores = model.predict([(query, d) for d in docs])
    ranked = sorted(zip(docs, scores), key=lambda x: -x[1])
    return [d for d, _ in ranked[:top_k]]
```

## Validation

After each phase, re-run benchmark:
```bash
ssh engrammic-dev-box "cd ~/benchmarks && ./run_engrammic_eval.sh"
```

Track accuracy progression:
- Phase 1: expect ~35-38%
- Phase 2: expect ~40-45%
- Phase 3: expect ~48-52%
- Phase 4: expect ~52-58%

## Files Changed

| File | Change |
|------|--------|
| `../longmemeval-harness/memory_modules/engrammic.py` | All phases |
| `../longmemeval-harness/evaluation/memory_configs/engrammic.json` | Add reranker config |

## Risks

1. **Notes extraction cost** - LLM call per trajectory adds latency/cost
   - Mitigation: cache notes, only extract once per trajectory

2. **Reranker latency** - cross-encoder adds ~100ms per query
   - Mitigation: acceptable for benchmark, optimize later

3. **DOM parsing edge cases** - accessibility trees vary by site
   - Mitigation: fallback to fixed chunking if semantic parse fails

## Future Work (post-benchmark)

- Port improvements back to context-service recall
- Add trajectory-level indexing to SAGE pipeline
- Structured knowledge pools (AgentRunbook-R approach)
