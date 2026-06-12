# LongMemEval Epistemic Harness Enhancement

**Goal:** Leverage full REST API surface for richer ingestion and smarter recall in the benchmark harness.

## Current State

The harness uses 3 endpoints:
- `POST /remember` - raw DOM chunks as observations
- `POST /learn` - extracted UI facts with evidence URIs
- `POST /link` - FOLLOWED_BY and CONTAINS relationships

Recall is flat: `POST /recall` with query string, returns mixed results.

## Phase 1: Richer Ingestion

### 1.1 Reasoning Chains for UI Flows

When processing a trajectory, synthesize multi-step patterns:

```python
# After processing all states in a trajectory
flow_steps = [
    {"step": 1, "reasoning": "User lands on homepage with login button"},
    {"step": 2, "reasoning": "Clicks login, modal appears with email/password fields"},
    {"step": 3, "reasoning": "Submits credentials, redirected to dashboard"},
]
self._reason(
    steps=flow_steps,
    conclusion="This site uses modal-based authentication with email/password",
    evidence_used=[state_node_ids],  # link to observed states
)
```

Endpoint: `POST /reason`

### 1.2 Commitments for Domain Patterns

High-confidence patterns that span multiple trajectories:

```python
# When we see the same pattern across 3+ trajectories
self._decide(
    content="E-commerce sites consistently use cart icon in top-right navigation",
    about=[evidence_node_ids],  # facts that support this
    confidence=0.9,
)
```

Endpoint: `POST /decide`

### 1.3 Smarter Link Types

Replace generic RELATED_TO with semantic relationships:

| Pattern | Link Type |
|---------|-----------|
| State A leads to State B | FOLLOWED_BY (keep) |
| Fact extracted from state | DERIVED_FROM |
| Multiple facts support conclusion | SUPPORTS |
| UI element references another | REFERENCES |

### 1.4 Hypotheses for Uncertain Patterns

When a pattern is observed but not yet confirmed:

```python
self._hypothesize(
    content="This site may require 2FA after password entry",
    about=[observed_state_ids],
    confidence=0.6,
)
# Later, if confirmed across trajectories:
self._crystallize(hypothesis_id=hyp_id)
```

Endpoints: `POST /hypothesize`, `POST /crystallize`

## Phase 2: Smarter Recall

### 2.1 Multi-Layer Query Strategy

Query different layers based on question type:

```python
def query(self, query: str) -> list[MemoryContextItem]:
    results = []
    
    # 1. Get relevant beliefs/commitments first (high-level patterns)
    wisdom_results = self._recall(query, layers=["wisdom"])
    
    # 2. Get supporting facts
    knowledge_results = self._recall(query, layers=["knowledge"])
    
    # 3. Get raw observations if needed
    memory_results = self._recall(query, layers=["memory"])
    
    # 4. Dedupe and rank by layer (wisdom > knowledge > memory)
    return self._merge_by_epistemic_rank(wisdom_results, knowledge_results, memory_results)
```

### 2.2 Provenance-Enriched Results

For retrieved beliefs, fetch provenance to provide context:

```python
for result in wisdom_results:
    if result.layer == "wisdom":
        # Get the evidence chain
        provenance = self._trace(result.node_id, max_depth=3)
        result.provenance_summary = self._summarize_provenance(provenance)
```

Endpoint: `POST /trace`

### 2.3 History-Aware Retrieval

Check if beliefs have evolved (supersession chain):

```python
for result in results:
    history = self._history(node_id=result.node_id)
    if len(history.timeline) > 1:
        # This belief was updated - include evolution context
        result.evolution_note = f"Updated {len(history.timeline)} times, latest: {history.current}"
```

Endpoint: `POST /history`

### 2.4 Reasoning Chain Retrieval

Find applicable reasoning chains for the query:

```python
# Reasoning chains have embedded conclusions for similarity matching
# The recall endpoint already searches chain embeddings
# Surface chains with their steps for richer context
```

## Implementation Order

1. **Phase 1.1** - Add `_reason()` method, call after trajectory processing
2. **Phase 1.3** - Upgrade link types (DERIVED_FROM for facts)
3. **Phase 2.1** - Layer-aware recall with merge strategy
4. **Phase 2.2** - Provenance enrichment for wisdom-layer results
5. **Phase 1.2** - Cross-trajectory commitments (requires pattern detection)
6. **Phase 1.4** - Hypotheses for uncertain patterns
7. **Phase 2.3** - History-aware retrieval
8. **Phase 2.4** - Reasoning chain surfacing

## API Methods to Add

```python
class EngrammicMemory:
    # Existing
    def _remember(self, content, tags) -> str | None
    def _learn(self, claim, evidence, tags) -> str | None
    def _link(self, from_id, to_id, relation) -> None
    
    # New - Ingestion
    def _reason(self, steps, conclusion, evidence_used) -> str | None
    def _decide(self, content, about, confidence) -> str | None
    def _hypothesize(self, content, about, confidence) -> str | None
    def _crystallize(self, hypothesis_id) -> str | None
    
    # New - Recall
    def _trace(self, node_id, max_depth) -> dict
    def _history(self, node_id) -> dict
    def _recall_layered(self, query, layers) -> list[dict]
```

## Success Metrics

- **Retrieval precision**: % of retrieved items that are relevant
- **Provenance depth**: avg citation chain length for wisdom-layer results
- **Layer distribution**: % of answers sourced from wisdom vs knowledge vs memory
- **Reasoning coverage**: % of trajectories with synthesized reasoning chains

## Open Questions

1. Should we run SAGE (custodian/synthesizer) during benchmark, or just use agent-side epistemics?
2. How aggressive should pattern detection be for cross-trajectory commitments?
3. Should provenance be included in the context sent to the reader model?
