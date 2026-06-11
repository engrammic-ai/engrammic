# Plan: LongMemEval-V2 Optimal Implementation

**Goal:** Hit 50%+ accuracy on web-small (240 questions)  
**Baseline:** 19.2% (broken), original 31.7%, RAG baseline 42.8%, RAG+notes 51%  
**Approach:** Mirror RAG+notes architecture via Engrammic API  
**Effort:** ~2 hours

## Architecture

```
Trajectory -> [Notes Extractor] -> procedure_note + hint_note
           -> [Raw Chunker]     -> clean a11y chunks (no headers)
                                      |
                                      v
                              Engrammic /remember
                                      |
Query -----------------------> Engrammic /recall (top_k=50)
                                      |
                                      v
                              [Local Reranker] -> top 20
                                      |
                                      v
                                  Results
```

## Tasks

### Task 1: Clean Raw Content (30 min)

Revert header pollution. Store raw a11y tree chunks only.

**File:** `../longmemeval-harness/memory_modules/engrammic.py`

Changes to `insert()`:
- Remove header construction (lines 115-126)
- Content = raw chunk only
- Keep tags for metadata (trajectory, state, domain)
- Increase chunk size back to 4KB

```python
# Before (broken)
content = "\n".join(header_lines) + "\n" + chunk

# After (clean)
content = chunk  # raw a11y tree only
```

### Task 2: Notes Extraction (45 min)

Add LLM-based notes extraction matching RAG baseline approach.

**File:** `../longmemeval-harness/memory_modules/engrammic.py`

Add async OpenAI client for notes generation:
```python
from openai import OpenAI

NOTE_PROMPT = """You convert one UI task trajectory into two reusable memory notes.

Write:
1. procedure_note - workflow steps (4-8 bullets)
2. hint_note - key facts from pages (6-12 bullets)

Each note: {title, description, content}
- title: retrieval-friendly with app/task context
- description: 1 sentence
- content: bullet list with '- ' lines

Rules:
- Ground in evidence from goal, actions, accessibility trees
- Use exact UI strings (buttons, labels, menus)
- If failed, describe attempted workflow and gotchas
- No screenshot/state numbers

Return JSON only: {"procedure_note":{...},"hint_note":{...}}"""
```

New method `_extract_notes()`:
- Input: trajectory dict (goal, states with actions + a11y trees)
- Build prompt with trajectory summary
- Call LLM (gemini-2.5-flash via litellm proxy)
- Parse JSON response
- Store as two separate memories with tags `type:procedure_note` and `type:hint_note`

### Task 3: Hybrid Retrieval (30 min)

Query returns both raw chunks AND notes.

**File:** `../longmemeval-harness/memory_modules/engrammic.py`

Changes to `query()`:
- Fetch top_k=50 from Engrammic
- Notes naturally float up due to higher semantic density
- No explicit filtering needed (Engrammic handles relevance)

### Task 4: Local Reranking (15 min)

Add cross-encoder reranking for precision.

**File:** `../longmemeval-harness/memory_modules/engrammic.py`

```python
from sentence_transformers import CrossEncoder

class EngrammicMemory(Memory):
    def __init__(self, ...):
        ...
        self.reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    
    def _rerank(self, query: str, docs: list[str], top_k: int = 20) -> list[str]:
        if len(docs) <= top_k:
            return docs
        pairs = [(query, d) for d in docs]
        scores = self.reranker.predict(pairs)
        ranked = sorted(zip(docs, scores), key=lambda x: -x[1])
        return [d for d, _ in ranked[:top_k]]
```

Changes to `query()`:
- After recall, extract content strings
- Rerank with cross-encoder
- Return top 20

## Implementation Order

1. **Task 1** - Clean content (fixes regression, gets us to ~35-40%)
2. **Task 2** - Notes extraction (biggest win, targets 50%+)
3. **Task 4** - Reranking (polish, +5-10%)
4. **Task 3** - Verify hybrid works (should be automatic)

## Subagent Dispatch

Three parallel Sonnet agents:

1. **clean-content** - Task 1: revert headers, increase chunk size
2. **notes-extractor** - Task 2: add notes extraction with LLM
3. **reranker** - Task 4: add cross-encoder reranking

After all complete, integration test on devbox.

## Validation

```bash
ssh engrammic-dev-box "cd ~/benchmarks && ./run_engrammic_eval.sh"
```

Target metrics:
- Overall accuracy: 50%+ (vs 19.2% current, 42.8% RAG baseline)
- Recall latency: <2s p95
- Memory build time: <15 min (100 trajectories)

## Dependencies

Need to install on devbox:
```bash
pip install sentence-transformers
```

## Risks

1. **Notes extraction cost** - 100 LLM calls during insert
   - Mitigation: gemini-2.5-flash is fast, parallelize
   
2. **Reranker model download** - first run pulls ~100MB model
   - Mitigation: one-time cost, cached after

3. **Memory pressure** - cross-encoder + embedding model in memory
   - Mitigation: devbox has 32GB RAM, should be fine
