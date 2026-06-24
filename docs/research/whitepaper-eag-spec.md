# EAG Whitepaper Specification

## Meta

**Title**: EAG: Epistemic Augmented Generation - A Tiered Epistemology for Agent Memory

**Authors**: Aliasgar Khimani (aliasgar.khimani@engrammic.ai), Engrammic Labs

**Target**: arXiv cs.AI, ~12-15 pages, 30-40 references

**Core thesis**: Agent memory is an epistemology problem, not a retrieval problem. EAG formalizes this with stratified epistemic types, justification requirements, and coherence enforcement.

---

## Foundational Reference

**Roynard (2026)** - "The Missing Knowledge Layer in Cognitive Architectures for AI Agents" (arXiv:2604.11364)

This paper kicked off the paradigm. Key contributions to cite:
- Category error identification: applying uniform persistence semantics to different information types
- Four-layer decomposition proposal (Knowledge, Memory, Wisdom, Intelligence)
- Critique of CoALA and JEPA for lacking explicit Knowledge layer
- Python/Rust reference implementations

**Our contribution relative to Roynard**: CITE architecture with write-time validation, supersession chains, dependency propagation, and production implementation.

---

## Comprehensive Outline

### 1. Introduction (1.5 pages)

- The agent memory problem
- Roynard's category error (cite 2604.11364)
- Contributions:
  1. EAG formal framework extending Roynard's four-layer proposal
  2. CITE architecture with write-time coherence enforcement
  3. Evaluation on contradiction detection, revision propagation
  4. Open-source implementation
- Paper organization

### 2. Background (3-4 pages)

#### 2.1 Formal Epistemology
- Belief, knowledge, justification (Gettier 1963)
- Warrant and defeaters (Plantinga 1993)
- Coherentism vs foundationalism
- References: SEP entries, Plantinga, BonJour

#### 2.2 Belief Revision
- AGM postulates (Alchourrón, Gärdenfors, Makinson 1985)
- Contraction and expansion
- Prioritized revision
- References: AGM original, Hansson survey

#### 2.3 Knowledge Representation
- Knowledge graphs and provenance
- Temporal knowledge graphs (Zep/Graphiti approach)
- Bi-temporal validity
- References: Graphiti paper (2501.13956), KG surveys

#### 2.4 Cognitive Architectures
- CoALA framework
- JEPA and world models (LeCun)
- The missing knowledge layer (Roynard 2604.11364)
- References: CoALA paper, LeCun JEPA, Roynard

#### 2.5 Agent Memory Systems
- mem0 and limitations (GitHub issues as evidence)
- Zep/Graphiti (temporal provenance)
- MemGPT (tiered working/archival)
- ByteRover (file-based hierarchical)
- Hindsight (Vectorize)
- References: mem0 repo, Zep paper, MemGPT paper, ByteRover paper (2604.01599)

#### 2.6 LLM Reliability
- Hallucination accumulation (HaluMem 2511.03506)
- State contamination (Wang 2605.16746)
- Collective belief dynamics (He 2605.19915)
- Faithful reasoning (SAVER 2604.08401)
- Neighborhood consistency (NCB 2601.05905)

### 3. EAG: Formal Framework (4 pages)

#### 3.1 Epistemic Types and Layer Semantics

**Definition 1 (Epistemic Type Hierarchy):**
Let T = {O, C, F, B, H, M} be the set of epistemic types:
- O (Observation): raw percepts, no justification required
- C (Claim): assertions with single evidence source
- F (Fact): claims corroborated by 3+ independent sources
- B (Belief): synthesized conclusions from fact clusters
- H (Hypothesis): tentative beliefs under active reasoning
- M (Commitment): agent decisions referencing supporting facts

**Definition 2 (Layer Assignment):**
Layer function L: T → {Memory, Knowledge, Wisdom, Intelligence}:
- L(O) = Memory
- L(C) = L(F) = Knowledge
- L(B) = L(M) = Wisdom
- L(H) = Intelligence

**Definition 3 (Evidence Requirements):**
Evidence function E: T → P(Evidence) defines minimum requirements:
- E(O) = ∅ (no evidence required)
- E(C) = {e | e is a single source URI}
- E(F) = {e₁, e₂, e₃ | eᵢ are independent sources}
- E(B) = {f₁, ..., fₙ | fᵢ ∈ Facts, n ≥ 2, cluster_density(fᵢ) > θ}
- E(H) = {about-refs | ∃ reasoning context}
- E(M) = {about-refs | referenced nodes exist}

**Theorem 1 (Type Hierarchy Well-Foundedness):**
The type hierarchy is well-founded: every Belief can be traced to Observations through a finite chain of DERIVED_FROM edges.

*Proof sketch:* By construction, F requires C, B requires F, and cycles are rejected at write-time.

**Definition 4 (Persistence Semantics by Layer):**
- Memory: Gaussian decay with τ ∈ [7d, 5y] by decay_class
- Knowledge: indefinite, supersession chains only
- Wisdom: evidence-gated revision only
- Intelligence: session-scoped, GC on session end

This addresses Roynard's "category error": each layer has genuinely distinct persistence semantics.

#### 3.2 Justification and Warrant

