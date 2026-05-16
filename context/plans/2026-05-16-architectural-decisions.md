# Architectural Decisions: Enforcement, Reliability, and Integration

**Date:** 2026-05-16  
**Status:** Draft - Reviewed  
**Scope:** Cross-cutting architectural improvements identified during codebase review

## Context

Review of the codebase identified gaps between documented EAG/CITE specs and actual enforcement. Industry research (knowledge graphs, cognitive architectures, MCP ecosystem, LLM reliability patterns) informed the decisions below.

## Decisions

### D1: Enforce Evidence Non-Empty for Knowledge Layer

**Priority:** Quick win (ship standalone before D3)  
**Location:** `primitives/eag/transitions/`, enforced at `context-service` protocol layer

**Decision:** Hard reject (400 error) Knowledge layer writes with empty evidence.

**Scope clarification:** Applies to `:Claim` nodes (via `learn` tool). `:Fact` nodes created via T5 consensus inherit evidence from source ReasoningChains.

**Rationale:**
- Spec (05-mcp-contract.md) marks evidence as REQUIRED for `learn` tool
- Invariant I1: "Every :Claim in Knowledge has at least one DERIVED_FROM edge"
- Wikidata pattern confirms evidence-first as industry standard
- Soft downgrade to Memory would violate agent intent

**Implementation:**
- Add `validate_evidence_non_empty()` predicate in primitives
- Call from protocol layer before Knowledge writes
- Return structured error with guidance ("use remember for observations without evidence")

**Rollout strategy:**
1. Log-only mode first (count violations in telemetry)
2. Enforce after one release cycle with violation data

**URI validation:** Check non-empty only at write time. External URI reachability is async (Evidence Pipeline handles separately).

---

### D2: Circuit Breakers for Storage Backends

**Priority:** Quick win  
**Location:** `context-service/src/context_service/engine/`

**Decision:** Add circuit breakers per storage backend with differentiated behavior.

| Store | On Circuit Open | Rationale |
|-------|-----------------|-----------|
| Memgraph | Hard fail | Source of truth |
| Qdrant | Hard fail | Source of truth for embeddings |
| Redis | Degrade (proceed without cache) | Optimization layer |

**Implementation:**
- Reuse existing `CircuitBreaker` from `extraction/filter/circuit_breaker.py`
- Add global key: `GLOBAL_SILO = "__global__"` for infrastructure services
- No half-open state needed - auto-reset after cooldown is sufficient

**Parameters:**
```python
failure_threshold: int = 5
window_s: float = 60.0
cooldown_s: float = 60.0
```

**Observability requirements:**
- Log on ALL state transitions (closed->open, open->closed)
- Emit metrics: `circuit_breaker_state{store, state}`, `circuit_breaker_trips_total{store}`
- Alert on circuit open for Memgraph/Qdrant

**State persistence:** In-memory per process. If Redis is down, Redis CB state is local only (acceptable since Redis is degradable).

**Agent backpressure:** Return structured error with `retry_after_seconds` hint when circuit is open.

---

### D3: Formalize Layer Transition Predicates

**Priority:** Quick win (after D1 ships standalone)  
**Location:** `primitives/src/primitives/eag/transitions/`

**Decision:** Create dedicated transitions module in primitives with pure predicate functions.

**Structure:**
```
primitives/eag/
  epistemology/       # (existing) confidence, promotion, supersession
  transitions/        # (new)
    __init__.py
    predicates.py     # can_enter_knowledge(), can_enter_wisdom(), etc.
    constraints.py    # LayerConstraint dataclasses (D7 merged here)
    errors.py         # TransitionError, MissingEvidenceError
```

**Predicates to implement:**

| Predicate | Applies to | Constraints |
|-----------|------------|-------------|
| `can_enter_knowledge(node)` | `:Claim` | evidence non-empty, refs exist |
| `can_enter_wisdom_belief(node)` | `:Belief` | `SYNTHESIZED_FROM` edges to Facts |
| `can_enter_wisdom_commitment(node)` | `:Commitment` | `DECLARED_BY` edge required, evidence optional |
| `can_supersede(old, new)` | All | same subject, valid reason |
| `can_promote(claim)` | `:Claim` -> `:Fact` | corroboration threshold met |
| `can_reject(proposed)` | `:ProposedBelief` | T12 transition |
| `can_trace(chain)` | `:ReasoningChain` | T6 Intelligence->Memory |

**`:Claim:Commitment` handling:** Validates Knowledge structure (SPO format) but Wisdom semantics (`DECLARED_BY` required, evidence optional since agent-authored).

**Enforcement:** context-service protocol layer imports and calls before writes.

---

### D4: LLM Fallback (Primary to Local)

