# Architecture Review (2026-05-07)

5-agent parallel review of context-service codebase.

## Scores

| Dimension | Score | Reviewer Focus |
|-----------|-------|----------------|
| Epistemic philosophy alignment | 7/10 | Spec vs implementation fidelity |
| Layer transitions | Solid | Memory→Knowledge→Wisdom→Intelligence flows |
| MCP tool ergonomics | 6.5/10 | Agent UX, cognitive load |
| Contradiction detection | Partial | Conflict logic soundness |
| Storage architecture | 7.5/10 | Memgraph/Qdrant/Redis, multi-tenancy |

## Priority Issues

### P0: Philosophy Gaps

**1. R1 promotion too eager**
- `_context_assert` auto-promotes claims with >= 1 evidence source at write time
- Spec says T1 (Memory→Knowledge) is signal-driven, Custodian-driven
- Single-source auto-promotion bypasses intended R1/R2/R3 consensus path
- Fix: MCP writes land as `:Claim`; Custodian applies promotion rules async

**2. Confidence calibration not wired**
- Spec defines: `source_tier * corroboration_factor * method_weight * raw_confidence`
- Code accepts `source_tier` as string metadata, stores caller's raw float
- No call to `primitives.epistemology.combined_confidence`
- Fix: Wire calibration formula at claim creation time

**3. No T3/T7 distinction**
- T3: Synthesized Belief (cluster density threshold)
- T7: Agent-authored Commitment (explicit stance)
- Both written as `:Commitment` via same endpoint
- Fix: Add `kind` field to wisdom-layer writes

### P1: Architecture Risks

**4. Dual-write divergence**
- Graph (Memgraph) and vector (Qdrant) writes issued independently
- No saga, outbox, or compensating transaction
- Crash between writes = inconsistent state
- Fix: Outbox pattern - graph write first, enqueue Qdrant upsert job

**5. Raw Cypher escape hatches**
- `execute_query`, `execute_write`, `session()`, `transaction()` on `HyperGraphStore`
- Makes protocol hard to swap for alternative backend
- Fix: Move to `RawCypherMixin`, deprecate from public protocol

**6. `_node_from_record` shape divergence**
- 3 branches: document, passage, legacy Node/Claim/Entity
- Will grow with new node types (ReasoningChain summaries)
- Fix: Registry-dispatch pattern keyed on label

### P2: Ergonomics Debt

**7. `context_store` overloaded**
- 14 params, 6 distinct calling signatures (one per layer)
- Conditionally-required params discovered at runtime, not schema validation
- Extra round-trip per layer type on first call
- Fix: Split into `context_remember` (memory) + `context_assert` (knowledge/wisdom/etc)

**8. `context_admin` ref/name collision**
- `ref` carries node_id, chain_id, ISO datetime, or belief_id depending on `action`
- `name` means `revision_note` or `query text` depending on action
- Fix: Decompose into `context_history` (reads) + `context_session` (writes)

**9. Belief layer inconsistency**
- `context_store(layer="belief")` exists alongside dedicated `context_update_belief`/`context_crystallize`
- Agents unsure which to use
- Fix: Either promote to `context_believe` tool or remove layer variant

### P3: Minor Fixes

**10. Timestamp parameterization**
- `PROMOTE_CLAIM_TO_FACT` uses `datetime()` directly in Cypher
- Should take `$valid_from` parameter like other queries
- Makes promotion non-reproducible in tests

**11. Commitment valid_to on Finding promotion**
- Commitment stays open-ended when promoted to Finding
- Continues to appear in active-node reads
- Fix: `SET cm.valid_to = $promoted_at` in `CREATE_FINDING_FROM_COMMITMENT`

**12. Ignored flags not surfaced**
- `include_steps=True` silently ignored in search mode
- Fix: Return `"ignored_flags": [...]` in response

### P4: Contradiction Detection Limitations

**Current approach**: Structural only (shared ABOUT target)
- Fast (< 30ms), bounded (LIMIT 10)
- No false negatives on co-reference

**Limitations**:
- High false positives ("Alice is CEO" and "Alice is a leader" both ABOUT Alice)
- Semantic conflicts across different ABOUT targets invisible
- No content signal (opposite polarity indistinguishable from complementary)

**Recommendations**:
- Add confidence delta as soft conflict signal (large delta = stronger heuristic)
- Keep semantic detection async-only (embedding comparison at session close)
- Wire `BATCH_CREATE_CONTRADICTS_EDGES` to WorkingBeliefs via `context_link`
- Calibrate `reflection_suggested` threshold to avoid alarm fatigue

## Strengths Noted

- Protocol abstraction (`HyperGraphStore`) is clean and typed
- Silo isolation consistently applied (property predicate + collection isolation)
- Supersession model complete (append-only, SUPERSEDES edges, valid_from/valid_to)
- Hybrid search first-class (dense/sparse/RRF fusion)
- `context_recall` well-designed (4 modes from 2 orthogonal params)
- Belief lifecycle coherent (store → update → crystallize)
- Confidence calibration guidelines in docstrings

## Next Steps

1. Address P0 items before next major release (philosophy alignment)
2. Plan dual-write saga as infrastructure improvement
3. Tool surface refactor can be batched as v2.1 MCP breaking change
