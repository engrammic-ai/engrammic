# Self-Hosted Distribution Design

**Date:** 2026-05-26  
**Status:** Ready  
**Trigger:** Compliance-driven lead (softlandia.fi) needs self-hosted deployment; pattern validated by multiple prospects

## Problem

Potential customers cannot use Engrammic's hosted service due to compliance requirements. They need to run the full stack locally with data never leaving their infrastructure.

## Goals

1. Enable compliant self-hosted deployment with minimal friction
2. Maintain license control and telemetry for business visibility
3. Extend existing installer to handle Docker deployments
4. Provide auth/silo flexibility for various customer setups

## Non-Goals

- Hybrid deployment (cloud compute + local data) - out of scope
- Kubernetes/Helm charts - future work if demand emerges
- Air-gapped deployments without any telemetry - customers can opt out but we don't optimize for it

## Architecture Overview

```
Customer Machine
├── docker-compose.yml (from installer)
├── .env (license key, config)
└── containers/
    ├── engrammic-api (license check on startup)
    ├── engrammic-dagster (SAGE background jobs)
    ├── memgraph
    ├── qdrant
    ├── redis
    └── postgres
```

## Components

### 1. Image Distribution

**Registry:**
- GCP Artifact Registry (public) - `europe-north1-docker.pkg.dev/engrammic/engrammic/`

**Images:**
| Image | Purpose |
|-------|---------|
| `engrammic-api` | Main context-service, MCP server, REST API |
| `engrammic-dagster` | SAGE pipeline worker (custodian, synthesizer, groundskeeper) |

**Versioning:**
- Tags: `latest`, `v0.x.y`, `v0.x.y-<sha>`
- Self-hosted customers should pin to semver tags

**CI Changes:**
- Make GCP AR public (IAM: `allUsers` gets `roles/artifactregistry.reader`)

### 2. Docker Compose Bundle

**Resource allocation (lite defaults):**

| Container | RAM | Notes |
|-----------|-----|-------|
| engrammic-api | 512MB | Single user |
| engrammic-dagster | 256MB | Background jobs |
| memgraph | 1GB | <100k nodes |
| qdrant | 512MB | Local scale |
| redis | 128MB | Cache |
| postgres | 256MB | Metadata + Dagster state |

**Total: ~2.5-3GB**

**Compose file ships with:**
- Lite resource limits as defaults
- Comments showing production sizing
- Health checks for all services
- Volume mounts for data persistence
- OTEL collector (optional, for telemetry)

**Scaling guidance (comments in compose file):**
| Threshold | Action |
|-----------|--------|
| >50k nodes | Bump Memgraph to 2GB |
| >100k nodes | Bump Memgraph to 4GB, Qdrant to 1GB |
| Multiple users | Bump engrammic-api to 1GB |

**Upgrade path:**
```bash
cd engrammic
docker compose pull    # fetch latest images
docker compose up -d   # restart with new versions
```

Telemetry includes version info; deprecation warnings appear in logs when running old versions.

### 3. License Key System

**Format:** Signed JWT (Ed25519)

```json
{
  "sub": "softlandia",
  "iss": "engrammic",
  "exp": 1756684800,
  "iat": 1716595200,
  "tier": "self-hosted",
  "features": ["mcp", "rest-api", "sage"]
}
```

**Key lifecycle:** 90-day expiry with auto-renewal

| Scenario | Behavior |
|----------|----------|
| Customer pays | Auto-renewal via `license.engrammic.ai/renew` extends key |
| Customer stops paying | Renewal fails, key expires in <90 days |
| Network unavailable | Graceful degradation: warn in logs, run until expiry |

**Validation flow:**
1. Container reads `ENGRAMMIC_LICENSE_KEY` env var
2. Verify Ed25519 signature against embedded public key
3. Check expiry (`exp` claim)
4. If <14 days until expiry: attempt auto-renewal (background, non-blocking)
5. If invalid/missing/expired: log error, exit 1
6. If valid: log customer ID, boot normally

**Auto-renewal endpoint:**
```
POST https://license.engrammic.ai/renew
Authorization: Bearer <current_license_key>

Response (success): { "key": "ENGR_eyJ..." }  # new 90-day key
Response (revoked): { "error": "license_revoked" }
```

Container writes renewed key to `.env` automatically (if writable) or logs instructions.

**Properties:**
- Offline capable for startup (no phone-home required)
- Auto-renewal for seamless paid experience
- Max 90 days of usage if customer churns
- Public key embedded in container image
- Private key stored in internal CLI repo (never distributed)

### 4. Internal CLI (../cli)

Separate repository for internal admin tooling.

**Structure:**
```
cli/
  src/
    engrammic_cli/
      __init__.py
      main.py           # typer entrypoint
      license.py        # key generation
  keys/
    private.pem         # Ed25519 signing key (gitignored!)
    public.pem          # copy to service + installer
  pyproject.toml
```

