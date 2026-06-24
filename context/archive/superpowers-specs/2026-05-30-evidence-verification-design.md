# Evidence Verification Design

**Status:** Approved  
**Date:** 2026-05-30  
**Resolves:** GitHub issue #52

## Problem

When agents store claims citing auth-gated sources (Slack, Gmail, Drive, private APIs), the validator cannot:

1. Verify reachability (401/403 without auth)
2. Confirm content matches the claim
3. Detect if the source has been edited or deleted

This makes "evidence" functionally "a URL the agent claims supports this" rather than verified content.

## Solution

Add a verification subsystem to the existing SAGE validator pipeline that fetches evidence via Nango (unified OAuth proxy), hashes content, and detects drift over time.

### Architecture

```
validator pipeline (Dagster)
├── validator_stale_commitment  (existing)
├── validator_contradiction     (existing)
└── validator_evidence_verify   (NEW)
    ├── pending verification: fetch via Nango, hash, update edge
    ├── re-verification: edges older than N days, re-fetch, drift check
    └── raises engagement markers on failure/drift
```

The sync-time `EvidenceValidator` marks auth-gated URIs as `pending` for async verification rather than rejecting them.

## Schema Changes

### CITES Edge Properties

New properties on the CITES relationship (Claim -> Document):

```python
verification_status: Literal["pending", "verified", "drifted", "stale", "unverifiable"]
verified_at: datetime | None          # last successful verification
content_hash: str | None              # sha256 of fetched content
verification_attempts: int            # for backoff on repeated failures
```

**Status definitions:**

| Status | Meaning |
|--------|---------|
| `pending` | Queued for verification, not yet fetched |
| `verified` | Successfully fetched and hashed |
| `drifted` | Re-fetch hash does not match stored hash |
| `stale` | Re-fetch failed (creds revoked, 404, etc) |
| `unverifiable` | No Nango integration for this URI pattern |

## Component Changes

### 1. EvidenceValidator (services/evidence.py)

Current behavior: returns valid/invalid based on HEAD request.

New behavior for `_validate_uri`:

| Response | Action |
|----------|--------|
| 2xx | `valid`, queue for async verification, set edge `verification_status="pending"` |
| 401/403 + matches Nango integration | `valid`, set `pending` (we can fetch with creds) |
| 401/403 + no Nango integration | `valid`, set `unverifiable` |
| Other 4xx/5xx | `invalid` (genuinely broken URL) |

Auth-gated URLs are no longer rejected. They are accepted and queued.

### 2. Nango Integration (new: integrations/nango.py)

```python
NANGO_INTEGRATIONS = {
    "slack.com": "slack",
    "mail.google.com": "gmail",
    "drive.google.com": "google-drive",
    "notion.so": "notion",
    "www.notion.so": "notion",
}

async def verify_via_nango(uri: str, silo_id: str) -> VerifyResult:
    """Fetch content via Nango proxy and return hash."""
    integration = resolve_integration(uri)
    if not integration:
        return VerifyResult(success=False, reason="no_integration")
    
    connection = await nango.get_connection(
        integration=integration,
        connection_id=silo_id,
    )
    if not connection:
        return VerifyResult(success=False, reason="no_connection")
    
    content = await nango.proxy(
        integration=integration,
        connection_id=silo_id,
        endpoint=uri_to_api_endpoint(uri),
    )
    
    return VerifyResult(
        success=True,
        hash=hashlib.sha256(content.encode()).hexdigest(),
    )
```

The `uri_to_api_endpoint` function maps user-facing URLs to API calls:
- Slack archive URL -> `conversations.history` API
- Drive URL -> file fetch API
- Gmail URL -> message fetch API

### 3. Dagster Asset (new: pipelines/assets/validator_evidence_verify.py)

```python
@asset(deps=[...], description="Verify evidence URIs via Nango")
async def validator_evidence_verify(context):
    # Phase 1: Pending verification
    pending_edges = await get_edges_by_status("pending", limit=100)
    for edge in pending_edges:
        result = await verify_via_nango(edge.uri, edge.silo_id)
        if result.success:
            await update_edge(edge, 
                verification_status="verified",
                verified_at=now,
                content_hash=result.hash)
            await maybe_upgrade_source_tier(edge)
        else:
            await increment_attempts(edge)
            if edge.verification_attempts >= MAX_ATTEMPTS:
                await update_edge(edge, verification_status="unverifiable")
                await raise_engagement_marker(edge, "verification_failed")
    
    # Phase 2: Re-verification (drift detection)
    stale_edges = await get_edges_needing_reverify(older_than_days=7)
    for edge in stale_edges:
        result = await verify_via_nango(edge.uri, edge.silo_id)
        if result.success:
            if result.hash == edge.content_hash:
                await update_edge(edge, verified_at=now)
            else:
                await update_edge(edge, verification_status="drifted")
                await raise_engagement_marker(edge, "evidence_drifted")
        else:
            await update_edge(edge, verification_status="stale")
            await raise_engagement_marker(edge, "evidence_stale")
```