**Priority:** Medium-term  
**Location:** `context-service/src/context_service/llm/`  
**Dependency:** vLLM infrastructure (in infra backlog)

**Decision:** Fallback chain is primary cloud LLM -> local vLLM only. No intermediate cloud fallbacks.

**Clarification:** Primary = configured cloud LLM (Anthropic/OpenAI per settings). Fallback = local vLLM.

| Item | Decision |
|------|----------|
| Runtime | vLLM (self-hosted) |
| Scope | All generation ops (extraction, synthesis, custodian) |
| Embeddings | No fallback for consistency; consider BM25 keyword search as degraded mode |
| Model | Qwen 2.5 72B or Gemma (benchmark on actual GPU infra) |
| Trigger | Circuit breaker open, rate limit, or timeout |

**Quality delta risk:** Local 70B will produce lower quality than Claude/GPT for complex synthesis. Acceptable for availability; log fallback events to monitor quality degradation.

**Implementation:**
- Add fallback config to LLM settings
- Wrap litellm/pydantic-ai calls with fallback logic
- Log fallback events for monitoring

**Embedding degraded mode:** If embedding service fails, fall back to BM25 keyword search via Memgraph full-text index. Lower quality but available.

---

### D5: Retrieval-Worthiness Classification

**Priority:** Quick win (move to Phase 1 - low effort, immediate value)  
**Location:** `context-service/src/context_service/reranking/`

**Decision:** Add floor threshold to existing reranker, return quality signal to agents.

**Parameters:**
```python
# Per-layer defaults
LAYER_THRESHOLDS = {
    Layer.KNOWLEDGE: 0.5,  # stricter - Facts/Claims are authoritative
    Layer.WISDOM: 0.5,     # stricter - Beliefs inform decisions
    Layer.MEMORY: 0.3,     # looser - context, partial matches useful
}
```

**Response additions:**
```python
{
    "results": [...],
    "retrieval_quality": "high" | "partial" | "low" | "none",
    "below_threshold": int,  # filtered count
    "suggestion": str | None  # guidance if quality is low/none
}
```

**Behavior:**
- Filter results below threshold
- Warn with signal, don't fail
- Agent decides how to proceed
- Quality buckets: high (>0.6 avg), partial (0.4-0.6), low (<0.4), none (0 results after filtering)

**Per-layer thresholds:** Enabled by default. Configurable per-silo override.

---

### D6: Contradiction Detection (Hybrid SPO)

**Priority:** Medium-term  
**Location:** `context-service/src/context_service/engine/` + `primitives/eag/epistemology/`

**Decision:** Phased hybrid approach - extract SPO triples, store as edges, rule-based conflict detection.

**Scope:** Commitments only (agent-authored stances)

**Phases:**

| Phase | Scope | Effort |
|-------|-------|--------|
| 1 | LLM extract (subject, predicate, object, polarity), store as properties on Commitment, log conflicts | 2 weeks |
| 2 | Predicate taxonomy (supports/opposes, causes/prevents), exclusivity rules in primitives | 2 weeks |
| 3 | Semantic fallback for low-confidence extractions (optional) | TBD |

**Latency budget:** SPO extraction must complete in <100ms OR run async. If sync extraction exceeds budget, write Commitment immediately and extract in background job.

**Storage (revised to align with spec):**
```cypher
// Store SPO as properties on Commitment node, not separate edges
(:Commitment {
  spo_subject: "project X",
  spo_predicate: "supports", 
  spo_object: "team goals",
  spo_polarity: "positive",
  spo_confidence: 0.9
})
```

**Conflict query (revised):**
```cypher
MATCH (c1:Commitment), (c2:Commitment)
WHERE c1.spo_subject = c2.spo_subject
  AND c1.spo_object = c2.spo_object
  AND c1.spo_predicate = c2.spo_predicate
  AND c1.spo_polarity <> c2.spo_polarity
  AND c1 <> c2
  AND c1.valid_to IS NULL AND c2.valid_to IS NULL  // current only
RETURN c1, c2
```

**Temporal handling:** Only compare currently-valid Commitments (`valid_to IS NULL`). Historical conflicts are expected.

**Predicate taxonomy location:** Define in primitives (domain-agnostic predicates like supports/opposes).

**Behavior:** Warn on write, don't block. Log for analysis.

---

### D7: Declarative Constraints (Python DSL)

**Priority:** Medium-term  
**Location:** `primitives/src/primitives/eag/transitions/constraints.py`  
**Merged with:** D3 (transition predicates)

**Decision:** Python DSL using typed dataclasses, not YAML.

**Rationale:**
- Type safety with mypy strict
- IDE support (autocomplete, refactoring)
- No interpreter overhead
- Sole technical cofounder - no non-engineer audience

