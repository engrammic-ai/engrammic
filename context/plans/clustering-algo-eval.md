# Clustering algorithm evaluation

**Goal:** Evaluate whether Leiden (current) should be replaced with a faster or more stable
algorithm. Current situation: Leiden runs via igraph workaround (MAGE native is broken), is
expensive enough to be batched to daily off-peak, and adds an igraph dependency. Three
candidates worth evaluating against it.

**Branch:** `phase-clustering-algo-eval` (spike, no prod changes until decision made)

---

## Background

Current implementation: `clustering/service.py` runs Leiden at three CPM resolution levels via
`igraphalg.community_leiden` in Memgraph. The MAGE native `leiden_community_detection.get` raises
"No communities detected" at all resolutions on our graph, so we go through igraph. Results feed
into `clustering/service.py`'s hierarchical summary pipeline (cluster nodes + LPA summaries via
LLM). Scheduled daily per silo via Dagster.

The cost is real: daily batching was introduced specifically because Leiden is too slow to run
incrementally on each write. This is worth fixing.

---

## Candidates

### 1. Label Propagation (LPA) — graph-native, near-linear

MAGE: `community_detection.get` (stable, documented, no known bugs on our graph shape).

Complexity: O(n+m). Near-linear. Could run incrementally after every custodian sweep rather than
daily. No igraph dependency. Downside: non-deterministic, can produce unstable clusters on sparse
graphs. Run multiple times and compare community assignments to check stability.

**Best case:** drop Leiden + igraph entirely, run LPA after each custodian sweep, retire the daily
Dagster schedule. Simpler stack, lower latency on Wisdom promotion.

### 2. HDBSCAN — embedding-space, no graph traversal required

Since every node is already embedded in Qdrant, clustering can happen entirely in embedding space
without touching Memgraph. HDBSCAN does not require a pre-specified k, handles variable-density
clusters well, and is robust to noise (relevant for a knowledge graph where cluster sizes vary
wildly by silo).

Library: `hdbscan` (scikit-learn compatible) or `cuML` if GPU is available.

Downside: loses the relational structure — HDBSCAN clusters by semantic similarity, not by
actual graph connectivity. Two nodes that are semantically similar but not connected in the graph
(contradicting facts from different sources, for instance) could end up in the same cluster. This
is a meaningful quality regression for our use case.

**Best case:** use HDBSCAN as a fast first-pass to seed cluster hypotheses, then validate with a
lightweight graph connectivity check before promoting to Wisdom nodes.

### 3. Louvain — graph-native, faster than Leiden in practice

MAGE: `louvain_community_detection.get`. Louvain is the predecessor to Leiden, slightly weaker
theoretical guarantees (can produce disconnected communities in edge cases), but faster in
practice and no known issues on our graph. Worth a direct benchmark against Leiden before
assuming LPA is the right swap.

---

## Evaluation criteria

| Criterion | Why it matters |
|---|---|
| Stability (same graph, multiple runs) | Wisdom nodes should not flicker between runs |
| Quality vs. Leiden baseline | Cluster coherence on a sample silo |
| Runtime on a 10k-node silo | Does it unblock incremental runs? |
| MAGE native vs. igraph dependency | Simplicity of stack |
| Handles sparse silos (< 100 nodes) | Early-stage silos should not produce garbage clusters |

---

## Suggested order

1. **Benchmark Louvain vs. Leiden** on a sample silo. If Louvain is within acceptable quality
   range, swap it in — lowest-risk change, no architectural shift.
2. **Spike LPA** on the same sample. Check stability across 10 runs. If stable enough, replace
   Leiden + switch clustering to post-custodian-sweep rather than daily.
3. **Spike HDBSCAN** as a hybrid: embed-space clustering for initial candidate clusters, graph
   connectivity check to reject cross-component clusters. Only worth it if LPA stability is
   unacceptable.

---

## Out of scope

- Changing the hierarchical summary pipeline (LLM summarisation per cluster) — that runs
  downstream of whatever detection algorithm is chosen and is unaffected.
- Changing the Dagster asset structure — schedule frequency may change but asset shape stays.
- SPLADE / hybrid retrieval changes — covered in `v1b-splade.md`.

---

## Done criteria

- A decision is made: one algorithm chosen, rationale documented.
- If replacing Leiden: `clustering/service.py` updated, igraph removed from dependencies if no
  longer needed, Dagster schedule adjusted if incremental runs become viable.
- `just check` passes, integration tests updated.
