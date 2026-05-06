# Plan: E2E Test Scenarios

**Status:** Draft 2026-05-01
**Goal:** Implement four E2E test scenarios covering meta-memory, recall quality, and MCP protocol validation.

## Scenarios

### Scenario 1: Provenance Chain Integrity

**Tests:** After ingest + extraction, provenance queries return complete chains to source documents.

**File:** `tests/integration/test_provenance_e2e.py`

**Flow:**
1. Store document via `context_remember` or direct service call
2. Create claim with REFERENCES edge via `context_assert`
3. Call `context_provenance` on the claim
4. Assert chain includes the source document
5. Assert root_sources contains the document

**Assertions:**
- Chain length > 0
- Chain contains Document layer node
- REFERENCES edge is traversed (not just DERIVED_FROM)

---

### Scenario 2: Reflection Round-Trip

**Tests:** MetaObservations stored via `context_reflect` are retrievable via `context_get_reflections`.

**File:** `tests/integration/test_reflection_e2e.py`

**Flow:**
1. Create a claim or fact node
2. Call `context_reflect` with observation about that node
3. Call `context_get_reflections` on the same node
4. Assert reflection is returned with correct properties

**Assertions:**
- Reflection count matches stored count
- observation_type preserved
- about relationship correct
- agent_id captured

---

### Scenario 3: Recall Quality with Ground Truth

**Tests:** Query returns semantically relevant results ranked correctly.

**File:** `tests/integration/test_recall_quality.py`

**Flow:**
1. Seed corpus with 5-10 documents of known semantic categories
2. Run queries with expected relevant/irrelevant docs
3. Assert relevant docs rank higher than irrelevant
4. Assert relevance_score thresholds

**Test Cases:**
- ML query returns ML docs above Python docs
- Rare-term query (proper noun) returns exact match
- Freshness affects ranking (recent > stale for equal relevance)

**Assertions:**
- Precision@3 for each query
- Relevant doc in top K
- Irrelevant doc not in top K (or ranked lower)

---

### Scenario 4: MCP Protocol Validation

**Tests:** Tools work via actual FastMCP JSON-RPC, not just direct function calls.

**File:** `tests/integration/test_mcp_protocol.py`

**Approach Options:**
- **Option A:** Use FastMCP's test client (if available)
- **Option B:** Spawn server in subprocess, connect via stdio
- **Option C:** HTTP test client against SSE endpoint

**Flow:**
1. Create MCP server instance
2. Send JSON-RPC tool call
3. Verify response structure
4. Verify error handling (invalid silo, missing params)

**Assertions:**
- Response follows MCP spec
- Error codes correct
- Auth context propagated

---

## Implementation Order

1. **Provenance E2E** (S) — validates REFERENCES fix we just shipped
2. **Reflection E2E** (S) — validates new `context_get_reflections` tool
3. **Recall Quality** (M) — needs corpus seeding, more assertions
4. **MCP Protocol** (M) — needs research on FastMCP test patterns

## Shared Fixtures Needed

```python
# tests/integration/conftest.py additions

@pytest.fixture
async def context_service(memgraph_client, qdrant_client, redis_client):
    """Fully wired ContextService for E2E tests."""
    from context_service.services.context import ContextService
    return ContextService(
        memgraph=memgraph_client,
        qdrant=qdrant_client,
        cache=redis_client,
        embedding=mock_embedding_service(),  # or real for recall tests
    )

@pytest.fixture
def scope_context(unique_org_id, unique_silo_id):
    """ScopeContext for E2E tests."""
    return ScopeContext(org_id=unique_org_id, silo_id=unique_silo_id)
```

## Files to Create

| File | Purpose |
|------|---------|
| `tests/integration/test_provenance_e2e.py` | Scenario 1 |
| `tests/integration/test_reflection_e2e.py` | Scenario 2 |
| `tests/integration/test_recall_quality.py` | Scenario 3 |
| `tests/integration/test_mcp_protocol.py` | Scenario 4 |
| `tests/integration/conftest.py` | Add shared fixtures |

## Done Criteria

- [ ] All four scenario files created
- [ ] Tests pass with live docker stack
- [ ] Tests skip gracefully without stack
- [ ] `just test-integration` runs all E2E scenarios
- [ ] Each scenario has at least 2 test cases