**Schedule:** Every 15 minutes (same as other validator assets).

### 4. Nango Connection Management

Customer OAuth flow:
1. Customer initiates connect via Nango's hosted OAuth flow
2. Nango stores tokens, returns `connection_id`
3. We store mapping: `silo_id` -> `connection_id` in Postgres

New table:

```sql
CREATE TABLE nango_connections (
    silo_id UUID PRIMARY KEY REFERENCES silos(id),
    connection_id TEXT NOT NULL,
    integration TEXT NOT NULL,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(connection_id, integration)
);
```

## Error Handling

### Retry and Backoff

| Failure Type | Action |
|--------------|--------|
| Nango timeout / 5xx | Retry next run, increment `verification_attempts` |
| 401/403 from Nango | Creds revoked, mark `stale`, raise marker, stop retrying |
| 404 | Content deleted, mark `stale`, raise marker |
| No integration match | Mark `unverifiable` immediately, no retry |
| Rate limited | Backoff, retry next run |

**Max attempts:** 3. After that, mark `unverifiable` and raise marker.

### Engagement Markers

| Marker | Trigger | Severity |
|--------|---------|----------|
| `evidence_drifted` | Re-fetch hash differs from stored | HIGH |
| `evidence_stale` | Re-fetch failed (404, revoked creds) | MEDIUM |
| `verification_failed` | Max attempts reached, never verified | LOW |

Resolution via existing `dismiss` / `tick` verbs.

## Source Tier Behavior

**On successful verification:**
- If `source_tier` is `unknown` (0.4) -> upgrade to `validated` (0.85)
- If already `validated` or higher -> no change
- Triggers confidence recomputation on the claim

**On drift/stale:**
- No auto-downgrade (engagement marker handles adjudication)

## Data Flow

```
1. Customer connects Slack/Gmail/Drive via Nango OAuth
   -> Nango stores tokens, returns connection_id
   -> We map connection_id to silo_id

2. Agent calls learn(claim, evidence=["https://slack.com/archives/C123/p456"])
   -> EvidenceValidator does HEAD check
   -> 401/403 + matches Nango integration -> accept, verification_status="pending"
   -> Store claim + CITES edge immediately
   -> Return {node_id, evidence_status: "pending_verification"}

3. validator_evidence_verify runs (every 15 min)
   -> Fetch via Nango proxy
   -> Hash content, update edge: verified, verified_at, content_hash
   -> Upgrade source_tier: unknown -> validated

4. Re-verification (7-day cycle)
   -> Re-fetch, compare hash
   -> Match: bump verified_at
   -> Mismatch: drifted + engagement marker

5. Agent recalls claim
   -> If drifted/stale: flag in response
   -> Engagement marker surfaces for resolution
```

## Testing Strategy

| Layer | Scope | Approach |
|-------|-------|----------|
| Unit | Nango client, hash computation, URI resolver | pytest, mock Nango responses |
| Integration | Dagster asset against test graph | pytest + test Memgraph, fake Nango server |
| E2E | Full flow: connect -> learn -> verify -> drift | Nango sandbox + real OAuth (manual) |

## Scope

### In Scope (Phase 1)

- CITES edge schema (verification_status, verified_at, content_hash)
- EvidenceValidator changes (pending status for auth-gated)
- validator_evidence_verify Dagster asset
- Nango proxy client
- Engagement markers for drift/stale
- source_tier upgrade on verification
- nango_connections table

### Out of Scope (Future)

- Custom Nango OAuth UI (use Nango's hosted connect flow)
- Per-customer integration settings
- Webhook-based real-time verification
- Field-level hashing for structured documents

## Effort Estimate

| Task | Days |
|------|------|
| CITES schema + EvidenceValidator changes | 0.5 |
| Nango client + URI resolver | 1 |
| Dagster asset (pending + re-verify) | 1 |
| Engagement marker wiring | 0.5 |
| Tests | 1 |
| **Total** | **4** |

## Dependencies

- Nango account (self-hosted or cloud)
- Nango integrations configured: Slack, Gmail, Google Drive, Notion
