# Clustering Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans

**Goal:** Scope clustering to Knowledge layer (Fact/Claim) by default, with configurable layer param

**Architecture:** Add target_layers param to run_clustering, filter queries by layer labels

**Tech Stack:** Memgraph Cypher, async Python, Leiden clustering

---

## Context

Clustering currently includes all content nodes (Document, Passage, Claim, Entity) via hardcoded
label filters in three primitives queries: `RUN_LEIDEN`, `BATCH_CREATE_MEMBER_OF`, and
`RUN_PAGERANK`. This pulls unvalidated Memory-layer nodes into Wisdom synthesis.

The fix adds a `target_layers: list[Layer]` param to `ClusteringService.run_clustering` and
introduces layer-filtered variants of the three affected queries in
`src/context_service/clustering/queries.py`. The primitives queries remain unchanged (they are
upstream and shared); we shadow them with local overrides that accept a label filter string.

Layer -> label mapping:
- `Layer.MEMORY` -> `Document OR Passage` (raw ingest nodes)
- `Layer.KNOWLEDGE` -> `Fact OR Claim`
- `Layer.WISDOM` -> `Cluster` (not a valid clustering input; guard against this)
- `Layer.INTELLIGENCE` -> no content label; guard similarly

Default: `[Layer.KNOWLEDGE]` -> `Fact OR Claim`.

---

## Steps

### Step 1 — Write failing tests for layer-to-label mapping helper

**File:** `tests/test_clustering_scope.py` (new file)

- [ ] Create `tests/test_clustering_scope.py`
- [ ] Import `Layer` from `primitives.protocols`
- [ ] Import the (not-yet-existing) helper `layer_labels` from
  `context_service.clustering.queries`
- [ ] Write `test_knowledge_layer_labels` — assert `layer_labels([Layer.KNOWLEDGE])` returns
  `"Fact OR Claim"`
- [ ] Write `test_memory_layer_labels` — assert `layer_labels([Layer.MEMORY])` returns
  `"Document OR Passage"`
- [ ] Write `test_multi_layer_labels` — assert `layer_labels([Layer.MEMORY, Layer.KNOWLEDGE])`
  returns `"Document OR Passage OR Fact OR Claim"`
- [ ] Write `test_wisdom_layer_raises` — assert `layer_labels([Layer.WISDOM])` raises `ValueError`
- [ ] Run `uv run pytest tests/test_clustering_scope.py -v` — all four tests must FAIL (ImportError
  is acceptable)

```bash
uv run pytest tests/test_clustering_scope.py -v
```

---

### Step 2 — Implement `layer_labels` helper and layer-filtered query strings

**File:** `src/context_service/clustering/queries.py`

- [ ] Add import: `from primitives.protocols import Layer`
- [ ] Add `_LAYER_LABEL_MAP: dict[Layer, list[str]]`:

  ```python
  _LAYER_LABEL_MAP: dict[Layer, list[str]] = {
      Layer.MEMORY: ["Document", "Passage"],
      Layer.KNOWLEDGE: ["Fact", "Claim"],
  }
  ```

- [ ] Implement `layer_labels(layers: list[Layer]) -> str`:
  - Raise `ValueError` if any layer is not in `_LAYER_LABEL_MAP`
  - Return `" OR ".join(label for layer in layers for label in _LAYER_LABEL_MAP[layer])`

- [ ] Add three layer-filtered query constants that accept a `$label_filter` parameter:

  ```python
  RUN_LEIDEN_SCOPED = """
  CALL igraphalg.community_leiden("CPM", null, $gamma, 0.01, null, 2, null)
  YIELD node, community_id
  WITH node, community_id
  WHERE node.silo_id = $silo_id
    AND any(lbl IN labels(node) WHERE lbl IN $node_labels)
  RETURN node.id AS node_id, community_id
  """

  BATCH_CREATE_MEMBER_OF_SCOPED = """
  MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})
  UNWIND $node_ids AS nid
  MATCH (n {id: nid})
  WHERE any(lbl IN labels(n) WHERE lbl IN $node_labels)
  CREATE (n)-[:MEMBER_OF {weight: $weight, created_at: $created_at}]->(c)
  RETURN count(*) as created
  """

  RUN_PAGERANK_SCOPED = """
  CALL pagerank.get()
  YIELD node, rank
  WITH node, rank
  WHERE any(lbl IN labels(node) WHERE lbl IN $node_labels)
    AND node.silo_id = $silo_id
  RETURN node.id AS node_id, rank
  """
  ```

- [ ] Export all three in `__all__`
- [ ] Run tests: `uv run pytest tests/test_clustering_scope.py -v` — all four must PASS

```bash
uv run pytest tests/test_clustering_scope.py -v
```

---

### Step 3 — Write failing tests for `run_clustering` signature

**File:** `tests/test_clustering_scope.py` (extend)

- [ ] Add `test_run_clustering_accepts_target_layers` — instantiate a `ClusteringService` with
  mocked deps, call `run_clustering(silo_id="s", job=..., target_layers=[Layer.KNOWLEDGE])` and
  assert it does not raise `TypeError`. (Use `AsyncMock` for `_memgraph`; mock `_job_store.save`.)
- [ ] Add `test_run_clustering_default_is_knowledge` — patch `detect_communities` to return `[]`,
  call `run_clustering` without `target_layers`, capture the `gamma` param passed to
  `detect_communities`, confirm no `TypeError`.
- [ ] Run tests: must FAIL (signature not yet updated)

```bash
uv run pytest tests/test_clustering_scope.py -v
```

---