**Commands:**
```bash
# Generate license key
uv run engrammic-cli license create \
  --customer softlandia \
  --expires 2027-01-01 \
  --tier self-hosted

# Output: ENGR_eyJhbGciOiJFZDI1NTE5...

# List/revoke (future)
uv run engrammic-cli license list
uv run engrammic-cli license revoke <key-id>
```

**Tech:** Python + typer + cryptography

### 5. Installer Integration

**Current state:** Rust binary downloads MCP skills only.

**Extended flow:**
```
Engrammic Installer

What would you like to install?
  [1] MCP skills (Claude Code, Cursor, etc.)
  [2] Self-hosted stack (Docker required)
  [3] Both

> 2

Checking Docker... ✓ Found

Enter your license key: ENGR_eyJhbG...
Validating... ✓ Valid (softlandia, expires 2027-01-01)

Select install directory [./engrammic]: 

Writing files...
  → engrammic/docker-compose.yml
  → engrammic/.env

Done! To start:
  cd engrammic && docker compose up -d

Service will be available at:
  MCP:  stdio (configure in your editor)
  REST: http://localhost:8000
```

**Installer changes:**
- Add Docker detection
- Interactive menu (or `--docker` flag)
- Embed license public key for validation
- Bundle docker-compose.yml template
- Write `.env` with `ENGRAMMIC_LICENSE_KEY` and defaults

### 6. Auth Strategies

Self-hosted bypasses WorkOS entirely. MVP ships with api_key only; proxy/jwt deferred to Phase 3.

| Strategy | Config | Use case | Phase |
|----------|--------|----------|-------|
| `api_key` | Static keys in YAML/env | Single user, service-to-service | **1 (MVP)** |
| `proxy` | Trust `X-User-Id`, `X-Silo-Id` headers | Behind reverse proxy with auth | 3 |
| `jwt` | Validate against JWKS URL | Customer's IdP (Okta, Auth0, Keycloak) | 3 |

**Config example (MVP):**
```yaml
# /engrammic/config.yaml
auth:
  strategy: api_key
  api_keys:
    - key: "sk_live_..."
      name: "default"
      silo_id: "main"
```

### 7. Silo Handling

**Modes:**

| Mode | Behavior |
|------|----------|
| `single` | One silo for entire deployment. Default. |
| `multi` | Derive silo_id from auth context (JWT claim or header) |

**Config:**
```yaml
silo:
  mode: single
  default_silo_id: "prod"
```

**For most self-hosted customers:** Single mode with a hardcoded silo_id. They don't need multi-tenancy.

### 8. Admin API

Silo management for customers who need programmatic control.

**Endpoints:**
```
POST   /v1/admin/silos              # Create silo
GET    /v1/admin/silos              # List silos
GET    /v1/admin/silos/{id}         # Get silo
PATCH  /v1/admin/silos/{id}         # Update silo
DELETE /v1/admin/silos/{id}         # Delete silo
```

**Auth:** Requires admin API key or admin role in JWT.

**Scope:** Specced for future. Build in Phase 3 when demanded.

### 9. Health & Diagnostics

**Health endpoint:** `GET /health`

```json
{
  "status": "healthy",
  "license": {
    "valid": true,
    "customer": "softlandia",
    "expires_at": "2026-08-26T00:00:00Z",
    "days_remaining": 87
  },
  "services": {
    "memgraph": "healthy",
    "qdrant": "healthy",
    "redis": "healthy",
    "postgres": "healthy",
    "dagster": "healthy"
  },
  "sage_mode": "active",
  "recent_restarts": [],
  "version": "0.3.2"
}
```

**Status logic:**
- `healthy`: All services up, no recent restarts
- `degraded`: Some services down or restarted recently, core API still works
- `unhealthy`: Critical services (memgraph, postgres) down

**SAGE mode:**
- `active`: LLM keys configured, full synthesis
- `passive`: No LLM keys, storage + recall only

**Diagnostic command:** Installer includes `engrammic doctor`

```bash
engrammic doctor

Checking Docker... ✓ Running
Checking containers... ✓ 6/6 healthy
Checking license... ✓ Valid (83 days remaining)
Checking connectivity... ✓ tel.engrammic.ai reachable
Checking disk space... ✓ 42GB free

All checks passed.
```

Reduces support burden by helping customers self-diagnose.

### 10. LLM Configuration

SAGE pipeline (custodian, synthesizer, groundskeeper) requires LLM access. Self-hosted customers provide their own API keys.

**Env vars:**
```bash
# .env
LLM_PROVIDER=openai          # openai | anthropic | google-vertex
LLM_API_KEY=sk-...           # API key for chosen provider
LLM_MODEL=gpt-4o-mini        # Optional: override default model
```

**Behavior:**
| Config state | SAGE behavior |
|--------------|---------------|
| Keys provided | Full SAGE: synthesis, dedup, contradiction detection |
| Keys missing | Passive mode: storage + recall only, no LLM features |

**Passive mode:** Core memory/recall works immediately. Customer can add LLM keys later for full SAGE. Logs info message on startup: "SAGE running in passive mode (no LLM_API_KEY)".

### 11. Telemetry

