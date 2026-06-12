# Critical Review: Architecture, Epistemics, and Data Structure Decisions

Date: 2026-06-11
Author: Claude (direct review, not subagent), grounded in: `context/architecture.md`, `primitives/docs/01-paradigm.md` + `06-epistemology.md`, `primitives/schema/labels.py` + `edges.py`, `context/plans/2026-06-01-brain-architecture.md`, and the code read during today's moat audit (services/context.py, sage/recall.py, sage/transactions.py, mcp/tools/*, reranking/*, config/settings.py).

Stance: the foundations are better than most two-person startups ship. The criticisms below are the gap between the spec's promises and the system's behavior - which, for a product whose entire pitch is epistemic rigor, is the gap that matters most.

## 1. Architecture

### What is right

- Protocol-based storage seams (`engine/protocols.py`) are real, not ceremonial. The standalone/SQLite engine being feasible proves the seam holds.
- Verb-based MCP surface as config (`mcp_tools.yaml`) is the correct call: the agent-facing contract evolves without code changes.
- Silo threading is disciplined: silo_id in every query, ownership cache, cross-silo evidence rejection. The moat audit rated multi-tenancy REAL+DEEP for a reason.
- The commitment to deterministic adjudication (no LLM at decision time) is the single best architectural decision in the system. Keep it sacred.

### A1. The two-brains problem (most serious)

There are two parallel epistemic engines alive simultaneously: the SAGE/Dagster cadence pipeline plus `services/context.py` (the live MCP path), and the reactive brain (`sage/transactions.py` + `sage/recall.py`, Phases 1-7 complete, cutover blocked). They have DIFFERENT semantics for the same operations:

