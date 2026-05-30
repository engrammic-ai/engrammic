# Plan: Evidence Verification via Nango

**Spec:** `docs/superpowers/specs/2026-05-30-evidence-verification-design.md`  
**Resolves:** GitHub #52  
**Effort:** ~4 days  
**Status:** Ready to execute

## Prerequisites

- [ ] Nango account created (self-hosted or cloud)
- [ ] Nango integrations configured: Slack, Gmail, Google Drive, Notion

## Tasks

### Phase 1: Schema + EvidenceValidator (0.5 day)

**1.1 Add CITES edge properties**

File: `src/context_service/db/queries.py`

Add to CITES edge creation queries:
```python
verification_status: str = "pending"
verified_at: datetime | None = None
content_hash: str | None = None
verification_attempts: int = 0
```

**1.2 Add nango_connections table**

New migration:
```sql
CREATE TABLE nango_connections (
    silo_id UUID PRIMARY KEY REFERENCES silos(id),
    connection_id TEXT NOT NULL,
    integration TEXT NOT NULL,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(connection_id, integration)
);
```

**1.3 Update EvidenceValidator**

File: `src/context_service/services/evidence.py`

Change `_validate_uri` behavior:
- 401/403 + matches Nango integration -> return `valid`, mark `pending`
- 401/403 + no integration -> return `valid`, mark `unverifiable`
- Keep other 4xx/5xx as `invalid`

Add helper:
```python
def _has_nango_integration(uri: str) -> bool:
    """Check if URI domain matches a configured Nango integration."""
    ...
```

### Phase 2: Nango Client (1 day)

**2.1 Create Nango client**

New file: `src/context_service/integrations/nango.py`

```python
NANGO_INTEGRATIONS = {
    "slack.com": "slack",
    "mail.google.com": "gmail", 
    "drive.google.com": "google-drive",
    "notion.so": "notion",
    "www.notion.so": "notion",
}

class NangoClient:
    async def get_connection(self, integration: str, connection_id: str) -> Connection | None
    async def proxy(self, integration: str, connection_id: str, endpoint: str) -> str

def resolve_integration(uri: str) -> str | None:
    """Map URI domain to Nango integration name."""

async def verify_via_nango(uri: str, silo_id: str) -> VerifyResult:
    """Fetch content via Nango and return hash."""
```

**2.2 URI to API endpoint mappers**

Per-integration logic to convert user-facing URLs to API calls:

```python
def slack_uri_to_endpoint(uri: str) -> str:
    """https://slack.com/archives/C123/p456 -> conversations.history params"""

def gmail_uri_to_endpoint(uri: str) -> str:
    """Gmail URL -> messages.get params"""

def drive_uri_to_endpoint(uri: str) -> str:
    """Drive URL -> files.get params"""

def notion_uri_to_endpoint(uri: str) -> str:
    """Notion URL -> pages.retrieve or blocks.children"""
```

**2.3 Settings**

File: `src/context_service/config/settings.py`

```python
# Nango
nango_base_url: str = Field(default="https://api.nango.dev")
nango_secret_key: str | None = Field(default=None)
```

### Phase 3: Dagster Asset (1 day)

**3.1 Create validator_evidence_verify asset**

New file: `src/context_service/pipelines/assets/validator_evidence_verify.py`

Two phases:
1. Pending verification: query edges with `verification_status="pending"`, fetch via Nango, update edge
2. Re-verification: query edges with `verified_at` > 7 days old, re-fetch, detect drift

```python
@asset(deps=[...])
async def validator_evidence_verify(context):
    await _verify_pending_edges(context)
    await _reverify_stale_edges(context)
```

**3.2 Graph queries**

File: `src/context_service/db/queries.py`

```python
GET_PENDING_VERIFICATION_EDGES = """
MATCH (c:Claim)-[r:CITES]->(d:Document)
WHERE r.verification_status = 'pending'
RETURN r, c.silo_id as silo_id, d.uri as uri
LIMIT $limit
"""

GET_EDGES_NEEDING_REVERIFY = """
MATCH (c:Claim)-[r:CITES]->(d:Document)
WHERE r.verification_status = 'verified'
AND r.verified_at < datetime() - duration({days: $days})
RETURN r, c.silo_id as silo_id, d.uri as uri
LIMIT $limit
"""

UPDATE_CITES_VERIFICATION = """
MATCH ()-[r:CITES]->()
WHERE id(r) = $edge_id
SET r.verification_status = $status,
    r.verified_at = $verified_at,
    r.content_hash = $content_hash,
    r.verification_attempts = $attempts
"""
```

**3.3 Register asset in pipeline**

File: `src/context_service/pipelines/definitions.py`

Add `validator_evidence_verify` to validator job.

**3.4 Source tier upgrade**

After successful verification, if claim's source_tier is `unknown`:
- Update to `validated`
- Trigger confidence recomputation

### Phase 4: Engagement Markers (0.5 day)

**4.1 Add marker types**

File: `src/context_service/engine/markers.py`

```python
class MarkerType(str, Enum):
    ...
    EVIDENCE_DRIFTED = "evidence_drifted"
    EVIDENCE_STALE = "evidence_stale"
    VERIFICATION_FAILED = "verification_failed"
```

**4.2 Wire markers into Dagster asset**

On drift/stale/failure, call:
```python
await raise_engagement_marker(
    silo_id=silo_id,
    target_id=claim_id,
    marker_type=MarkerType.EVIDENCE_DRIFTED,
    context={"uri": uri, "old_hash": old_hash, "new_hash": new_hash},
)
```

### Phase 5: Tests (1 day)

**5.1 Unit tests**

- `tests/integrations/test_nango.py`: mock Nango responses, test URI resolution, hash computation
- `tests/services/test_evidence.py`: test new validator behavior for 401/403

**5.2 Integration tests**

- `tests/pipelines/test_validator_evidence_verify.py`: test Dagster asset against test Memgraph with fake Nango

**5.3 Test fixtures**

- Fake Nango server (httpx mock)
- Sample URIs for each integration
- Pre-populated CITES edges in various states

## Verification

```bash
just check                    # lint + typecheck
just test -k evidence         # evidence-related tests
just test -k nango            # nango client tests
just test -k validator_evid   # dagster asset tests
```

Manual verification:
1. Start local stack with Nango (or mock)
2. Create a claim with Slack evidence URL
3. Confirm edge created with `verification_status="pending"`
4. Run validator job manually
5. Confirm edge updated to `verified` with hash
6. Modify mock content, re-run
7. Confirm `drifted` status and engagement marker

## Files Changed

| File | Change |
|------|--------|
| `src/context_service/db/queries.py` | CITES edge properties, new queries |
| `src/context_service/services/evidence.py` | Validator behavior for auth-gated |
| `src/context_service/integrations/nango.py` | NEW: Nango client |
| `src/context_service/pipelines/assets/validator_evidence_verify.py` | NEW: Dagster asset |
| `src/context_service/pipelines/definitions.py` | Register new asset |
| `src/context_service/engine/markers.py` | New marker types |
| `src/context_service/config/settings.py` | Nango settings |
| `alembic/versions/xxx_add_nango_connections.py` | NEW: migration |
| `tests/integrations/test_nango.py` | NEW |
| `tests/pipelines/test_validator_evidence_verify.py` | NEW |

## Post-Implementation

- [ ] Update issue #52 with implementation notes
- [ ] Deploy Nango (self-hosted) or configure cloud account
- [ ] Configure integrations in Nango dashboard
- [ ] Add customer OAuth connect flow to admin UI (future)