### Step 4 — Update `ClusteringService.run_clustering` signature and query dispatch

**File:** `src/context_service/clustering/service.py`

- [ ] Add import at top: `from primitives.protocols import Layer`
- [ ] Add import: `from context_service.clustering.queries import layer_labels, RUN_LEIDEN_SCOPED, BATCH_CREATE_MEMBER_OF_SCOPED, RUN_PAGERANK_SCOPED`
- [ ] Change `run_clustering` signature:

  ```python
  async def run_clustering(
      self,
      silo_id: str,
      job: ClusteringJob,
      target_layers: list[Layer] | None = None,
  ) -> None:
  ```

- [ ] At the top of `run_clustering`, resolve the label list:

  ```python
  effective_layers = target_layers if target_layers is not None else [Layer.KNOWLEDGE]
  node_labels = layer_labels(effective_layers).split(" OR ")
  ```

- [ ] Pass `node_labels` through to `detect_communities`:

  ```python
  assignments = await self.detect_communities(silo_id, gamma, node_labels)
  ```

- [ ] Update `detect_communities` signature:

  ```python
  async def detect_communities(
      self, silo_id: str, gamma: float, node_labels: list[str]
  ) -> list[dict[str, Any]]:
  ```

  Body: use `RUN_LEIDEN_SCOPED` with `{"gamma": gamma, "silo_id": silo_id, "node_labels": node_labels}`.

- [ ] Pass `node_labels` to `build_hierarchy` and store it on the instance for the duration of the
  job, or thread it as a parameter. Prefer threading it as a parameter to avoid shared mutable
  state. Update `build_hierarchy` signature:

  ```python
  async def build_hierarchy(
      self,
      silo_id: str,
      level_assignments: dict[ClusterLevel, list[dict[str, Any]]],
      node_labels: list[str],
  ) -> list[Cluster]:
  ```

  Inside `build_hierarchy`, replace `queries.BATCH_CREATE_MEMBER_OF` with
  `BATCH_CREATE_MEMBER_OF_SCOPED` and add `"node_labels": node_labels` to the params dict.

- [ ] Update `update_importance` signature:

  ```python
  async def update_importance(self, silo_id: str, node_labels: list[str]) -> None:
  ```

  Replace `queries.RUN_PAGERANK` with `RUN_PAGERANK_SCOPED` and add `"node_labels": node_labels`.

- [ ] Propagate `node_labels` through the `run_clustering` call chain:
  `detect_communities` -> `build_hierarchy` -> `update_importance`.

- [ ] Remove the old TODO comment inside `run_clustering` (the one referencing EAG scoping).

- [ ] Run tests: `uv run pytest tests/test_clustering_scope.py -v` — all must PASS

```bash
uv run pytest tests/test_clustering_scope.py -v
```

---

### Step 5 — Update `clear_and_build_hierarchy_atomic` to accept `node_labels`

**File:** `src/context_service/clustering/service.py`

- [ ] Update `clear_and_build_hierarchy_atomic` signature:

  ```python
  async def clear_and_build_hierarchy_atomic(
      self,
      silo_id: str,
      level_assignments: dict[ClusterLevel, list[dict[str, Any]]],
      node_labels: list[str] | None = None,
  ) -> list[Cluster]:
  ```

- [ ] Default `node_labels` to `["Fact", "Claim"]` when `None`.
- [ ] Replace the `queries.BATCH_CREATE_MEMBER_OF` reference inside the atomic method with
  `BATCH_CREATE_MEMBER_OF_SCOPED` and add `"node_labels": node_labels` to its params dict.

- [ ] Run full test suite: `uv run pytest tests/ -v --ignore=tests/test_clustering_asset.py`
  (skip the Dagster asset test only if it needs live resources — check first).

```bash
uv run pytest tests/ -v
```

---

### Step 6 — Verify types pass

- [ ] Run `just check` (ruff + mypy strict)
- [ ] Fix any type errors (common: `list[str] | None` needs `if node_labels is None` guard before
  indexing, `list[Layer]` needs `Sequence[Layer]` if mypy complains about variance)

```bash
just check
```

---

### Step 7 — Regression: existing clustering asset test still passes

**File:** `tests/test_clustering_asset.py`

The Dagster asset test mocks `asyncio.run` wholesale, so it is insulated from the signature
changes. Confirm it still passes:

```bash
uv run pytest tests/test_clustering_asset.py -v
```

- [ ] All existing tests green

---

### Step 8 — Update the Dagster asset to pass `target_layers`

**File:** `src/context_service/pipelines/assets/clustering.py`

- [ ] Find the call site where `run_clustering` (or `clear_and_build_hierarchy_atomic`) is invoked.
- [ ] Ensure it passes `target_layers=[Layer.KNOWLEDGE]` explicitly (makes the default visible at
  the call site for future reviewers).
- [ ] Import `Layer` from `primitives.protocols` at the top of that file.

```bash
uv run pytest tests/test_clustering_asset.py -v
just check
```

---

## Acceptance criteria

- `uv run pytest tests/test_clustering_scope.py -v` — all pass
- `uv run pytest tests/ -v` — no regressions
- `just check` — no mypy or ruff errors
- Clustering with default params touches only `Fact` and `Claim` nodes
- Memory-layer nodes (`Document`, `Passage`) are excluded from Leiden input, MEMBER_OF creation,
  and PageRank scoring unless `Layer.MEMORY` is explicitly passed
- `Layer.WISDOM` and `Layer.INTELLIGENCE` passed as `target_layers` raise `ValueError` fast, before
  any Memgraph query is issued