- `sage/recall.py:compute_recall_score` multiplies confidence into Knowledge-layer scores; `services/context.py:query` never touches confidence in ranking (today's read-path leak exists partly because the fix was already written - in the dead path).
- Supersession filtering: sage checks `NodeState.SUPERSEDED`; services checks `props.get("superseded_by")`. Two different sources of truth for the same predicate.
- Conflict surfacing, temporal filters, layer scoring: all duplicated with drift.

Every epistemic improvement must now be made twice or silently diverges. The brain-cutover blockers list (link enum mismatch, crystallize signature, revise transaction) is short; the cost of NOT cutting over compounds with every read-path change - including the step-1 fusion work, which is being wired into the path that the brain rewrite was supposed to replace. Kill one brain. This is the highest-leverage architectural cleanup in the codebase.

### A2. Ranking logic has no owner

The final relevance of a recall result is currently shaped in five places with no single module owning the pipeline: Qdrant hybrid score -> freshness/heat multipliers (services) -> reranker overwrite (context_query) -> threshold/adaptive-tau/quality (reranking/quality) -> trust gate withholding (recall verb). Step 1 adds epistemic fusion as a sixth stage. Each stage was added for a good reason; the composition was never designed. The reranker-overwrites-everything bug is the predictable result of stage-by-stage accretion. Post-sprint: extract one `ranking/` pipeline with named, ordered, individually-testable stages and a documented contract for which score basis each consumer (floor, tau, quality, ordering, gate) reads. The step-1 plan's `score_basis_key` is the first brick of this; finish the wall.

### A3. Operational surface vs team size

Memgraph + Qdrant + Redis + Postgres + Dagster + Watchtower for a pre-revenue product run by one technical founder. The dagster/alembic collision incident and the Memgraph-MAGE image requirement are the predictable tax. Two specific risks:

- Dual-write consistency: store() writes Memgraph and Qdrant with no outbox/saga. A Qdrant success + Memgraph failure (or vice versa) leaves a node retrievable-but-absent or present-but-unsearchable. For a product selling bookkeeping integrity, an unreconciled dual-write is an embarrassing failure mode. At minimum: a nightly reconciliation job (count + sample diff per silo); ideally an outbox.
- GDPR erasure must cascade across graph, vectors, caches (result cache, rerank cache, embedding cache), and Redis streams. The forget/erasure work covers the primary stores; the cache layers are where deleted content lingers. Verify TTLs are the only guarantee and document that.

The standalone SQLite engine is not just a community edition - it is the answer to this for every deployment below scale tier. Treat Memgraph+Qdrant as the scale tier, not the default.

### A4. Config sprawl

settings.py is ~1000 lines, dozens of nested configs, 12 already-identified dead flags. Every flag is a behavior fork that tests must cover and docs must explain. The selfhosted-env-example incident (documented vars that wire to nothing) is the symptom. Adopt a rule: a config flag ships with (a) a test exercising both values or (b) a deletion date.

## 2. Epistemics

### What is right

- Four-layer persistence-semantics framing is genuinely correct and the paradigm doc is honest about scope ("bookkeeping, not cognition").
- Provenance invariants I1-I6 enforced at write time, with layer-ordered acyclicity (I4) - elegant, cheap, correct.
- SUPERSEDES edges requiring a typed reason enum is exactly the kind of discipline competitors lack.
- The extraction/adjudication seam (LLM at extraction, pure functions at adjudication) is the right boundary.

### E1. The confidence scalar conflates four orthogonal judgments

`combined = source_tier x corroboration x method_weight x raw_confidence` collapses provenance quality, agreement, extraction method, and an LLM's self-report into one number. Problems:

1. raw_confidence is an LLM self-report - notoriously uncalibrated. Multiplying it in means the "deterministic" confidence is a deterministic function of a stochastic, biased input. The determinism claim survives; the meaningfulness claim does not, until calibrated.
2. The magic constants (0.85, 0.75, 0.6, the 0.383 community ceiling, the -0.5 exponent) have no calibration data behind them - "calibration based on observed accuracy" is explicitly deferred. Until then these are vibes with decimal places; fine, but then the system should not make threshold decisions (promotion, trust-gate floors) read as if the scalar were measured probability.
3. No `formula_version` on nodes. When you DO recalibrate, every stored confidence silently changes meaning. Stamp the formula version at write time; it costs one prop and saves a future migration nightmare. (credibility_factors already stores the breakdown - good - so the fix is cheap.)

### E2. Missing confidence means opposite things in different code paths

Found during today's audit and worth elevating: `services/context.py:1491` treats missing confidence as 1.0 (`or 1.0`), `sage/recall.py:412` as 0.0, the trust gate as 1.0, the min_confidence filter in sage as 0.0. The SAME epistemic state - "we never assessed this" - is "fully trusted" on one path and "worthless" on another. For an epistemics product this is not a nit; it is the product contradicting itself about what absence of evidence means. Decide once (recommendation: missing = None, never penalized, never boosted - the trust-gate convention), encode it in ONE function in primitives, and make every reader call it.

### E3. Four representations of "superseded"

A node's supersession is expressed via (1) `state == SUPERSEDED`, (2) `props.superseded_by`, (3) `valid_to` timestamp, (4) the SUPERSEDES edge. Different readers consult different ones (see A1). Canonical-source rule needed: the edge is the truth (it carries reason + provenance); state/props/valid_to are derived caches written in the same transaction. One helper resolves "is this node current"; all readers use it. Same disease, smaller: conflict_status is stringly-typed ("none"/"unresolved"/"resolved_*") in props with no enum in primitives, while the resolution taxonomy (supersede/merge/coexist) lives in validator code. Promote both to primitives enums - they ARE the epistemology.

### E4. The structural-contradiction claim is narrower than the marketing

The marquee deterministic contradiction detection (same s, same p, different o) requires entity resolution plus a registered predicate vocabulary - and applies only to the EXTRACTION path. The live `learn()` path stores free-text claims; its inline contradiction check is embedding cosine similarity with an async LLM confirm - useful, but neither structural nor deterministic. So the honest statement is: "deterministic adjudication over structurally-extracted claims; similarity-flagged, LLM-confirmed contradiction for free-text assertions." The current docs blur this, and open-vocabulary predicates routing to an admin queue is a human bottleneck (or silent dropout) at any real scale. Either invest in the predicate registry as a first-class product surface or stop implying structural detection covers agent writes.

### E5. Corroboration counts sources, not independence

`count(distinct source_node_id)` - the mem0 #4573 pathology (one hallucination amplified into 808 entries) would CORROBORATE itself under naive counting unless dedup catches every copy. CITE v2's independence-weighted corroboration is the right answer and is apparently implemented (Phase 7 checked off), but `06-epistemology.md` still documents the naive count, and the primitives package update was deferred "after Phase 2 validation". Spec/impl drift on the exact mechanism that distinguishes you from the failure mode you pitch against. Sync the doc, and make independence weighting the documented default.

### E6. Bi-temporality is half of what the audit positioning needs

valid_from/valid_to + as_of queries give VALID time. There is no TRANSACTION time (when did the system learn/record it). "What did we believe on March 1" - the auditor's actual question - conflates the two; Zep ships proper bi-temporal edges and will win that comparison in any diligence that probes. Either add recorded_at/transaction-time to the temporal model (cheap if done now, brutal later) or scope the audit pitch to provenance-and-revision-history rather than full time-travel.

### E7. ProposedBelief: schrodinger's deprecation

The brain plan says "ProposedBelief eliminated - use confidence threshold". The label remains in the schema, accept/dismiss verbs remain in the surface, MCP server instructions still teach the ProposedBelief flow, and SAGE still emits them on the legacy path. Two contradictory belief-formation stories are live in documentation simultaneously. Pick one (my take: the accept/dismiss adjudication verb flow is the differentiator - agent-in-the-loop belief promotion is the thing nobody else has; a silent confidence threshold throws that away). Then delete the loser everywhere in one commit.

### E8. Decay has two uncoordinated knobs

`MEMORY_DECAY_SIGMA = 90` hardcoded in sage/recall.py vs `settings.freshness_sigma_days` used by services - two dials for one concept, on the two diverged paths. The fusion research's recommendation (per-layer half-life: memory ~14d, knowledge ~90d, wisdom none) should land as ONE per-layer config consumed by the ONE surviving path.

### E9. Layer asymmetry vs marketing symmetry

Implementation maturity is Memory/Knowledge deep, Wisdom medium (synthesis is weak-LLM + gating, crystallize/revise on legacy paths), Intelligence shallow (session-scoped storage with the weakest invariants). That asymmetry is FINE - it matches the thinking-vs-retrieval honest framing - but the four-layer diagram implies symmetric depth. Expect sophisticated buyers (Verda's engineers) to probe Wisdom/Intelligence and find less than the diagram suggests. Pre-empt: describe layers by maturity in technical docs.

## 3. Data format / structure

### D1. The properties-dict escape hatch

Typed labels, untyped everything else: confidence, credibility, credibility_factors, conflict_status, superseded_by, valid_from/to, heat, tier all live in a schemaless props dict read via string keys with per-call-site defaults (see E2). There are no prop migrations, so every reader is defensively coded against every historical prop shape - which is where the inconsistent-defaults bug class breeds. Fix: define a pydantic `EpistemicState` model (confidence, credibility, credibility_factors, conflict_status, formula_version) serialized under ONE prop key, parsed by ONE function. Single point of schema evolution; mypy strict actually gets to help.

### D2. Edge taxonomy has redundancy and a split brain

CORROBORATES vs SUPPORTS (both "this strengthens that" - one semantic, one epistemology-propagation; the distinction is real but undocumented at the schema level), REFERENCES vs MENTIONS, DERIVED_FROM vs EXTRACTED_FROM. And the MCP `link` verb's relationship enum does not match CITEEdgeType - which is literally one of the brain-cutover blockers. Rules worth adopting: one shared enum (primitives is the source; MCP imports it), and every edge type documents exactly one writer and one consumer pattern. Edges nobody traverses are schema debt.

### D3. Multi-label subtyping is fragile

`Commitment` encoded as multi-label `Claim:Commitment` already produced one production bug (commitment-label fix in the May 28 audit). Multi-label works in Memgraph but every Cypher query must remember the pattern, and greps miss it. A `subtype` property (or making Commitment a first-class label with its own layer mapping) is more boring and more robust.

### D4. SPO triples are the spec's knowledge unit, not the system's

The paradigm doc declares claims-as-structured-triples the unit of knowledge ("claims, not chunks"). In the live system, triples exist only on the extraction path; agent `learn()` writes are free text with evidence URIs. That is a reasonable pragmatic choice - but it means the knowledge layer is bimodal (structured triples + free-text claims) and most epistemic machinery (structural contradiction, SPO corroboration identity) only works on the structured half. Either (a) run extraction over learn() writes too (async, the custodian already exists for this) so everything converges to triples, or (b) update the paradigm doc to describe the bimodal reality. (a) is the better product: it would make agent-written claims first-class citizens of the contradiction/corroboration machinery - which is exactly the capability the benchmark needs to demonstrate.

### D5. Content lives in two stores plus caches

Content in Memgraph, embeddings (and payload?) in Qdrant, copies in result/rerank/embedding caches. Beyond the dual-write risk (A3), this makes "what does the system know about X, exhaustively" - the audit-tool query - subtly hard against your own store. The Memory Health Audit tool should be built against the graph as sole source of truth, treating the vector store as an index, never a source.

## 4. Priority ordering (my opinion, post-sprint)

1. **Kill one brain** (A1) - unblocks everything; the cutover blockers are days of work.
2. **One epistemic-state module** (E2 + D1 + E3): canonical missing-confidence semantics, typed EpistemicState prop, canonical supersession resolver, conflict/resolution enums in primitives, formula_version stamping.
3. **Extraction over learn() writes** (D4) - converges the knowledge layer to triples and widens the moat the benchmark measures.
4. **Ranking pipeline extraction** (A2) - formalize what step 1 started.
5. **Settle ProposedBelief** (E7) - keep accept/dismiss, delete the threshold story (or vice versa, but decide).
6. **Transaction-time** (E6) - before the audit/compliance positioning hardens around a promise the data model only half keeps.
7. **Reconciliation job for dual-writes** (A3) - one Dagster/reaction job, cheap insurance.
8. Doc syncs: independence-weighted corroboration (E5), bimodal knowledge layer (D4), layer maturity (E9), config flag hygiene (A4).

## Closing judgment

The architecture's bones are good and the epistemology's COMMITMENTS are the right ones - deterministic adjudication, provenance invariants, typed supersession, layer-differentiated persistence. The recurring disease is divergence: two read paths, two decay knobs, four supersession representations, two belief-formation stories, two contradiction mechanisms, spec'd-vs-shipped gaps in corroboration and triples. None of these is individually fatal; together they are exactly how an epistemics product loses the right to its own pitch. The system that keeps consistent, sourced, revisable books must keep its OWN books consistent first. Convergence work is unglamorous and invisible to buyers, which is why (per the court verdict's pattern) it must be strictly sequenced AFTER the sprint's proof artifacts - but the list above should be the very next plan after the benchmark ships.
