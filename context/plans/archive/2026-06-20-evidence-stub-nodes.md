# Evidence Stub Nodes for file:// and urn:// URIs

**Date:** 2026-06-20
**Status:** Ready
**Effort:** 30 min

## Problem

When `learn()` is called with `file://` or `urn:` evidence refs, the evidence passes validation but **no stub node is created** and **no `DERIVED_FROM` edge is created**. The claim stores successfully but has a broken provenance chain.

**Location:** `src/context_service/services/evidence.py:89-99`

```python
elif ref.startswith("file://"):
    return EvidenceResult(
        status="valid",
        confidence=0.9,
        reason="File URI accepted (local validation skipped)",
        # BUG: no node_id returned!
    )
elif ref.startswith("urn:"):
    return EvidenceResult(
        status="valid",
        confidence=0.85,
        reason="URN accepted (external validation skipped)",
        # BUG: no node_id returned!
    )
```

**Downstream effect:** In `context_store.py:407-408`:
```python
if ev_result.node_id:
    evidence_nodes.append(ev_result.node_id)
```

No node_id means no entry in `evidence_nodes`, which means `store_claim` receives empty `evidence_node_ids` and `_create_derived_from_edges` is never called.

HTTP(S) URIs work correctly because `_validate_uri` calls `_upsert_document_for_uri` which creates a stub Document node and returns its ID.

## Solution

Create stub Document nodes for `file://` and `urn:` refs, same pattern as HTTP.

### Changes

**0. Add `urn:` to MCP model allow-list:**

`urn:` is currently rejected at `models/mcp.py:96-108` before reaching the evidence validator. Add it:

```python
# models/mcp.py line 84-88
@property
def is_uri(self) -> bool:
    return (
        self.ref.startswith("http://")
        or self.ref.startswith("https://")
        or self.ref.startswith("file://")
        or self.ref.startswith("urn:")  # ADD
    )

# models/mcp.py line 99-107
@field_validator("ref")
@classmethod
def validate_ref_format(cls, v: str) -> str:
    if not (
        v.startswith("node:")
        or v.startswith("http://")
        or v.startswith("https://")
        or v.startswith("file://")
        or v.startswith("urn:")  # ADD
    ):
        raise ValueError(
            "Evidence ref must be node:<uuid> or a URI (http://, https://, file://, urn:)"
        )
    return v
```

**1. Add `_upsert_stub_for_local_ref` helper:**

```python
async def _upsert_stub_for_local_ref(
    self, uri: str, silo_id: str, ref_type: str
) -> str:
    """Create or find a stub Document node for a local/external reference."""
    from uuid import NAMESPACE_URL, uuid5

    # CRITICAL: Include silo_id in hash to ensure silo isolation.
    # Without this, two silos citing the same URI would generate the same doc_id,
    # but MERGE would fail to match (different silo_id), creating duplicate nodes.
    doc_id = str(uuid5(NAMESPACE_URL, f"{silo_id}:{uri}"))
    
    query = """
    MERGE (d:Node:Document {id: $doc_id, silo_id: $silo_id})
    ON CREATE SET 
        d.uri = $uri,
        d.stub = true,
        d.ref_type = $ref_type,
        d.created_at = datetime()
    RETURN d.id AS id
    """
    await self._store.execute_query(
        query,
        {"doc_id": doc_id, "silo_id": silo_id, "uri": uri, "ref_type": ref_type},
    )
    return doc_id
```

**2. Update file:// handling (~line 89):**

```python
elif ref.startswith("file://"):
    node_id = await self._upsert_stub_for_local_ref(ref, silo_id, "file")
    return EvidenceResult(
        status="valid",
        node_id=node_id,
        confidence=0.9,
        reason="File URI accepted (stub created, local validation skipped)",
    )
```

**3. Update urn: handling (~line 94):**

```python
elif ref.startswith("urn:"):
    node_id = await self._upsert_stub_for_local_ref(ref, silo_id, "urn")
    return EvidenceResult(
        status="valid",
        node_id=node_id,
        confidence=0.85,
        reason="URN accepted (stub created, external validation skipped)",
    )
```

