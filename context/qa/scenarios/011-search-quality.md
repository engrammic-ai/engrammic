# Scenario: Search Quality

## Metadata

- **ID:** 011
- **Agents:** 2
- **Duration:** ~5 min
- **Silo:** (default)

## Setup

None

## Instructions

### Worker 1: Content Seeder

1. Store 3 highly relevant documents about machine learning:
   ```
   mcp__engrammic__context_store(
       layer="memory",
       content="Neural networks use backpropagation to adjust weights during training, minimizing loss functions through gradient descent",
       tags=["ml", "relevant"],
       confidence=0.9
   )
   
   mcp__engrammic__context_store(
       layer="memory", 
       content="Deep learning models require large datasets and GPU acceleration for efficient training of multiple hidden layers",
       tags=["ml", "relevant"],
       confidence=0.9
   )
   
   mcp__engrammic__context_store(
       layer="memory",
       content="Transformer architectures use attention mechanisms to process sequential data without recurrence",
       tags=["ml", "relevant"],
       confidence=0.9
   )
   ```

2. Store 3 decoy documents (topically distant):
   ```
   mcp__engrammic__context_store(
       layer="memory",
       content="The recipe calls for two cups of flour and one egg",
       tags=["decoy", "cooking"]
   )
   
   mcp__engrammic__context_store(
       layer="memory",
       content="Victorian architecture features ornate decorations and high ceilings",
       tags=["decoy", "architecture"]
   )
   
   mcp__engrammic__context_store(
       layer="memory",
       content="The hiking trail spans 15 miles through dense forest",
       tags=["decoy", "outdoors"]
   )
   ```

3. Store 2 partially relevant documents:
   ```
   mcp__engrammic__context_store(
       layer="memory",
       content="Computer science students often study algorithms and data structures",
       tags=["partial", "education"]
   )
   
   mcp__engrammic__context_store(
       layer="memory",
       content="Statistical methods are used across many scientific disciplines",
       tags=["partial", "statistics"]
   )
   ```

4. Report all node IDs with their tags

### Worker 2: Search Evaluator

1. Search for machine learning content:
   ```
   mcp__engrammic__context_recall(
       query="How do neural networks learn through training?",
       top_k=8
   )
   ```

2. Evaluate ranking:
   - Check relevance_score ordering
   - Verify ML-tagged docs rank in top 3
   - Verify decoy docs rank lowest
   - Check partial docs rank in middle

3. Test semantic understanding:
   ```
   mcp__engrammic__context_recall(
       query="deep learning GPU requirements",
       top_k=5
   )
   ```

4. Report:
   - Ranking order by relevance_score
   - Whether relevant docs beat decoys
   - Any ranking anomalies

## Success Criteria

- [ ] 8 documents stored across relevance tiers
- [ ] Query returns results ordered by relevance_score
- [ ] Top 3 results are ML-tagged documents
- [ ] Decoy documents rank below relevant ones
- [ ] Partially relevant docs rank between relevant and decoy
- [ ] Semantic query matches conceptually related content

## Notes

Tests search/retrieval quality:
- Hybrid search (semantic + keyword)
- Relevance scoring and ranking
- Semantic understanding beyond keyword matching
- Noise rejection (decoy filtering)