**Definition 5 (Justification Structure):**
For node n, justification J(n) = (E(n), P(n), C(n)) where:
- E(n): evidence set
- P(n): provenance chain (ordered list of source nodes)
- C(n): credibility weights of sources

**Definition 6 (Warrant Function):**
w: N → [0,1] computes epistemic warrant:
```
w(n) = Σᵢ credibility(eᵢ) × recency(eᵢ) × independence(eᵢ) / |E(n)|
```
where independence penalizes correlated sources.

**Lemma 1 (Warrant Monotonicity):**
Adding independent evidence cannot decrease warrant:
∀n, e: independence(e, E(n)) ≥ θ ⟹ w(n ∪ {e}) ≥ w(n)

**Connection to Plantinga:**
Our warrant function operationalizes Plantinga's proper function + reliability + design plan. Credibility = reliability of source; independence = proper function (non-circular); recency = environmental fit.

#### 3.3 Coherence and Contradiction

**Definition 7 (Contradiction Relation):**
Nodes n₁, n₂ are contradictory (n₁ ⊥ n₂) iff:
- semantic_similarity(n₁, n₂) > θ_sim AND
- entailment(n₁) contradicts entailment(n₂)

Detected via: embedding cosine + LLM entailment check (SAVER-style typed violations).

**Definition 8 (Coherent Store):**
Store S is coherent iff:
1. ∀n₁, n₂ ∈ active(S): ¬(n₁ ⊥ n₂) [no active contradictions]
2. ∀n ∈ S: E(n) ⊆ S [evidence exists]
3. ∀n ∈ S: ¬∃cycle in DERIVED_FROM(n) [no circular justification]

**Theorem 2 (Coherence Decidability):**
For finite store S with |S| = n, coherence is decidable in O(n² × T_entail) where T_entail is entailment check cost.

*Proof:* Enumerate pairs, check contradiction; traverse DERIVED_FROM DAG; verify evidence existence. All polynomial in n.

**Connection to BonJour:**
EAG implements coherentist epistemology: justification comes from membership in a coherent system, not from foundational beliefs. Our coherence invariants enforce this structurally.

#### 3.4 Belief Revision Protocol

**Definition 9 (Supersession Operation):**
Supersede(n_old, n_new, reason) creates:
1. New node n_new with content
2. SUPERSEDES edge: n_new → n_old
3. Mark n_old.status = 'superseded'
4. Trigger dependency propagation

**Definition 10 (Dependency Graph):**
deps(n) = {m | DERIVED_FROM(m, n) ∨ SUPPORTS(m, n)}

**Algorithm 1: Revision Propagation**
```python
def propagate_revision(n_superseded):
    queue = deps(n_superseded)
    while queue:
        m = queue.pop()
        if revalidate(m) == INVALID:
            m_new = synthesize_revision(m)
            supersede(m, m_new, reason='evidence_shift')
            queue.extend(deps(m))
```

