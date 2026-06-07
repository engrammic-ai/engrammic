# Retrieval Quality Improvements Needed - 2026-06-07

## Context

Somnus benchmark testing revealed retrieval quality issues. With proper seeding, with_engrammic achieves 60% vs 80% baseline on LoCoMo. The 20-point gap appears to be retrieval relevance.

## Evidence

From Somnus debug output:
- Recall returns 20 results ✓
- **Relevance scores are low (0.15)** when they should be higher
- Agent uses recall but gets wrong facts back

## Investigation Areas

### 1. Embedding Quality for Conversational Text
Current embeddings may not capture conversational semantics well.
- Test: Compare embedding similarity for known-related chunks
- Consider: Fine-tuned embeddings for conversational memory

### 2. Reranking Effectiveness  
The reranking fix was deployed but gap remains.
- Verify reranking is active and working
- Check if reranker model is appropriate for conversational QA
- Consider: Cross-encoder reranking for better precision

### 3. Query Expansion
Single-query retrieval may miss relevant content.
- Consider: HyDE (Hypothetical Document Embeddings)
- Consider: Query rewriting/expansion before search

### 4. Chunking Recommendations
Somnus currently chunks consecutive turns. Better strategies:
- Semantic chunking (by topic/entity)
- Overlapping chunks
- Hierarchical (summary + detail)

### 5. include_content Parameter
Verified `recall` now accepts `include_content=True` and returns full content.
Working correctly as of this investigation.

## Metrics to Track

- Retrieval precision@k for known questions
- Relevance score distribution
- Success rate by question type (factual vs temporal vs reasoning)

## Related

- Somnus investigation: `somnus/context/notes/2026-06-07-recall-accuracy-investigation.md`
- mem0 reports ~90% on LoCoMo - investigate their approach
