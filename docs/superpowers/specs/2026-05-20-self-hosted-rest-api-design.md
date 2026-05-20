# Self-Hosted REST API Surface

**Date:** 2026-05-20
**Status:** Ready for review

---

## Overview

REST API for self-hosted Engrammic deployments. Provides a layer-aligned HTTP interface mirroring the MCP tool surface, plus admin operations for operators. Self-hosted customers use this to build their own applications on top of Engrammic without MCP.

**Two surfaces:**
1. **Data API** (`/v1/*`) - CRUD for epistemic layers, search, graph operations
2. **Admin API** (`/v1/admin/*`) - License, silos, config, jobs, audit, metrics

---

## Authentication

### Mode Selection

```bash
# Hosted (default) - WorkOS OAuth
WORKOS_API_KEY=sk_...
WORKOS_CLIENT_ID=client_...

# Self-hosted
SELF_HOSTED_AUTH=true
# Loads /etc/engrammic/auth.yaml (or AUTH_CONFIG_PATH override)
```

### Self-Hosted Auth Config

```yaml
# /etc/engrammic/auth.yaml

# Strategy A: Trust upstream proxy headers
strategy: proxy
proxy:
  headers:
    silo_id: X-Silo-Id           # required
    user_id: X-User-Id           # optional
    scopes: X-Auth-Scopes        # optional, default: read,write
  require_https: true            # reject if X-Forwarded-Proto != https
  trusted_source_ips:            # REQUIRED - requests from other IPs rejected
    - 10.0.0.0/8
    - 172.16.0.0/12

# Strategy B: JWT validation from customer IdP
# strategy: jwt
# jwt:
#   issuer: https://auth.customer.com
#   jwks_uri: https://auth.customer.com/.well-known/jwks.json
#   audience: engrammic
#   allowed_algorithms:          # explicit allowlist, rejects 'none'
#     - RS256
#     - ES256
#   max_clock_skew_seconds: 60   # default 60
#   claims:
#     silo_id: silo_id
#     scopes: scope

# Strategy C: API keys (service-to-service, CI/CD)
# strategy: api_key
# api_key:
#   keys_file: /etc/engrammic/api_keys.yaml  # or inline keys below
#   keys:
#     - id: svc_etl_pipeline
#       secret_hash: sha256:...   # bcrypt or sha256 hash
#       silo_id: engineering
#       scopes: [read, write]
#       expires_at: 2027-01-01T00:00:00Z  # optional
```

### Scopes

Scopes are cumulative. Each level includes all permissions from levels above it.

