# Q/A Invariants

Universal checks applied to every scenario. These must pass regardless of scenario-specific criteria.

## 1. Silo Isolation

**Check:** No data from other silos appears in queries.

**How to verify:**
```
context_recall(mode="flat", layer="memory", limit=100, silo_id="<test-silo>")
```

All returned nodes must have matching silo_id.

**Fail condition:** Any node with different silo_id in results.

## 2. Provenance Chains Valid

**Check:** All nodes are traceable to a source.

**How to verify:**
For a sample of nodes:
```
context_admin(action="provenance", node_id="<node>", silo_id="<test-silo>")
```

Chain should reach a terminal node (Document, Observation, or external source).

**Fail condition:** Provenance returns empty or error for any node.

## 3. No Errors

**Check:** No MCP tool calls returned errors during the scenario.

**How to verify:**
- Review worker reports for error mentions
- Query nodes and check for error states

**Fail condition:** Any error response from MCP tools (excluding expected validation errors in negative test cases).

## 4. No Orphan Nodes

**Check:** All created nodes are reachable.

**How to verify:**
```
context_recall(mode="flat", layer="<layer>", limit=100, silo_id="<test-silo>")
```

Compare node count with worker-reported created nodes.

**Fail condition:** Nodes created but not retrievable via recall.
