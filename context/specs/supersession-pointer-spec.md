# Supersession Pointer Specification

> **Status:** Draft  
> **Related:** `context/plans/2026-05-19-supersession-head-pointer.md` (implementation plan)

## Problem

Finding the "live tip" of a supersession chain currently requires O(n) edge traversal:

```cypher
MATCH path = (tip)-[:SUPERSEDES*0..]->(input)
WHERE NOT ()-[:SUPERSEDES]->(tip)
RETURN tip
```

For chains of depth 10+, this becomes a performance bottleneck in retrieval paths.

## Solution

Add denormalized pointers (`tail_id`, `head_id`) to enable O(1) chain head resolution.

## Data Model

### Node Properties

| Property | Type | Set On | Mutable | Description |
|----------|------|--------|---------|-------------|
| `tail_id` | string (UUID) | Non-tail nodes | No | Points to oldest node in chain |
| `head_id` | string (UUID) | Tail node only | Yes | Points to current head of chain |

### Invariants

1. **Tail uniqueness:** Each chain has exactly one tail (the oldest superseded node)
2. **Head uniqueness:** Each chain has exactly one head (the current live tip)
3. **Tail immutability:** Once `tail_id` is set, it never changes
4. **Head mutability:** `head_id` on the tail is updated on each chain extension
5. **Mutual exclusivity:** A node has either `tail_id` OR `head_id`, never both
6. **Standalone nodes:** Nodes not in any chain have neither property set

### Chain Structure Examples

**Simple chain (C supersedes B supersedes A):**
```
Node A: head_id = C, tail_id = null    (tail)
Node B: head_id = null, tail_id = A    (middle)
Node C: head_id = null, tail_id = A    (head)

Edges: C -[SUPERSEDES]-> B -[SUPERSEDES]-> A
```

**Standalone node:**
```
Node X: head_id = null, tail_id = null
```

## Resolution Algorithm

```
resolve_current_head(input_id):
    node = get(input_id)
    
    # Case 1: Node is the tail (has head_id)
    if node.head_id is not null:
        return node.head_id
    
    # Case 2: Node is in a chain (has tail_id)
    if node.tail_id is not null:
        tail = get(node.tail_id)
        return tail.head_id
    
    # Case 3: Standalone node (no pointers)
    return input_id
```

**Complexity:** O(1) - at most 2 indexed lookups.

## Write Operations

### Single Supersession

When `new` supersedes `old`:

```
1. Derive tail_id:
   - If old.tail_id exists: tail_id = old.tail_id (old was head of existing chain)
   - Else: tail_id = old.id (old becomes tail of new chain)

2. Set new.tail_id = tail_id

3. Update tail's head_id:
   - Match tail node by tail_id
   - Set tail.head_id = new.id
```

### Multi-Target Supersession (CRYSTALLIZE edge case)

When `new` supersedes multiple targets (e.g., commitment supersedes two existing commitments sharing ABOUT targets):

**Design decision: Separate chains, no merge**

Each target remains the tail of its own chain. The new node gets `tail_id` pointing to the FIRST target encountered (deterministic via ORDER BY). Other targets get their `head_id` updated to point to `new`.

```
Before:
  Chain 1: B -> A  (A.head_id=B, B.tail_id=A)
  Chain 2: D -> C  (C.head_id=D, D.tail_id=C)

After (E supersedes B and D):
  Chain 1: E -> B -> A  (A.head_id=E, B.tail_id=A, E.tail_id=A)
  Chain 2: E -> D -> C  (C.head_id=E, D.tail_id=C)
  
  Note: E.tail_id points to A (first by ORDER BY), but E is head of BOTH chains.
  Resolution from C: C.head_id=E (correct)
  Resolution from A: A has head_id=E (correct)
```

**Trade-off:** This means `tail_id` on the head node is not guaranteed to be the tail of ALL chains it heads. However, resolution still works because we look up `head_id` from the input's tail, not from the head's tail.

**Alternative considered:** Merge chains into single chain with earliest tail. Rejected because:
- Requires rewriting `tail_id` on all nodes of merged chains (O(n) write)
- Complicates provenance (artificial ordering between unrelated chains)

