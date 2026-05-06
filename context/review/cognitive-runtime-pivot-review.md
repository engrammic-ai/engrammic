# Adversarial Review: Cognitive Runtime Pivot Plan

**Date**: 2026-05-07
**Reviewer**: Automated adversarial agent (Sonnet)
**Verdict**: NEEDS REVISION

## Overview

The plan at `context/plans/cognitive-runtime-pivot.md` proposes four changes to shift from "epistemically-aware document store" to "cognitive runtime." This review found structural issues that prevent correct implementation.

---

## Credible Concerns

### 1. CRITICAL: Graph topology does not exist

**What**: Tasks 3 and 4 assume this traversal path:
```
Commitment -> DERIVED_FROM -> ReasoningChain -> PART_OF_SESSION -> ReasoningSession
```

This path does not exist in the codebase. The wisdom-layer Commitment written by `commit_belief()` creates `ABOUT` edges to referenced nodes, not `DERIVED_FROM` edges to ReasoningChains. The session attachment (`PART_OF_SESSION`) is only written for ReasoningChain nodes at the intelligence layer.

**Impact**: `context_belief_state` and sync conflict detection queries would return zero rows on every call, silently appearing to work while doing nothing.

**Fix options**:
1. Wire `commit_belief()` to create `DERIVED_FROM` edge to active chain (requires `chain_id` parameter)
2. Add `session_id` property directly to Commitment nodes
3. Reconsider whether wisdom layer is the right place for session-scoped belief state (see architectural note below)

### 2. HIGH: Conflict detection assumes Entity nodes

**What**: The `DETECT_CONFLICTING_COMMITMENTS` query does:
```cypher
MATCH (new)-[:ABOUT]->(e:Entity)
```

But `commit_belief()` writes `ABOUT` edges to whatever node_ids the agent passes — typically Document or Claim nodes, not Entity nodes.

**Impact**: Query silently returns no conflicts because `:Entity` label constraint filters out all targets.

**Fix**: Remove `:Entity` label constraint:
```cypher
MATCH (new)-[:ABOUT]->(e)
```

Or enforce that `about` targets must be Entity nodes in `commit_belief()`.

### 3. MEDIUM: Tool surface expansion contradicts consolidation

**What**: Plan adds 3 new tools (4 -> 7): `context_load`, `context_belief_state`, `context_update_belief`.

**Impact**: Increases API surface, breaks agents assuming 4-tool contract, requires MCP client repo update.

**Fix**: Fold `context_load` into `context_recall` with `include_content: true` flag. This is essentially what it does anyway.

### 4. MEDIUM: `context_update_belief` cannot change content

**What**: The Cypher does `content: old.content` with no `new_content` parameter. Agents can only update confidence and reason, not belief text.

**Impact**: If a belief is factually wrong (not just low confidence), the agent cannot correct it.

**Fix**: Add optional `content` parameter, or rename to `context_recalibrate_belief` to be honest about the limitation.

### 5. LOW: Index task is a no-op

**What**: Task 6 proposes composite indexes that Memgraph cannot create. The relevant single-property indexes already exist.

**Impact**: No functional impact, but false rationale for < 30ms target.

**Fix**: Remove Task 6 or rewrite to only add missing single-property indexes.

---

## Architectural Note: Working Beliefs vs Commitments

The plan conflates two concepts:

- **Working beliefs**: Session-scoped, mutable, what the agent currently thinks during this reasoning session. These should be ephemeral and discardable.

- **Commitments**: Durable stances the agent has crystallized and is willing to stand behind. These get supersession-tracked and potentially validated by the Custodian.

The cognitive runtime needs working beliefs for live epistemic state. The wisdom layer provides commitments for durable stances. The plan asks the wisdom layer to do both, which is why the topology doesn't exist — it was never designed for session-scoped state.

**Recommendation**: Consider whether `ReasoningChain` at the intelligence layer should hold working beliefs, with promotion to wisdom-layer `Commitment` as an explicit crystallization step.

---

## Non-issues

- **< 30ms target**: Achievable with LIMIT 10 and silo_id filtering. The concern is semantic (query returns nothing), not performance.
- **Supersession pattern**: Consistent with existing `CREATE_BELIEF_SUPERSEDES` usage in codebase.
- **reflection_suggested heuristic**: Simple and correct — returns true when contradictions exist.

---

## Summary

The plan cannot be implemented as written. The core queries assume a graph topology that does not exist. Before proceeding:

1. Decide how wisdom-layer Commitments connect to ReasoningSessions (or whether they should)
2. Fix the `:Entity` label constraint in conflict detection
3. Consider folding `context_load` into `context_recall`
4. Decide whether `context_update_belief` should allow content changes
