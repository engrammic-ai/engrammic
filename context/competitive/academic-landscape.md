# Academic Landscape: Graph-Based LLM Memory

Last updated: 2026-05-05

## HippoRAG / HippoRAG 2

**Source:** OSU-NLP Group (Gutierrez, Shu, Gu, Yasunaga, Su)
**Venues:** NeurIPS 2024, ICML 2025

**Citations:**
- HippoRAG: https://proceedings.neurips.cc/paper_files/paper/2024/file/6ddc001d07ca4f319af96a3024f6dbd1-Paper-Conference.pdf
- HippoRAG 2: https://arxiv.org/abs/2502.14802
- Code: https://github.com/OSU-NLP-Group/HippoRAG

**Core idea:** Hippocampal indexing theory applied to RAG. LLM as neocortex (pattern processing), schemaless KG as hippocampus (indexing). OpenIE extracts triples; Personalized PageRank enables single-step multi-hop retrieval.

**Results:**
- 20% improvement over SOTA on multi-hop QA
- 10-20x cheaper, 6-13x faster than iterative retrieval (IRCoT)
- HippoRAG 2: 7% improvement on associative memory tasks

**Gaps vs EAG:**
- No epistemology (all triples treated equally, no claim/fact distinction)
- No temporal schema (benchmarks temporal reasoning but no valid_from/valid_to)
- No consensus/validation mechanism
- Multi-session memory listed as "future work"

**Positioning:** Solves retrieval efficiency, not knowledge quality. Complementary.

---

## AriGraph

**Source:** AIRI Institute / Skoltech (Anokhin, Semenov, Sorokin, Evseev, Kravchenko, Burtsev, Burnaev)
**Venue:** IJCAI 2025

**Citations:**
- Paper: https://arxiv.org/abs/2407.04363
- Proceedings: https://www.ijcai.org/proceedings/2025/0002.pdf

**Core idea:** Memory graph integrating semantic and episodic memories for agent world models. TripletGraph foundation with episodic vertices/edges layered on top.

**Results:**
- Outperforms established memory methods on TextWorld (complex interactive text games)
- Competitive on multi-hop QA benchmarks

**Gaps vs EAG:**
- No epistemic verification (no claim to fact promotion)
- No explicit temporal handling (sequence implicit in graph structure)
- Single-agent, single-run focused (no multi-session)
- No confidence/consensus mechanism

**Positioning:** Agent world-modeling, not knowledge management. Different problem space.

---

## Other Notable Work

**Cognee Framework** (topoteretes/cognee): Open-source graph-based memory with Extract-Cognify-Load pipeline. 2025 paper on hyperparameter optimization for graph RAG.

**"From Experience to Strategy"**: Multi-layered trainable graph memory with meta-cognition abstraction. Worth tracking.

---

## Comparison Matrix

| Dimension | HippoRAG | AriGraph | Delta Prime (EAG) |
|-----------|----------|----------|-------------------|
| Core win | Fast multi-hop retrieval | Agent world-modeling | Knowledge validation + temporal |
| Graph schema | Schemaless (OpenIE) | Triplet + episodic | Tiered layers + CITEEdgeType |
| Multi-session | Future work | Not addressed | Native (silo_id) |
| Temporal | Benchmarked, no schema | Implicit sequence | valid_from/valid_to, time-travel |
| Epistemology | None | None | Claim to Fact via custodian |
| Confidence | None | None | R1/R2 validators, supersession |

---

## Takeaways

1. **Retrieval vs Trust:** Academic work focuses on retrieval efficiency. EAG's differentiator is epistemic validation.
2. **Temporal is underexplored:** No academic system has explicit temporal schema with time-travel queries.
3. **Multi-session gap:** Cross-run memory is future work or unaddressed in all surveyed systems.
4. **No "NeoCognition":** Could not find a paper by this name. May be unpublished or different name.