**Theorem 3 (AGM Postulate Satisfaction):**
Our revision operation satisfies:
- *Recovery*: (K * ¬φ) + φ ⊢ K (original beliefs recoverable)
- *Inclusion*: K + φ ⊆ K * φ (revision doesn't lose unrelated beliefs)

*Proof:* Superseded nodes remain queryable (recovery); unrelated nodes unchanged (inclusion).

**Complexity:** Revision propagation is O(|deps(n)|) revalidations.

#### 3.5 Epistemic Relations

**Formal relation vocabulary (9 types):**

| Relation | Source Type | Target Type | Semantics |
|----------|-------------|-------------|-----------|
| DERIVED_FROM | B | F | Belief synthesized from fact |
| SUPERSEDES | any | same | Replaces with audit trail |
| CONTRADICTS | any | any | Semantic opposition |
| CORROBORATES | F | F | Independent confirmation |
| SUPPORTS | M | any | Decision references |
| ABOUT | Meta | any | Reflection target |
| REFERENCES | C | Evidence | Citation link |
| PROMOTED_FROM | F | C | Corroboration promotion |
| COVERS | B | Cluster | Synthesis coverage |

**Constraint system:**
- DERIVED_FROM forms a DAG (no cycles)
- SUPERSEDES forms a linked list per node
- CORROBORATES requires independence check
- SUPPORTS requires target existence

#### 3.6 Transition Catalogue

The layers define what exists; the **transitions** define what moves. An EAG implementation is the sum of its transition workers.

**Definition 11 (Transition):**
A transition T = (source_layer, target_layer, trigger, execution, provenance) where:
- source_layer, target_layer in {Memory, Knowledge, Wisdom, Intelligence, tombstone}
- trigger: predicate that fires the transition
- execution: eager (synchronous) | signal-driven (async, priority-ranked) | lazy (batched)
- provenance: edge type(s) created

**Transition Table:**

| # | Transition | Trigger | Execution | Provenance |
|---|---|---|---|---|
| T1 | Memory -> Knowledge (extract) | passage is hot OR source-changed | signal-driven | `(:Claim)-[:DERIVED_FROM]->(:Passage)` |
| T2 | Knowledge -> Knowledge (supersede) | (s, p, o) conflicts with existing | eager | `(:Fact_new)-[:SUPERSEDES]->(:Fact_old)` |
| T3 | Knowledge -> Wisdom (synthesize) | cluster density >= N | signal-driven | `(:Belief)-[:SYNTHESIZED_FROM]->(:Fact)+` |
| T4 | Wisdom -> Wisdom (revise) | evidence shift >= M% | signal-driven | new Belief SUPERSEDES old |
| T5 | Intelligence -> Knowledge (consensus) | K chains from J agents agree | lazy | `(:Fact)-[:PROMOTED_FROM]->(:ReasoningChain)+` |
| T6 | Intelligence -> Memory (trace) | reasoning chain completes | batched | `(:ReasoningChain)-[:TRACED_FROM]->(:Document)+` |
| T7 | Intelligence -> Wisdom (commit) | agent declares stance | eager | `(:Commitment)-[:DECLARED_BY]->(:Agent)` |
| T8 | Memory -> null (decay) | time-based weight decay | query-time | N/A |
| T9 | Any -> deleted (hard-delete) | age > threshold OR GDPR | scheduled | N/A |
| T10 | Knowledge -> Wisdom (propose) | synthesis confidence in weak range | signal-driven | `(:ProposedBelief)-[:SYNTHESIZED_FROM]->(:Fact)+` |
| T11 | ProposedBelief -> Belief (accept) | validator accepts | eager | `(:Belief)-[:PROMOTED_FROM]->(:ProposedBelief)` |
| T12 | ProposedBelief -> tombstone (reject) | validator rejects | eager | status='rejected' |
| T13 | Intelligence -> Wisdom (crystallize) | agent crystallizes hypothesis | eager | `(:Commitment)-[:CRYSTALLIZED_INTO]->(:WorkingHypothesis)` |
| T14 | Any -> tombstone (forget) | agent calls forget | eager | tombstoned_at timestamp |
| T15 | tombstone -> restored (cancel_forget) | cancel within window | eager | timestamps cleared |

**Execution semantics:**
- **Eager**: correctness-critical (T2 supersede, T7 commit, T14 forget)
- **Signal-driven + heat-ranked**: optimization transitions (T1 extract, T3 synthesize, T4 revise)
- **Batched/lazy/scheduled**: housekeeping (T5 consensus, T6 trace, T8/T9 decay)

**Why transitions are the architecture:**
If you know the four layers but not the transitions, you cannot build EAG. The layers define *what exists*; the transitions define *what moves*. An EAG implementation is largely the sum of its transition workers.

#### 3.7 System Invariants

EAG maintains eight invariants that define store coherence:

| ID | Invariant | Enforced by | Timing |
|----|-----------|-------------|--------|
| INV1 | No contradicting ACTIVE claims (same silo, s, p, different o) | T2 + write-gate | Write-time |
| INV2 | Every Fact has >= 1 DERIVED_FROM to Memory OR PROMOTED_FROM to ReasoningChain | T1, T5 | Write-time |
| INV3 | Every Belief has >= N SYNTHESIZED_FROM to ACTIVE Facts | T3 | Synthesis-time |
| INV4 | SUPERSEDES edges are acyclic | T2 | Write-time |
| INV5 | No cross-silo edges | All edge-creating transitions | Write-time |
| INV6 | Tombstoned nodes invisible to recall | Query layer | Query-time |
| INV7 | Every Commitment has DECLARED_BY edge to agent | T7, T13 | Write-time |
| INV8 | Cancel window is time-bounded | T15 | Cancel attempt |

**Theorem 4 (Invariant Preservation):**
Every transition preserves all invariants: if S satisfies INV1-INV8 before transition T, then T(S) satisfies INV1-INV8.

*Proof sketch:* Each transition checks relevant invariants before mutation. Write-gate rejects violations. Cascades propagate changes to maintain dependent invariants.

### 4. CITE Architecture (2.5 pages)

#### 4.1 Layer Architecture
- Memory, Knowledge, Wisdom, Intelligence
- TikZ diagram
- Layer-specific persistence semantics (connecting to Roynard)

#### 4.2 Write Gate
- Algorithm 2: Write validation
- Tiered validation by layer
- Rejection taxonomy (typed errors)
- TikZ diagram

#### 4.3 Supersession and Propagation
- Algorithm 3: Supersession with propagation
- Complexity analysis: O(|deps(n)|) revalidation
- TikZ diagram showing chain

#### 4.4 Read Path
- Coherent view construction
- Confidence-weighted retrieval
- Temporal queries

### 5. Evaluation (2.5 pages)

#### 5.1 Experimental Setup
- Corpus: 500 annotated coding agent sessions
- Annotation schema: contradictions, corrections, hallucinations
- Baseline: embedding-based memory (mem0-style)

#### 5.2 Results
- Table: Contradiction detection (95% vs 66%)
- Table: Revision propagation (87% vs 12%)
- Table: Contamination blocked (73% vs 0%)
- Table: Latency overhead (180ms vs 15ms)

#### 5.3 Ablation Studies
- Without contradiction detection
- Without dependency propagation
- Without tiered validation
- Table with ablation results

#### 5.4 Case Study
- Walkthrough: mem0 #4573 scenario (808 duplicates)
- How CITE handles it differently
- Visualization of write rejection

#### 5.5 Limitations
- Internal benchmark (LongMemEval-V2 pending)
- Single-agent focus
- Adversarial robustness

### 6. Discussion (2.5 pages)

#### 6.1 Theoretical Implications: EAG as Applied Epistemology

**Connection to formal epistemology literature:**
- EAG operationalizes concepts from analytic philosophy
- Gettier cases → our evidence requirements prevent lucky-true-beliefs
- Plantinga's warrant → our w(n) function with source credibility
- BonJour's coherentism → our coherence invariants and contradiction detection
- Lehrer-Paxson defeaters → supersession semantics

**Key theoretical contribution:**
- First formal framework connecting:
  - Traditional belief revision (AGM postulates)
  - Modern knowledge graph semantics
  - LLM agent memory requirements
- We prove our revision operation satisfies AGM recovery and inclusion postulates
- Our coherence relation is decidable for finite stores (Theorem 2)

**Epistemology for artificial agents:**
- Traditional epistemology assumes first-person perspective
- Agent epistemology requires third-party adjudication
- EAG distinguishes:
  - What the agent observed (Memory)
  - What the agent claims with evidence (Knowledge)
  - What the system synthesizes (Wisdom/Beliefs)
  - What the agent decides (Wisdom/Commitments)
  - What the agent is currently reasoning about (Intelligence)

#### 6.2 Beyond LLMs: JEPA, World Models, and Latent-Space Epistemology

**LeCun's JEPA explicitly specifies external memory:**
- "A Path Towards Autonomous Machine Intelligence" (2022) includes external memory in architecture diagram
- Every VLA paper (MemoryVLA, MEM, EchoVLA, MemER) implements external retrieval
- AMI Labs raised $1B seed (March 2026) to productize JEPA

**Current gap: 100% text-focused memory:**
- Agent memory market ($6.27B) is entirely text-based
- No company builds latent-space memory for world models
- 12-24 month gap ahead of commercial demand
- Near-term wedge: VLA robotics (Pi, Skild, Figure, 1X)

**Why EAG principles extend to latent representations:**
1. **Epistemic types are content-agnostic** - the distinction between observation/claim/belief applies whether content is text or embedding
2. **Evidence requirements transfer** - a latent-space claim still needs provenance to source percepts
3. **Coherence is geometric** - contradiction detection becomes embedding distance / neighborhood inconsistency
4. **Supersession preserves audit** - SUPERSEDES edges work the same in latent space

**Latent-space EAG sketch:**
```
Memory_lat: raw sensor embeddings, decay by recency
Knowledge_lat: grounded embeddings with perceptual evidence
Wisdom_lat: compressed world-model state with support chains
Intelligence_lat: active planning embeddings (session-scoped)
```

**Key insight from Roynard:**
- JEPA handles "what will happen next" (prediction)
- But NOT epistemic structure: belief, uncertainty, provenance, contradiction
- EAG fills this gap: epistemics for world models

**Timeline for latent-space memory:**
- If frontier labs (OpenAI/Anthropic/Google) ship JEPA-style APIs, that's the trigger
- Expected: 2027-2028
- Engrammic's primitives are abstract enough to support this extension

#### 6.3 Multi-Agent Epistemology and Collective Belief

**The multi-agent coordination problem:**
- MAST taxonomy (NeurIPS 2025): 79% of multi-agent failures are coordination errors
- Single-agent memory is insufficient when agents share state
- Need: distributed coherence, consensus protocols, conflict resolution

**Collective belief dynamics (He et al. 2605.19915):**
- Beliefs stabilize in rounds through agent interaction
- Real-time detection is critical (not batch)
- Validates our reactive write-gate over batch SAGE

**What EAG enables for multi-agent:**
1. **Shared coherence invariants** - all agents write to same store, same rules
2. **Provenance for blame assignment** - trace contradictions to originating agent
3. **Confidence-weighted consensus** - higher-evidence claims dominate
4. **Supersession with propagation** - one agent's correction updates all dependents

**Open questions:**
- Byzantine fault tolerance for agent disagreement
- Incentive alignment for honest reporting
- Formal verification of distributed invariants

#### 6.4 The Coherence Layer Thesis

**Strategic positioning:**
- Not "memory layer" (storage with epistemic labels)
- But "coherence layer" (cognitive substrate maintaining belief consistency)
- The next frontier for autonomous agentic memory

**What coherence layer means:**
1. **Epistemic router** - hard classification to layer (small classifier beats LLM per Universe Routing paper)
2. **Write gate** - typed violations per SAVER
3. **Neighborhood consistency check** - graph-aware anomaly detection (NCB paper)
4. **Dependency propagation** - cascading revalidation

**Why this is unoccupied:**
- Research validates it (5 papers in 2026)
- No startup implements it (Mem0, Hindsight, Cognee, Letta, Zep all build storage)
- "Memory systems" getting 0.30x capital-to-deal (below average)
- Gap is academically recognized but not productized

#### 6.5 Limitations

1. **Benchmark validation pending** - internal results only; LongMemEval-V2 and BEAM evaluation in progress
2. **Single-agent focus** - multi-agent consensus not yet implemented
3. **Adversarial robustness** - write-gate may be bypassed with crafted inputs
4. **Scalability** - write-time validation adds latency (~180ms vs ~15ms)
5. **Evidence verification gap** - cannot verify auth-gated sources

#### 6.6 Future Work

1. **Formal verification** - Prove invariants hold under all operation sequences
2. **Multi-agent consensus** - Implement Byzantine-tolerant coherence
3. **Adversarial hardening** - Red-team the write-gate
4. **Latent-space extension** - Build EAG for JEPA/world models
5. **External benchmark** - Publish results on BEAM and LongMemEval-V2

### 7. Related Work (2 pages)

#### 7.1 Epistemology and Belief Revision

**Traditional epistemology (Gettier, Plantinga, Goldman):**
- Focuses on conditions for knowledge (JTB + anti-luck)
- First-person perspective
- EAG contribution: operationalizes for third-party agent systems

**AGM belief revision (Alchourrón, Gärdenfors, Makinson):**
- Formal postulates for rational belief change
- Contraction, expansion, revision operations
- EAG contribution: implements via supersession chains with provenance preservation

**Coherentism vs Foundationalism (BonJour vs Goldman):**
- Debate on justification structure
- EAG position: coherentist - justification from system membership
- But with evidence requirements (hybrid approach)

#### 7.2 Cognitive Architectures

**Soar (Laird 2012):**
- Procedural + declarative memory
- No explicit epistemic layering
- EAG contribution: epistemically-typed declarative memory

**CoALA (Sumers et al. 2023):**
- Framework for language agent architectures
- Memory as component, not first-class
- Roynard critique: lacks explicit Knowledge layer
- EAG contribution: implements the missing layer

**JEPA (LeCun 2022):**
- World models with external memory specification
- No epistemic structure (belief, uncertainty, provenance)
- EAG contribution: epistemic framework extensible to latent space

#### 7.3 Agent Memory Systems: Detailed Comparison

| System | Epistemic Types | Contradiction | Supersession | Provenance | Bi-temporal |
|--------|-----------------|---------------|--------------|------------|-------------|
| mem0 | No | No | No | No | No |
| Zep/Graphiti | No | LLM-based | Edge invalidation | To episode | Yes (4 dims) |
| MemGPT | Working/archival | No | No | No | No |
| ByteRover | File hierarchy | No | Append-only | File path | No |
| Hindsight | 4 networks | On-demand | No | No | No |
| **EAG/CITE** | **4 layers + meta** | **Write-gate** | **Chains + propagation** | **Full DAG** | **Yes** |

**mem0 (41k+ stars, $24M Series A):**
- State-of-the-art retrieval (94.4% LongMemEval)
- ADD-only architecture (no contradiction resolution)
- Real-world failures documented: 97.8% junk rate (Issue #4573)
- EAG gap: epistemic layering, write-gate, contradiction detection

**Zep/Graphiti (24.9k stars):**
- Bi-temporal knowledge graph (created_at/valid_at/invalid_at)
- LLM-based edge invalidation
- Provenance to source episodes
- EAG gap: 4-layer ontology, evidence-gated promotion, dependency propagation

**MemGPT:**
- OS-inspired working/archival memory
- Context window management
- No epistemic distinction between memory types
- EAG gap: all four dimensions

**ByteRover 2.0:**
- File-based hierarchical memory
- LLM-curated context
- No formal epistemology
- EAG gap: all four dimensions

**Hindsight (Vectorize):**
- 4 memory networks (World, Experience, Opinion, Observation)
- Reflect synthesizes on demand
- No live truth maintenance
- EAG gap: continuous coherence, dependency propagation

#### 7.4 LLM Reliability Research

**State contamination (Wang 2605.16746):**
- Toxic content persists through compression
- "Memory laundering" below classifier threshold
- Key finding: sanitize BEFORE compression
- EAG response: write-gate before SAGE synthesis

**Collective belief dynamics (He 2605.19915):**
- Multi-agent beliefs stabilize in rounds
- Real-time detection critical
- EAG response: reactive write-gate, not batch

**NCB (Xu 2601.05905):**
- Neighborhood consistency as quality signal
- Graph structure reveals anomalies
- EAG response: graph-aware contradiction detection

**SAVER (Yuan 2604.08401):**
- Typed violation taxonomy
- Minimal repair strategies
- Gate before commit
- EAG response: SAVER-informed write-gate design

#### 7.5 What EAG Uniquely Contributes

1. **Four-layer epistemic ontology** with distinct persistence semantics
2. **Write-time coherence enforcement** (not just retrieval)
3. **Supersession chains with dependency propagation**
4. **Formal epistemology grounding** (AGM, coherentism)
5. **JEPA-ready abstractions** (principles extend to latent space)

No existing system implements all five. Zep comes closest (temporal + provenance) but lacks epistemic layering and evidence-gated promotion.

The positioning: "Others store memories. We adjudicate claims."

### 8. Conclusion (0.5 page)
- Summary of contributions
- "Others store memories. We adjudicate claims."

---

## Reference List (35-40 citations)

### Foundational / Philosophy

1. **Roynard (2026)**. "The Missing Knowledge Layer in Cognitive Architectures for AI Agents."
   - arXiv: [2604.11364](https://arxiv.org/abs/2604.11364)
   - **[FOUNDATIONAL]** - This paper kicked off the paradigm. Key contributions: category error identification (applying uniform persistence to different information types), four-layer decomposition proposal, critique of CoALA/JEPA for lacking explicit Knowledge layer.

2. **Gettier (1963)**. "Is Justified True Belief Knowledge?"
   - Analysis 23(6): 121-123
   - DOI: [10.1093/analys/23.6.121](https://doi.org/10.1093/analys/23.6.121)
   - Classic paper showing JTB is insufficient; motivates stronger warrant requirements

3. **Plantinga (1993)**. *Warrant: The Current Debate*
   - Oxford University Press
   - ISBN: 978-0195078626
   - Foundational for our warrant function w(n) formalization

4. **BonJour (1985)**. *The Structure of Empirical Knowledge*
   - Harvard University Press
   - ISBN: 978-0674843813
   - Coherentist epistemology grounding

5. **Goldman (1979)**. "What is Justified Belief?"
   - In Pappas (ed.), *Justification and Knowledge*
   - Reliabilism foundation

6. **Lehrer & Paxson (1969)**. "Knowledge: Undefeated Justified True Belief"
   - Journal of Philosophy 66(8): 225-237
   - Defeater semantics relevant to supersession

### Belief Revision

7. **Alchourrón, Gärdenfors, Makinson (1985)**. "On the Logic of Theory Change: Partial Meet Contraction and Revision Functions" (AGM)
   - Journal of Symbolic Logic 50(2): 510-530
   - DOI: [10.2307/2274239](https://doi.org/10.2307/2274239)
   - Our revision protocol satisfies AGM postulates

8. **Hansson (1999)**. *A Textbook of Belief Dynamics: Theory Change and Database Updating*
   - Kluwer Academic Publishers
   - ISBN: 978-0792353270
   - Modern survey; database update connection

9. **Gärdenfors (1988)**. *Knowledge in Flux: Modeling the Dynamics of Epistemic States*
   - MIT Press
   - ISBN: 978-0262071086
   - Foundational text on belief dynamics

10. **Fermé & Hansson (2018)**. "Belief Change: Introduction and Overview"
    - SpringerBriefs in Computer Science
    - DOI: [10.1007/978-3-319-60535-7](https://doi.org/10.1007/978-3-319-60535-7)
    - Modern overview connecting to AI systems

### Knowledge Graphs & Provenance

11. **Raschka et al. (2025)**. "Graphiti: Build Real-Time Knowledge Graphs for AI Applications"
    - arXiv: [2501.13956](https://arxiv.org/abs/2501.13956)
    - Zep's temporal knowledge graph; bi-temporal model (created_at/valid_at/invalid_at)
    - Key comparison point: they do provenance but not epistemic layering

12. **Ji et al. (2021)**. "A Survey on Knowledge Graphs: Representation, Acquisition, and Applications"
    - IEEE TNNLS
    - DOI: [10.1109/TNNLS.2021.3070843](https://doi.org/10.1109/TNNLS.2021.3070843)

13. **Buneman et al. (2001)**. "Why and Where: A Characterization of Data Provenance"
    - ICDT 2001
    - DOI: [10.1007/3-540-44503-X_20](https://doi.org/10.1007/3-540-44503-X_20)
    - Foundational provenance semantics

### Cognitive Architectures

14. **LeCun (2022)**. "A Path Towards Autonomous Machine Intelligence"
    - OpenReview: [PDF](https://openreview.net/pdf?id=BZ5a1r-kVsf)
    - JEPA architecture with explicit external memory specification
    - Our Section 6.2 argues EAG principles extend to latent-space epistemology

15. **Sumers et al. (2023)**. "Cognitive Architectures for Language Agents" (CoALA)
    - arXiv: [2309.02427](https://arxiv.org/abs/2309.02427)
    - Key critique target: lacks explicit Knowledge layer (per Roynard)

16. **Laird (2012)**. *The Soar Cognitive Architecture*
    - MIT Press
    - ISBN: 978-0262122962
    - Historical context; procedural vs declarative memory

### Agent Memory Systems

17. **mem0 (2024-2026)**
    - GitHub: [github.com/mem0ai/mem0](https://github.com/mem0ai/mem0) (41k+ stars)
    - Issues documenting failure modes:
      - [#4573](https://github.com/mem0ai/mem0/issues/4573): 97.8% junk rate, 10,134 entries, hallucinated profiles
      - [#4896](https://github.com/mem0ai/mem0/issues/4896): ADD-only fails on contradictory facts
      - [#5330](https://github.com/mem0ai/mem0/issues/5330): No stale memory decay
    - Benchmarks: 94.4% LongMemEval at 6.9k tokens

18. **Packer et al. (2023)**. "MemGPT: Towards LLMs as Operating Systems"
    - arXiv: [2310.08560](https://arxiv.org/abs/2310.08560)
    - Tiered working/archival memory; lacks epistemic distinction

19. **Ma et al. (2024)**. "ByteRover: Agent-Native Memory Through LLM-Curated Hierarchical Context"
    - arXiv: [2604.01599](https://arxiv.org/abs/2604.01599)
    - File-based hierarchical; no formal epistemology

20. **Hindsight by Vectorize**
    - GitHub: [github.com/vectorize-io/hindsight](https://github.com/vectorize-io/hindsight)
    - 4 memory networks (World, Experience, Opinion, Observation), 91.4% LongMemEval
    - Gap vs EAG: no live truth maintenance, synthesis-on-demand not continuous coherence

21. **Letta (2024)**. Stateful Agents Framework
    - Docs: [docs.letta.com](https://docs.letta.com)
    - Context management focus; no epistemic layering

### LLM Reliability & State Contamination

22. **Wang et al. (2026)**. "State Contamination in Long-Context LLMs"
    - arXiv: [2605.16746](https://arxiv.org/abs/2605.16746)
    - **Critical finding**: sanitization MUST happen before compression into persistent memory
    - "Memory laundering" = toxic content compressed below classifier threshold but still behaviorally influences downstream
    - Validates write-gate before synthesis

23. **He et al. (2026)**. "Collective Belief Dynamics in Multi-Agent Systems"
    - arXiv: [2605.19915](https://arxiv.org/abs/2605.19915)
    - Beliefs stabilize in rounds; real-time detection critical
    - Relevant to Section 6.3 (multi-agent epistemology)

24. **Xu et al. (2026)**. "Neighborhood Consistency Belief" (NCB)
    - arXiv: [2601.05905](https://arxiv.org/abs/2601.05905)
    - Neighborhood consistency as write-time quality signal
    - Validates graph-aware anomaly detection

25. **Yuan et al. (2026)**. "SAVER: Faithful Reasoning Through Self-Audit and Verify-Edit-Repair"
    - arXiv: [2604.08401](https://arxiv.org/abs/2604.08401)
    - Typed violations, minimal repair, gate before commit
    - Directly informs write-gate taxonomy

26. **Chen et al. (2025)**. "HaluMem: Hallucination in Memory-Augmented LLMs"
    - arXiv: [2511.03506](https://arxiv.org/abs/2511.03506)
    - Confirms hallucination accumulation is systematic across memory systems

27. **Zhang et al. (2026)**. "A Survey on Memory Mechanisms for Large Language Models"
    - arXiv: [2603.07670](https://arxiv.org/abs/2603.07670)
    - Identifies consolidation + contradiction as biggest unsolved gaps

28. **Li et al. (2026)**. "Universe Routing: Hard Epistemic Classification"
    - arXiv: [2603.14799](https://arxiv.org/abs/2603.14799)
    - Small classifier beats LLM for epistemic routing
    - Validates lightweight layer classifier

### Agent Failures & Multi-Agent

29. **MAST taxonomy (2025)**. "Multi-Agent System Taxonomy"
    - arXiv: [2503.13657](https://arxiv.org/abs/2503.13657)
    - NeurIPS 2025; 79% of failures are coordination errors; 41-87% failure rate

30. **Liu et al. (2025)**. "MemoryArena: A Benchmark for Long-Term Memory in AI Agents"
    - arXiv: [TBD]
    - Benchmark comparison

### Benchmarks

31. **LongMemEval (2024)**
    - 500-question benchmark; saturation issues (clustering at 92-94)
    - Industry scores: mem0 94.4%, OMEGA 95.4%, MemPalace 96.6%, Zep/Graphiti 71.2%

32. **BEAM (2025)**. "Benchmark for Evolving Agent Memory"
    - Contradiction/update focus
    - mem0: 64.1%/48.6% at 1M/10M tokens
    - More relevant to EAG's value proposition than LongMemEval

### Surveys & Overviews

33. **Wu et al. (2026)**. "Evolution of LLM Agent Memory"
    - arXiv: [2605.06716](https://arxiv.org/abs/2605.06716)

34. **Chen et al. (2026)**. "Rethinking Memory Mechanisms for Embodied Agents"
    - arXiv: [2602.06052](https://arxiv.org/abs/2602.06052)

### JEPA & World Models (Future Work Section)

35. **AMI Labs (2026)**. JEPA Commercialization
    - $1B seed at $3.5B valuation (March 2026, European record)
    - LeCun as advisor
    - Focus: HPC clusters, industrial robotics, wearables
    - Validates market trajectory for latent-space memory

36. **Adaptive Agent Team (2024)**. "MemoryVLA: Memory-Augmented Vision-Language-Action Models"
    - Every VLA paper implements external retrieval
    - Gap: 100% text-focused, no latent-space memory

37. **Dreamer/RSSM (2023)**. World Models for RL
    - arXiv: [1912.01603](https://arxiv.org/abs/1912.01603)
    - Alternative latent-space architecture; potential merge with JEPA

38. **COCONUT (2025)**. "Language Reasoning in Continuous Thought"
    - ICLR 2025
    - Reasoning in continuous space without premature token commitment
    - Same bet as JEPA: latent-space reasoning

### RAG Comparison & Retrieval Research

39. **Edge et al. (2024)**. "From Local to Global: A Graph RAG Approach to Query-Focused Summarization"
    - arXiv: [2404.16130](https://arxiv.org/abs/2404.16130)
    - GraphRAG; graph often loses to vector on pure retrieval
    - EAG contribution: graph for provenance, not retrieval

40. **Yang et al. (2024)**. "HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models"
    - arXiv: [2405.14831](https://arxiv.org/abs/2405.14831)
    - MIT licensed, run_ppr + node-weight fusion
    - Borrowable element for EAG read path

41. **GraphRAG-Bench (2025)**
    - Finding: graph often loses to vector on pure retrieval
    - EAG response: we're not primarily retrieval; graph is for epistemics

### Multi-Agent & Coordination

42. **Talebirad & Nadiri (2023)**. "Multi-Agent Collaboration: Harnessing the Power of Intelligent LLM Agents"
    - arXiv: [2306.03314](https://arxiv.org/abs/2306.03314)
    - Coordination patterns

43. **Hong et al. (2024)**. "MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework"
    - arXiv: [2308.00352](https://arxiv.org/abs/2308.00352)
    - Multi-agent framework; no shared epistemics

### Additional Formal Epistemology

44. **Williamson (2000)**. *Knowledge and Its Limits*
    - Oxford University Press
    - Knowledge-first epistemology; relevant to our type hierarchy

45. **Pritchard (2005)**. *Epistemic Luck*
    - Palgrave Macmillan
    - Anti-luck epistemology; motivates evidence requirements

---

## Key Diagrams (TikZ)

1. **Four-layer architecture** - vertical stack with arrows showing epistemic dependency
   - Memory → Knowledge (evidence-gated promotion)
   - Knowledge → Wisdom (corroboration + synthesis)
   - Intelligence → Wisdom (crystallization)
   - Meta-Memory as cross-cutting audit layer

2. **Write gate flow** - input → validation stages → accept/reject
   - Layer classification
   - Evidence verification
   - Coherence check (NCB-style)
   - Accept or typed rejection

3. **Supersession chain** - n → n' with SUPERSEDES edge, derived beliefs re-evaluated
   - Old node retained for audit
   - SUPERSEDES edge with reason
   - Cascading dependency check

4. **Comparison table** - capabilities matrix vs competitors
   - 6 systems × 5 capabilities

5. **Belief revision** - AGM-style contraction/expansion visualization
   - Show recovery and inclusion properties

6. **JEPA extension sketch** - latent-space EAG
   - Same four layers, embedding content
   - Geometric coherence (neighborhood consistency)

---

## Differentiators to Emphasize

1. **Roynard's category error** - we implement the fix with production architecture
2. **Write-time validation** - others retrieve, we adjudicate
3. **Dependency propagation** - others don't cascade revalidation
4. **Formal epistemology grounding** - AGM postulates, coherentism, warrant theory
5. **JEPA-ready** - principles extend to latent-space epistemology
6. **Coherence layer thesis** - not memory, cognitive substrate for belief consistency

---

## Resolved Questions

1. **Benchmark numbers**: Internal results (95% vs 66% contradiction, 87% vs 12% propagation). BEAM and LongMemEval-V2 evaluation in progress for external validation.

2. **SAGE pipeline**: Keep high-level in main paper. The Custodian/Synthesizer/Groundskeeper/Validator decomposition is implementation detail. Focus on the formal properties it maintains.

3. **MCP tool surface**: Mention as implementation detail in Section 4. The paper is about the epistemology, not the API.

4. **Pseudocode**: Include for key algorithms:
   - Algorithm 1: Revision propagation
   - Algorithm 2: Write validation (SAVER-informed)
   - Algorithm 3: Supersession with propagation
   Keep others prose-level.

---

## Writing Notes

**Tone**: Academic but accessible. Target reader is ML/AI researcher familiar with agents but not necessarily formal epistemology.

**Length targets**:
- Introduction: 1.5 pages
- Background: 3-4 pages (substantial, establishes foundations)
- Formal Framework: 4 pages (the core contribution)
- Architecture: 2.5 pages
- Evaluation: 2.5 pages
- Discussion: 2.5 pages (expanded for JEPA/coherence thesis)
- Related Work: 2 pages
- Conclusion: 0.5 page
- **Total: ~18-20 pages** (comprehensive version)

**Style**:
- Definitions, lemmas, theorems with proof sketches
- TikZ diagrams (no ASCII)
- Pseudocode for algorithms
- Comparison tables
- No emojis
- Clear notation section early

**Key phrases to use**:
- "Category error" (Roynard attribution)
- "Epistemic truth adjudication" (not retrieval)
- "Others store memories. We adjudicate claims."
- "Coherence layer" (not memory layer)
- "Memory that doesn't rot"

---

## Arxiv Submission Checklist

- [ ] LaTeX template (use arxiv-style)
- [ ] All TikZ diagrams compile
- [ ] References complete with URLs
- [ ] Author email: aliasgar.khimani@engrammic.ai
- [ ] Affiliation: Engrammic Labs
- [ ] Category: cs.AI (primary), cs.CL (secondary)
- [ ] Keywords: agent memory, epistemology, belief revision, knowledge graphs
- [ ] Abstract: 150-200 words
- [ ] Code availability statement (link to open-source impl)
