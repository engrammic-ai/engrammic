# Clustering Removal Cleanup

**Status:** Planned  
**Context:** CITE v2 schema removes clustering (Leiden, PageRank, `:Cluster` nodes, `:MEMBER_OF` edges)  
**Blocker:** None — stubs in place, runtime safe

## Background

v2 schema simplifies from 15+ nodes to 5 nodes. Clustering was used for belief synthesis (group Facts into Clusters, synthesize Belief when density threshold met). v2 replaces this with direct `SYNTHESIZED_FROM` edges from Beliefs to source Facts.

Current state: all cluster-related queries stubbed to return empty results. No runtime failures, but dead code remains.

## Files to clean up

### 1. Delete entirely (dead modules)

| File | Reason |
|------|--------|
| `src/context_service/clustering/` | Entire directory — Leiden, PageRank, cluster queries |
| `src/context_service/db/custodian_read_queries.py` | All queries were cluster-related |

### 2. Remove cluster-related code (partial cleanup)

| File | What to remove |
|------|----------------|
| `src/context_service/engine/revision.py` | `_GET_BELIEF_CLUSTER`, `_GET_FACT_CONTENTS_IN_CLUSTER`, cluster-based revision logic |
| `src/context_service/custodian/proposal_worker.py` | `estimate_cluster_confidence`, `get_cluster_facts`, `get_proposal_candidates` |
| `src/context_service/reactions/tasks.py` | `update_cluster_membership_task` |
| `src/context_service/pipelines/assets/belief_synthesis.py` | Entire asset (or rewrite for v2 synthesis) |
| `src/context_service/db/queries.py` | Cluster stub constants |
| `src/context_service/db/schema.py` | `LABEL_CLUSTER`, cluster-related predicates |

### 3. Update callers

| Caller | Current behavior | v2 behavior |
|--------|-----------------|-------------|
| `custodian/tools.py` | Imports stubbed functions | Remove cluster tool implementations |
| `custodian/visit.py` | Calls `fetch_cluster_member_ids` | Remove cluster visit logic |
| `sage/transactions.py` | References `SYNTHESIS_THRESHOLD` for clusters | Replace with direct fact corroboration |

### 4. Dagster pipeline updates

| Asset/Job | Change |
|-----------|--------|
| `belief_synthesis` | Rewrite or remove — synthesis now triggered by fact corroboration, not cluster density |
| `llm_pattern_detection` | Check if cluster-dependent |
| Custodian sensors | Remove cluster-related triggers |

## New synthesis trigger (v2)

Instead of "cluster reaches N facts", v2 synthesis should trigger on:
- N Facts share high semantic similarity (embedding distance)
- Facts have corroborating evidence (via `CORROBORATES` edges)
- Direct confidence aggregation without cluster intermediary

This is a separate design task — may warrant its own plan.

## Order of operations

1. Merge current v2 schema PR (stubs in place)
2. Delete `clustering/` directory
3. Delete `custodian_read_queries.py`
4. Clean up partial files (remove stubbed functions)
5. Update callers to not import dead code
6. Remove Dagster cluster assets
7. Design + implement v2 synthesis trigger

## Acceptance criteria

- [ ] No references to `:Cluster`, `:MEMBER_OF`, Leiden, PageRank in codebase
- [ ] `just check` passes
- [ ] Tests pass (some tests may need deletion if they tested clustering)
- [ ] v2 synthesis trigger designed and implemented
