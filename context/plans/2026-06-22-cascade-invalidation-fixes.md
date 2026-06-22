# Cascade Invalidation Fixes Implementation Plan

Date: 2026-06-22
Status: Draft

## Goal

Patch three critical architectural flaws in the SAGE downstream cascade logic (`cascade_staleness` in `src/context_service/sage/transactions.py` and related functions) that can leave the knowledge graph in an inconsistent state during concurrent updates or deep reasoning chains.

## Identified Issues

During a deep-dive review of Engrammic's causal invalidation logic (comparing it to Kumiho's `AnalyzeImpact`), the following edge cases were identified:

### 1. Partial Invalidation (No Transaction Rollback)
If an intermediate node update fails during `cascade_staleness` (e.g., due to a database lock or transient failure), the exception is caught but does not trigger a full transaction rollback. 
* **Impact:** The knowledge graph is left in an inconsistent, partially-invalidated state. Some downstream nodes are marked as stale, while parallel branches falsely remain active because the cascade died halfway through. This severely breaks causal guarantees.

### 2. Hard Depth Limits (No Deferral Queue)
To prevent infinite recursion, the system enforces a `MAX_CASCADE_DEPTH` (currently 10). When this limit is reached, the system raises a `DepthLimitExceeded` exception and terminates the process synchronously.
* **Impact:** Deeply nested dependency graphs (e.g., >10 hops of reasoning) will perpetually fail to update. 
* **Resolution:** Instead of aborting, the system should push nodes that exceed the depth limit into an async queue (e.g., via Taskiq `CASCADE_STALENESS` events) for background invalidation by another worker.

### 3. O(N) Cycle Detection Performance
Graph cycles are prevented by passing a `visited` tracking collection recursively through the cascade. Currently, this is implemented as a Python `list`.
* **Impact:** Membership lookups are $O(N)$. For broad cascades touching thousands of nodes, this causes severe CPU degradation. 
* **Resolution:** Enforce the use of a `set()` for $O(1)$ membership lookups during cycle-detection traversals.

## Scope

- [ ] Wrap `cascade_staleness` operations in an atomic database transaction (`async with store.transaction():`).
- [ ] Refactor `MAX_CASCADE_DEPTH` handling to emit a deferred `ReactionEvent` (via Taskiq) for nodes at the boundary, rather than raising a hard exception or silently dropping the update.
- [ ] Change the `visited` collection in recursive traversal functions to a `set()`.
- [ ] Review `flag_cascade` in `src/context_service/engine/revision.py` and `causal_invalidation.py` for similar lack of atomicity.

## Risks
- Wrapping large recursive cascades in a single database transaction might hold database locks for too long if the cascade is massive. If this becomes a bottleneck, consider batching the transaction or relying strictly on the event-driven async queue for each depth level.