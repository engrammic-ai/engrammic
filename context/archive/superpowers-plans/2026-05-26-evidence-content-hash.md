# Evidence Content Hash Specification

**Status:** Draft  
**Date:** 2026-05-26  
**Problem:** Validator agent cannot verify auth-gated external sources (Slack, Gmail, etc.)

## Problem Statement

When agents store claims with evidence from auth-gated sources:

```python
learn("Q2 revenue is $5M", evidence=["https://slack.com/archives/C123/p456"])
```

The validator cannot:
1. Verify the URL is reachable (401/403 without auth)
2. Confirm the content matches the claim
3. Detect if the source has been edited or deleted

This weakens epistemic rigor: "evidence" becomes "a URL the agent claims supports this" rather than "verified content."

## Proposed Solution: Content Hash

Add an optional `content_hash` field to evidence references. Agents hash content at extraction time, creating an audit trail.

### Schema Changes

**Evidence reference format (extended):**

```
# Current
https://slack.com/archives/C123/p456

# Proposed (backward compatible)
https://slack.com/archives/C123/p456#sha256=a1b2c3...
```

Or as structured evidence:

```python
class EvidenceRef:
    uri: str                          # Required
    content_hash: str | None          # sha256 of extracted content
    extracted_at: datetime | None     # When agent fetched content
    extracted_by: str | None          # Agent/connector identity
    snippet: str | None               # First N chars of content (for debugging)
```

### Storage

Option A: Encode in URI fragment (simple, no schema change)
```
https://example.com/doc#sha256=abc123&extracted=2026-05-26T10:00:00Z
```

Option B: Store as edge properties on CITES relationship
```cypher
(claim)-[:CITES {
  content_hash: "sha256:abc123",
  extracted_at: datetime("2026-05-26T10:00:00Z"),
  extracted_by: "agent:custodian"
}]->(document)
```

**Recommendation:** Option B. Edge properties are cleaner, queryable, and don't pollute URIs.

### Validation Flow

```
1. Agent extracts content from external source
2. Agent computes sha256(content)
3. Agent calls learn() with evidence + content_hash
4. Evidence validator:
   a. Stores hash on CITES edge
   b. If source is re-fetchable later, can compare hashes
   c. Logs hash mismatch as staleness signal
5. Validator agent:
   a. Can query for claims with stale/missing hashes
   b. Can flag claims where source is unfetchable + no hash exists
```

### API Changes

**learn tool (MCP):**

```yaml
parameters:
  evidence:
    type: array
    items:
      oneOf:
        - type: string  # URI (backward compatible)
        - type: object
          properties:
            uri: { type: string }
            content_hash: { type: string, pattern: "^sha256:[a-f0-9]{64}$" }
            extracted_at: { type: string, format: date-time }
            snippet: { type: string, maxLength: 200 }
```

**Example call:**

```python
learn(
    claim="Q2 revenue projection is $5M",
    evidence=[
        {
            "uri": "https://slack.com/archives/C123/p456",
            "content_hash": "sha256:a1b2c3d4...",
            "extracted_at": "2026-05-26T10:30:00Z",
            "snippet": "Based on current pipeline, we're projecting $5M..."
        }
    ],
    source="external",
    confidence=0.8
)
```

### Validator Agent Changes

New validation checks:

| Check | Severity | Action |
|-------|----------|--------|
| Evidence URI unreachable + no hash | Warning | Flag as unverifiable |
| Evidence URI reachable + hash mismatch | Error | Mark claim as potentially stale |
| Evidence URI reachable + hash match | Pass | High confidence |
| Evidence URI unreachable + hash exists | Info | Audit trail preserved |

### Migration

- Existing evidence refs remain valid (no hash = legacy)
- New claims from connectors should include hash
- Backfill job can attempt to hash fetchable URIs

## Scope

**In scope:**
- Schema for content_hash on CITES edges
- API extension for structured evidence
- Validator checks for hash presence/match

**Out of scope (future):**
- Connector SDK for auth-gated sources
- Real-time content change detection
- Field-level hashing for structured documents

## Effort Estimate

- Schema + API changes: 1 day
- Validator integration: 0.5 day
- Tests: 0.5 day
- **Total: 2 days**

## Open Questions

1. Should snippet be stored? Useful for debugging but adds storage.
2. Max snippet length? 200 chars seems reasonable.
3. Should we support multiple hash algorithms? Start with sha256 only.