**Structure:**
```python
@dataclass
class EdgeConstraint:
    edge_type: str
    target_layer: Layer | list[Layer]
    min_count: int = 0
    max_count: int | None = None

@dataclass
class LayerConstraint:
    required_fields: list[str]
    required_edges: list[EdgeConstraint]
    validators: list[Callable[[Node], ValidationResult]]

# Node-type specific constraints for Wisdom layer
WISDOM_NODE_CONSTRAINTS: dict[str, LayerConstraint] = {
    "Belief": LayerConstraint(
        required_fields=["about"],
        required_edges=[EdgeConstraint("SYNTHESIZED_FROM", Layer.KNOWLEDGE, min=1)],
        validators=[],
    ),
    "Commitment": LayerConstraint(
        required_fields=["about"],
        required_edges=[EdgeConstraint("DECLARED_BY", target_layer=None, min=1)],  # Agent, not layer
        validators=[],
    ),
}
```

**Typing validators:** Use `Protocol` class for validator interface to satisfy mypy strict:
```python
class NodeValidator(Protocol):
    def __call__(self, node: Node) -> ValidationResult: ...
```

---

### D8: OAuth 2.1 for MCP Auth

**Priority:** Deferred  
**Revisit:** Before OSS MCP server release

**Decision:** Defer OAuth 2.1 + PKCE alignment. Current WorkOS auth is sufficient.

**Notes:**
- MCP spec recommends OAuth 2.1 + PKCE
- Research found ~2000 exposed MCP servers lack auth
- Important for public/OSS release, not internal use

---

### D9: Typed Reducer Pattern

**Priority:** Deferred  
**Revisit:** If invalid state transition bugs appear in production

**Decision:** Defer explicit state machine for node lifecycle.

**Rationale:**
- Layer itself is the primary state
- Transition predicates (D3) define valid moves
- Status fields exist where needed (ProposedBelief status, SUPERSEDES edges)
- No evidence of state bugs currently

---

## Implementation Order (Revised)

**Phase 1 (Quick wins):**
1. D1 - Evidence enforcement (standalone, log-only first)
2. D5 - Retrieval worthiness (low effort, immediate value)
3. D2 - Storage circuit breakers

**Phase 2 (Medium-term):**
4. D3 + D7 - Transition predicates + constraints in primitives
5. D6 - Contradiction detection (phased, no infra blockers)
6. D4 - LLM fallback (blocked on vLLM infra)

**Phase 3 (Deferred):**
- D8 - OAuth 2.1 (OSS launch)
- D9 - Typed reducers (if needed)

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| D1 breaks existing agents | Log-only mode first; measure violation rate before enforcing |
| D2 cascading failures | Return `retry_after_seconds` hint; agents should implement backoff |
| D4 quality degradation on fallback | Log all fallback events; monitor downstream quality metrics |
| D6 false positives | Warn don't block; human review of flagged conflicts initially |
| D6 latency blowout | Async extraction if >100ms; write first, extract background |

## Open Questions (Updated)

1. ~~Should D1 enforcement run a backfill check?~~ **Answered:** Log-only mode first, then enforce after measuring violations.

2. ~~What local model to finalize for D4?~~ **Answered:** Qwen 2.5 72B or Gemma (final choice depends on GPU infra benchmarks).

3. ~~For D6, should the predicate taxonomy be defined in primitives or context-service?~~ **Answered:** Primitives (domain-agnostic).

4. ~~For D5, should quality thresholds differ per layer?~~ **Answered:** Yes, per-layer. Knowledge 0.5, Wisdom 0.5, Memory 0.3.

5. ~~For D2, what alert thresholds for circuit breaker trips?~~ **Answered:** Any Memgraph/Qdrant circuit open = page.

6. ~~For D1, how does evidence enforcement interact with Evidence Pipeline async modes?~~ **Answered:** Check non-empty only; URI validation is separate async concern.

## References

- `primitives/context/specs/02-layers.md` - Layer definitions
- `primitives/context/specs/03-transitions.md` - Transition catalogue  
- `primitives/context/specs/05-mcp-contract.md` - MCP invariants
- Industry research: Neo4j GRAPH TYPE, Wikidata constraints, LangGraph reducers, AGM belief revision

## Review Notes (2026-05-16)

Opus review identified:
- Spec alignment issues with D1 scope (`:Claim` vs all Knowledge), D3 predicates (per-node-type), D6 schema
- Completeness gaps: URI validation timing, CB state persistence, temporal conflicts
- Risks: breaking existing agents, cascading failures, false positives
- Prioritization: D5 moved to Phase 1, D1 ships standalone before D3

All findings incorporated above.