## Historical Queries (as_of)

Pointers only track the CURRENT head. Historical queries (`as_of < now`) must fall back to chain traversal:

```cypher
// Fast path: pointers (only valid when as_of = now or head was valid at as_of)
WITH input, COALESCE(input.tail_id, input.id) AS tail_id
MATCH (tail) WHERE tail.id = tail_id
WITH COALESCE(tail.head_id, input.id) AS pointer_head_id
MATCH (head) WHERE head.id = pointer_head_id
  AND head.valid_from <= $as_of
  AND (head.valid_to IS NULL OR head.valid_to > $as_of)
RETURN head  // Fast path succeeded

// Slow path: chain walk (when pointer head is not valid at as_of)
MATCH path = (tip)-[:SUPERSEDES*0..]->(input)
WHERE tip.valid_from <= $as_of
  AND (tip.valid_to IS NULL OR tip.valid_to > $as_of)
RETURN tip ORDER BY tip.valid_from DESC LIMIT 1
```

## Affected Queries

| Query | Location | Change |
|-------|----------|--------|
| `CREATE_CROSS_NODE_SUPERSEDES` | `engine/queries.py` | Set `tail_id`, update tail's `head_id` |
| `CREATE_BELIEF_SUPERSEDES` | `db/queries.py` | Set `tail_id`, update tail's `head_id` |
| `CRYSTALLIZE_TO_COMMITMENT` | `db/queries.py` | Set `tail_id`, update tail's `head_id` (multi-target) |
| `FILTER_SUPERSEDED_AT` | `engine/queries.py` | Add pointer fast-path with chain-walk fallback |
| `GET_NODE_AS_OF` | `engine/queries.py` | Consider pointer fast-path |
| `GET_NODE_VERSION_CHAIN` | `engine/queries.py` | No change (still walks edges for full history) |

## Backfill

Existing chains need pointers populated. Backfill script:

1. Find all tails: nodes with incoming SUPERSEDES but no outgoing SUPERSEDES, and no `head_id` set
2. For each tail, walk to head via SUPERSEDES edges
3. Set `tail.head_id = head.id`
4. Set `node.tail_id = tail.id` for all non-tail nodes in chain

**Idempotency:** Safe to re-run; checks for existing pointers before setting.

**Concurrency:** Run during low-traffic window. New supersessions during backfill will set their own pointers correctly.

## Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Missing `tail_id` on chain member | `resolve_current_head` returns `input_id` instead of actual head | Backfill or chain-walk fallback |
| Stale `head_id` (tail points to old head) | `head.valid_to` is set (head was superseded) | Chain-walk fallback; indicates bug in write path |
| Deleted tail node | `tail_id` points to non-existent node | Chain-walk fallback; log warning |
| Orphaned pointer (node deleted mid-chain) | Resolution returns null | Return input_id as fallback |

## Testing Requirements

1. **Unit tests:**
   - Single supersession sets correct pointers
   - Chain extension (C -> B -> A) updates tail's head_id
   - Multi-target supersession handles both targets
   - Standalone node resolution returns self
   - Historical query falls back to chain walk

2. **Integration tests:**
   - Backfill script on existing chains
   - Concurrent supersession + resolution
   - Mixed pointer/no-pointer nodes (partial backfill)

## Performance Targets

| Operation | Before | After |
|-----------|--------|-------|
| `resolve_current_head` (chain depth 10) | ~50ms | <5ms |
| `FILTER_SUPERSEDED_AT` (100 nodes, avg depth 5) | ~250ms | <50ms |
| Supersession write overhead | - | +2 property sets |

## Open Questions

1. **Index on pointers?** Probably not needed - we lookup by `id` (already indexed), then read `tail_id`/`head_id` properties. No queries filter BY these properties.

2. **Expose in API?** Currently internal optimization. Could expose `chain_head_id` in node response for transparency, but adds coupling.

3. **Primitives integration?** Keep in context-service only (storage optimization) or add to primitives protocol? Recommendation: context-service only until proven stable.