**Default:** Enabled (license terms include consent)

**Opt-out:** `TELEMETRY_ENABLED=false`

**Collected:**
- Install ID (anonymous UUID, generated on first boot)
- Query counts by layer
- Latency percentiles (p50, p95, p99)
- Error rates by category
- Version info

**Not collected:**
- Content or query text
- User-identifiable information beyond license customer_id

**Endpoint:** `tel.engrammic.ai`

**Behavior:** Fire-and-forget. If endpoint unreachable, log locally and continue. Never block operations.

### 12. Resilience & OOM Handling

**Container restart policy:** All services use `restart: unless-stopped`. Docker auto-restarts crashed containers.

**Resource limits:** Compose file includes memory limits. If exceeded, container is OOM-killed and restarted.

**Proactive memory monitoring:** `/health` endpoint includes memory usage:
```json
{
  "memory": {
    "memgraph": {"used_mb": 890, "limit_mb": 1024, "percent": 87},
    "qdrant": {"used_mb": 320, "limit_mb": 512, "percent": 62},
    "app": {"used_mb": 380, "limit_mb": 512, "percent": 74}
  }
}
```

**Health degradation:** Returns `degraded` status if:
- Any service memory exceeds 80% of limit
- Any service restarted in the last 5 minutes

**Log warnings:** At 80% memory: "memgraph memory at 87%, run 'engrammic scale up' to increase limits"

**One-command scaling:**
```bash
engrammic scale up      # Bump all limits by 20%
engrammic scale down    # Reduce all limits by 20%
engrammic scale status  # Show current usage vs limits
```

Example output:
```
Current resource usage:

  Container         Used     Limit    Usage
  memgraph          890MB    1024MB   87% ⚠
  qdrant            320MB    512MB    62%
  app               380MB    512MB    74%
  dagster           180MB    256MB    70%
  redis             95MB     128MB    74%
  postgres          210MB    256MB    82% ⚠

Recommendation: Run 'engrammic scale up' to increase limits by 20%
```

After `engrammic scale up`:
```
Scaling up all containers by 20%...
  memgraph:  1024MB → 1228MB
  qdrant:    512MB  → 614MB
  app:       512MB  → 614MB
  dagster:   256MB  → 307MB
  redis:     128MB  → 153MB
  postgres:  256MB  → 307MB

Restarting containers...
Done. New limits active.
```

**Diagnostic detection:** `engrammic doctor` shows:
- Current memory usage per container
- Recent OOM events with recommendations
- Disk space warnings

**Graceful degradation:** If Dagster (SAGE) crashes, core API continues serving memory/recall. SAGE features return 503 until Dagster recovers.

## Implementation Phases

### Phase 1: Core Distribution (MVP for Luke)
- [ ] Make GCP AR public
- [ ] Create docker-compose.yml with lite defaults
- [ ] Add license validation to engrammic-api startup (90-day keys)
- [ ] Add auto-renewal endpoint (`license.engrammic.ai/renew`)
- [ ] Create internal CLI repo with license generation
- [ ] Extend installer for Docker flow + license key input
- [ ] Add health endpoint with license status + SAGE mode + memory usage
- [ ] Add SAGE passive mode (graceful degradation when no LLM keys)
- [ ] Add `engrammic doctor` diagnostic command with OOM detection
- [ ] Add `engrammic scale up/down/status` for one-command resource scaling

### Phase 2: Polish
- [ ] Documentation for self-hosted setup
- [ ] Deprecation warnings for old versions in logs

### Phase 3: Future (build when demanded)
- [ ] Docker Hub mirroring
- [ ] Auth strategies beyond api_key (proxy, jwt)
- [ ] Silo admin API endpoints
- [ ] Multi-silo mode
- [ ] Kubernetes Helm chart
- [ ] Self-hosted admin UI

## Decisions Made

1. **License key prefix:** Use `ENGR_` prefix for easy identification
2. **Key duration:** 90-day keys with auto-renewal
3. **Registry:** GCP AR public only (Docker Hub deferred)
4. **Auth MVP:** api_key strategy only; proxy/jwt deferred to Phase 3
5. **Compose location:** Install to `./engrammic/` subdirectory (keeps things tidy)
6. **MCP config:** Installer prints instructions; doesn't auto-write editor config (too many editors)
7. **LLM for SAGE:** Customer provides API keys; passive mode (storage only) if not configured
8. **OOM handling:** Docker restart policy + health degradation + doctor OOM detection

## Dependencies

- Self-Hosted REST API Phase 1 plan (auth strategies, already specced)
- Existing installer codebase (Rust, in mcp-client repo)
- New internal CLI repo (`../cli`)

## Success Criteria

1. Luke (softlandia.fi) can install and run self-hosted Engrammic in <10 minutes
2. License validation works offline
3. Auto-renewal works for paying customers
4. Non-paying customers locked out within 90 days
5. Telemetry flows to tel.engrammic.ai
6. `engrammic doctor` helps customers self-diagnose
7. No WorkOS dependency for self-hosted