| Scope | Access |
|-------|--------|
| `read` | GET endpoints, POST /search/recall, POST batch-get |
| `write` | read + POST/PATCH/DELETE on data endpoints |
| `admin` | write + /admin/* (silos, config, jobs, audit, metrics) |
| `export` | write + /admin/export/*, /admin/import (data movement, separate for compliance) |

Note: `admin` and `export` are peer scopes, both include `write`. A key can have `admin` without `export` (ops without data exfil) or `export` without `admin` (backup job without config access).

### Silo Isolation

Requests can only access the silo from their auth context. Enforced at API layer regardless of auth mode.

---

## Endpoint Structure

### Memory Layer

```
POST   /v1/memory/                  # remember (single observation)
POST   /v1/memory/batch             # remember (bulk, up to 1000)
POST   /v1/memory/batch-get         # fetch multiple by IDs
GET    /v1/memory/{node_id}         # fetch by ID
DELETE /v1/memory/{node_id}         # soft-delete (GDPR/CCPA)
```

### Knowledge Layer

```
POST   /v1/knowledge/               # learn (requires evidence)
POST   /v1/knowledge/batch          # learn (bulk)
POST   /v1/knowledge/batch-get      # fetch multiple by IDs
GET    /v1/knowledge/{node_id}      # fetch by ID
DELETE /v1/knowledge/{node_id}      # soft-delete (GDPR/CCPA)
```

### Wisdom Layer

```
POST   /v1/wisdom/beliefs           # believe (requires about nodes)
POST   /v1/wisdom/beliefs/batch-get # fetch multiple by IDs
GET    /v1/wisdom/beliefs/{node_id}
DELETE /v1/wisdom/beliefs/{node_id} # soft-delete

POST   /v1/wisdom/hypotheses        # hypothesize (tentative)
PATCH  /v1/wisdom/hypotheses/{id}   # revise
POST   /v1/wisdom/hypotheses/{id}/commit  # commit to belief
GET    /v1/wisdom/hypotheses/{id}
DELETE /v1/wisdom/hypotheses/{id}   # discard hypothesis
```

### Intelligence Layer

```
POST   /v1/intelligence/reason      # reasoning chain
POST   /v1/intelligence/reflect     # meta-observation
GET    /v1/intelligence/{node_id}   # fetch reasoning/reflection by ID
POST   /v1/intelligence/batch-get   # fetch multiple by IDs
```

Nodes are immutable. Updates use supersession (create new node referencing old). DELETE performs soft-delete (tombstone), preserving audit trail.

### Graph Operations

```
POST   /v1/graph/links              # link nodes
POST   /v1/graph/links/batch        # bulk links
GET    /v1/graph/trace/{node_id}    # provenance chain
```

### Search

```
POST   /v1/search/recall            # semantic search (complex queries)
GET    /v1/search/recall?q=...      # simple text search
```

---

## Admin API

### License

```
GET    /v1/admin/license            # status, tier, features, expiry, grace_period
```

Read-only. License managed by Engrammic (signed JWT), operators can inspect status.

### Silo Management

```
POST   /v1/admin/silos              # create silo
GET    /v1/admin/silos              # list silos
GET    /v1/admin/silos/{id}         # silo details + stats
PATCH  /v1/admin/silos/{id}         # update config
DELETE /v1/admin/silos/{id}         # soft-delete
```

Silo config includes:
```json
{
  "name": "engineering",
  "retention": {
    "default_ttl_days": null,
    "rules": [
      {"layer": "memory", "ttl_days": 90},
      {"tag": "ephemeral", "ttl_days": 7}
    ]
  },
  "features": {
    "reasoning_enabled": true,
    "synthesis_enabled": true
  }
}
```

### Configuration

```
GET    /v1/admin/config             # current runtime config
PATCH  /v1/admin/config             # update (LLM provider, embedding model, thresholds)
```

### Jobs (Async Operations)

```
GET    /v1/admin/jobs               # list recent jobs
GET    /v1/admin/jobs/{id}          # status, progress, result/error
POST   /v1/admin/jobs/{id}/cancel   # cancel running job
POST   /v1/admin/jobs/{id}/retry    # retry failed job
POST   /v1/admin/jobs/tombstone     # trigger tombstone
POST   /v1/admin/jobs/synthesis     # trigger Custodian synthesis
POST   /v1/admin/jobs/maintenance   # reindex, compaction
```

### Export/Backup

```
POST   /v1/admin/export             # 202 Accepted, returns job_id
GET    /v1/admin/export/{job_id}/download  # stream backup artifact
POST   /v1/admin/import             # 202 Accepted, upload + restore
```

Import accepts multipart upload or URL reference to backup artifact.

### Audit Logs

```
GET    /v1/admin/audit              # paginated audit log
       ?silo_id=...
       &action=...
       &actor=...
       &since=...
       &until=...
```

Audit logs capture both reads and writes for compliance (SOC2, HIPAA adjacency):
- `node.read`, `node.create`, `node.delete`
- `search.recall`
- `admin.config.update`, `admin.silo.create`, etc.
- `auth.success`, `auth.failure`

### Metrics

```
GET    /v1/admin/metrics            # node counts, storage, query volume per silo
GET    /v1/admin/metrics/prometheus # Prometheus scrape endpoint
```

### Health (No Auth)

```
GET    /health/live                 # k8s liveness probe
GET    /health/ready                # k8s readiness (DB connections up)
```

---

## Request/Response Formats

### Success Response

```json
{
  "data": { ... },
  "meta": {
    "request_id": "req_abc123",
    "took_ms": 42
  }
}
```

### List Response

```json
{
  "data": [ ... ],
  "meta": {
    "request_id": "req_abc123",
    "took_ms": 87,
    "pagination": {
      "cursor": "eyJpZCI6...",
      "has_more": true
    }
  }
}
```

Pagination is cursor-based only. Cursor is opaque base64.

### Error Response

```json
{
  "error": {
    "code": "validation_error",
    "message": "evidence is required for learn",
    "details": {
      "field": "evidence",
      "constraint": "required"
    }
  },
  "meta": {
    "request_id": "req_abc123"
  }
}
```

### Error Codes

| HTTP | Code | When |
|------|------|------|
| 400 | `validation_error` | Bad input |
| 401 | `unauthorized` | Missing/invalid auth |
| 403 | `forbidden` | Valid auth, wrong scope or silo |
| 404 | `not_found` | Node/resource doesn't exist |
| 409 | `conflict` | Duplicate, version mismatch |
| 429 | `rate_limited` | Too many requests |
| 503 | `unavailable` | DB down, license expired (read-only mode) |

### Batch Response

```json
{
  "data": {
    "succeeded": [
      {"index": 0, "node_id": "mem_abc"},
      {"index": 2, "node_id": "mem_def"}
    ],
    "failed": [
      {"index": 1, "error": {"code": "validation_error", "message": "..."}}
    ]
  },
  "meta": { ... }
}
```

Partial success allowed. Clients must check both arrays.

---

## Streaming

For large reads, clients can request SSE streaming:

```http
GET /v1/graph/trace/node_abc123
Accept: text/event-stream
```

```
event: node
data: {"node_id": "node_abc", "layer": "wisdom", ...}

event: node
data: {"node_id": "node_def", "layer": "knowledge", ...}

event: done
data: {"count": 12, "took_ms": 234}
```

Default (no Accept header) returns full JSON array. Streaming is optional for progressive rendering.

---

## Async Operations

Long-running admin operations return 202 with a job ID:

```http
POST /v1/admin/export
```

```json
{
  "data": {
    "job_id": "job_xyz",
    "status": "queued"
  }
}
```

Poll for status:

```http
GET /v1/admin/jobs/job_xyz
```

```json
{
  "data": {
    "job_id": "job_xyz",
    "type": "export",
    "status": "running",
    "progress": 0.45,
    "created_at": "2026-05-20T10:00:00Z",
    "completed_at": null,
    "result": null,
    "error": null
  }
}
```

Status values: `queued`, `running`, `completed`, `failed`

**Async operations:**
- Export/backup
- Tombstone (large scope)
- Synthesis trigger
- Maintenance/reindex

**Sync operations:**
- Single writes (remember, learn, believe)
- Batch writes (up to 1000 items)
- Reads (recall, trace)

---

## Implementation Notes

### Relationship to MCP Surface

The REST API is a parallel surface, not a replacement. MCP remains primary for AI agents.

| MCP Tool | REST Endpoint |
|----------|---------------|
| remember | POST /v1/memory/ |
| learn | POST /v1/knowledge/ |
| believe | POST /v1/wisdom/beliefs |
| recall | POST /v1/search/recall |
| trace | GET /v1/graph/trace/{id} |
| link | POST /v1/graph/links |
| reason | POST /v1/intelligence/reason |
| reflect | POST /v1/intelligence/reflect |
| hypothesize | POST /v1/wisdom/hypotheses |
| revise | PATCH /v1/wisdom/hypotheses/{id} |
| commit | POST /v1/wisdom/hypotheses/{id}/commit |

### Auth Resolution Order

In `get_auth_context`:
1. If `SELF_HOSTED_AUTH=true`, load YAML config and use proxy/jwt strategy
2. Otherwise, use WorkOS session verification (existing)

### Silo Header

All data endpoints require silo context. In self-hosted proxy mode, this comes from headers. In JWT mode, from token claims.

---

## Decisions

1. **Rate limiting:** Both. Ship basic configurable token bucket in API layer AND document that operators should add edge rate limiting. Silo-level quotas configurable via admin API.

2. **Versioning:** Path-based (`/v1/`). Breaking changes require `/v2/`. Non-breaking additions (new fields, endpoints) stay in current version.

3. **SDK:** Generate OpenAPI spec (table stakes for enterprise). Client SDKs (Python, TypeScript) follow when we have design partners requesting them.

## Deferred (v1.1+)

- **Webhooks** - Event subscriptions for node creation, synthesis completion, license expiry. Defer until we understand what events customers want.
- **Graph traversal endpoint** - Arbitrary graph queries beyond trace. Add when customers need subgraph extraction.
- **Config validation dry-run** - `POST /v1/admin/config/validate` before applying.
- **Historical metrics** - Time-series data for capacity planning dashboards.

---

## Related Documents

- `context/brainstorm/2026-05-20-self-hosted-licensing.md` - License enforcement for self-hosted
- `context/architecture.md` - Service architecture overview
- `src/context_service/config/mcp_tools.yaml` - MCP tool surface config