### Stub Node Properties

| Property | Value |
|----------|-------|
| `id` | Deterministic UUID5 from URI |
| `silo_id` | Caller's silo |
| `uri` | Original reference |
| `stub` | `true` (marks as unverified placeholder) |
| `ref_type` | `"file"` or `"urn"` |
| `created_at` | Timestamp |

The `stub=true` flag allows:
- `trace()` to show these as terminal sources with a warning
- Future content extraction to identify unfetched stubs
- Provenance queries to distinguish verified vs placeholder evidence

### Provenance Query Update

`PROVENANCE_ROOT_SOURCES` already returns stub nodes correctly. The `trace` tool output should surface the `stub` flag so agents know the source wasn't verified.

Check `trace.py` — if it doesn't surface `stub`, add it to the response.

## Testing

```python
# test_evidence.py
async def test_file_uri_creates_stub():
    validator = EvidenceValidator(store)
    result = await validator.validate("file:///path/to/doc.md", silo_id)
    assert result.status == "valid"
    assert result.node_id is not None
    # Verify node exists
    nodes = await store.execute_query(
        "MATCH (n {id: $id}) RETURN n.stub AS stub",
        {"id": result.node_id}
    )
    assert nodes[0]["stub"] is True

async def test_urn_creates_stub():
    validator = EvidenceValidator(store)
    result = await validator.validate("urn:isbn:0-123-45678-9", silo_id)
    assert result.status == "valid"
    assert result.node_id is not None

async def test_file_uri_creates_derived_from_edge():
    """Critical: verify the full provenance chain, not just stub creation."""
    result = await context_learn(
        content="Test claim",
        evidence=["file:///path/to/source.md"],
        silo_id=silo_id,
    )
    claim_id = result["node_id"]
    # Verify DERIVED_FROM edge exists
    edges = await store.execute_query(
        """
        MATCH (c:Claim {id: $claim_id})-[:DERIVED_FROM]->(d:Document {stub: true})
        RETURN d.uri AS uri
        """,
        {"claim_id": claim_id}
    )
    assert len(edges) == 1
    assert edges[0]["uri"] == "file:///path/to/source.md"
```

### URI Normalization Decision

**Do NOT normalize URIs** (e.g., stripping fragments). Rationale:
- `file:///doc.md#line42` and `file:///doc.md#line100` are semantically distinct references
- The agent is citing a specific location, not the whole document
- If we normalized, `trace()` would lose the specific citation context

**Acknowledged tradeoff:** When `trace()` queries a belief derived from both `file:///api.md#line42` and `file:///api.md#line100`, you get two DERIVED_FROM branches for what is semantically one source document. This fan-out is intentional (citation granularity > provenance simplicity), but if it creates noise in trace output, consider grouping by base URI in the presentation layer, not the storage layer.

If this causes issues in practice, revisit. For now, preserve citation granularity.

## Failure Handling

**Stub creation failure should hard-fail the write.**

A claim whose evidence node silently failed to persist is an unprovenanced claim masquerading as evidenced — exactly the current bug. Better to reject than store a lie. The validator should raise/return `invalid_evidence` if `_upsert_stub_for_local_ref` fails.

This differs from semantic dedup, which should degrade gracefully (a dedup miss creates a duplicate the Custodian catches later; a dedup crash must never fail a write).

## Rollout

1. Deploy — existing claims with broken provenance remain broken
2. No migration needed — new claims will have proper edges
3. Optional: backfill script to find claims with `evidence` property containing file:// or urn:// and create missing edges

## Success Criteria

- `learn(claim="X", evidence=["file:///path/to/source.md"])` creates a Claim with a `DERIVED_FROM` edge to a stub Document
- `trace(claim_id)` returns the stub as a root source with `stub: true`
- No regression on HTTP(S) evidence (already working)

## Open Questions (Backlog)

1. **Orphan stub cleanup on forget():** If agent `forget()`s a claim that DERIVED_FROM a stub, should the stub be deleted? Currently no — stubs may be referenced by multiple claims. Consider adding a cleanup pass to Groundskeeper that deletes stubs with zero incoming edges.
