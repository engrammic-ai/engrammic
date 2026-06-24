# Closed Beta Deployment Design

**Date:** 2026-05-18
**Status:** Approved
**Author:** Claude + User

## Summary

Deploy Engrammic for design partner closed beta on GCP with full environment isolation, CI/CD via GitHub Actions, and a separate beacon telemetry service.

## Context

Design partners need access to Engrammic with:
- Silo isolation per partner (via WorkOS org mapping, already implemented)
- Stable beta environment separate from dev
- Telemetry collection via beacon endpoint

Current state:
- Pulumi IaC with dev/prod profiles
- Artifact Registry at `europe-north1-docker.pkg.dev/engrammic/engrammic/`
- WorkOS auth with user/usage tracking (just shipped)
- Beacon receiver code not yet written

## Architecture

```
beta branch push
       |
       v
+----------------------------------------------------------+
|  GitHub Actions                                          |
|  +--------------+  +---------------+  +----------------+ |
|  | Build API    |  | Build Beacon  |  | pulumi up      | |
|  | image        |->| image         |->| --stack beta   | |
|  +--------------+  +---------------+  +----------------+ |
+----------------------------------------------------------+
                           |
       +-------------------+-------------------+
       v                                       v
+------------------+                +------------------+
| Cloud Run: API   |                | Cloud Run: Beacon|
| beta.engrammic.ai|                | tel.engrammic.ai |
+--------+---------+                +--------+---------+
         |                                   |
         +----------------+------------------+
                          | VPC / Private Service Connect
         +----------------+------------------+
         v                                   v
+--------------------+           +---------------------------+
| Cloud SQL Postgres |           | GCE StatefulHost (beta)   |
| (managed, backups) |           | +----------+ +--------+   |
| :5432              |           | | Memgraph | | Qdrant |   |
+--------------------+           | | :7687    | | :6333  |   |
                                 | +----------+ +--------+   |
                                 | +-------+                 |
                                 | | Redis |                 |
                                 | | :6379 |                 |
                                 | +-------+                 |
                                 +---------------------------+
```

**Database split rationale:**
- **Cloud SQL for Postgres**: Automatic backups, PITR, easier migrations, no VM dependency for critical relational data
- **StatefulHost for Memgraph/Qdrant/Redis**: No managed GCP alternatives, self-hosting is the only option

## File Changes

| Path | Change |
|------|--------|
| `docker/Dockerfile.api` | Move/update from existing Dockerfile |
| `docker/Dockerfile.beacon` | New: minimal FastAPI beacon receiver |
| `src/beacon_service/__init__.py` | New: package init |
| `src/beacon_service/main.py` | New: FastAPI app with POST /v1/beacon |
| `src/beacon_service/config.py` | New: Postgres connection config |
| `infra/Pulumi.beta.yaml` | New: beta stack config |
| `infra/components/cloudsql.py` | New: Cloud SQL Postgres instance |
| `infra/components/beacon.py` | New: BeaconServiceRun component |
| `infra/components/cloudrun.py` | Update: support multiple services |
| `infra/components/compute.py` | Update: remove Postgres from StatefulHost |
| `infra/__main__.py` | Update: add beacon service + Cloud SQL |
| `.github/workflows/deploy-beta.yml` | New: CI/CD workflow |

## Pulumi Beta Stack Config

`infra/Pulumi.beta.yaml`:
```yaml
config:
  gcp:project: engrammic
  engrammic-infra:environment: beta
  # StatefulHost (Memgraph, Qdrant, Redis only - no Postgres)
  engrammic-infra:instance_type: e2-standard-2
  engrammic-infra:use_spot: false
  engrammic-infra:disk_size_memgraph: 50
  engrammic-infra:disk_size_qdrant: 50
  # Cloud SQL Postgres
  engrammic-infra:cloudsql_tier: db-f1-micro
  engrammic-infra:cloudsql_disk_size: 20
  engrammic-infra:cloudsql_ha: false
  # Cloud Run
  engrammic-infra:min_cloudrun_instances: 1
```

Sizing rationale:
- StatefulHost downsized to e2-standard-2 (no Postgres load)
- Cloud SQL db-f1-micro (~$10/month) sufficient for beta, upgrade to db-g1-small if needed
- HA disabled for cost savings during beta

## Beacon Service

Minimal FastAPI service to receive telemetry beacons with shared-secret authentication.

**Authentication:** Each self-hosted instance is provisioned with a `BEACON_SECRET` that maps to a `silo_id`. The beacon service validates the secret and derives `silo_id` server-side (never trusts client-supplied silo_id).

```python
# src/beacon_service/main.py
from fastapi import FastAPI, Header, HTTPException, Request
from contextlib import asynccontextmanager
import asyncpg
import structlog
import os

log = structlog.get_logger()

# Secret -> silo_id mapping (loaded from DB or config at startup)
# In production: query beacon_secrets table
SECRET_TO_SILO: dict[str, str] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    # Load secret mappings
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch("SELECT secret, silo_id FROM beacon_secrets")
        for row in rows:
            SECRET_TO_SILO[row["secret"]] = row["silo_id"]
    yield
    await app.state.pool.close()

app = FastAPI(title="Engrammic Beacon", lifespan=lifespan)

@app.post("/v1/beacon")
async def receive_beacon(
    request: Request,
    x_beacon_secret: str = Header(..., alias="X-Beacon-Secret"),
):
    """Receive and store telemetry beacon from self-hosted instances."""
    silo_id = SECRET_TO_SILO.get(x_beacon_secret)
    if not silo_id:
        raise HTTPException(status_code=401, detail="Invalid beacon secret")

    payload = await request.json()
    event_type = payload.get("event_type", "unknown")

    async with app.state.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO beacon_events (silo_id, event_type, payload)
            VALUES ($1, $2, $3)
            """,
            silo_id,
            event_type,
            payload,
        )

    log.info("beacon_received", silo_id=silo_id, event_type=event_type)
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

**Database tables** (Alembic migration):
```sql
-- beacon_secrets: maps shared secrets to silos
CREATE TABLE beacon_secrets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    silo_id VARCHAR(255) NOT NULL UNIQUE,
    secret VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_beacon_secrets_secret ON beacon_secrets(secret);

-- beacon_events: stores received telemetry
CREATE TABLE beacon_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    silo_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(100),
    payload JSONB,
    received_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_beacon_silo_time ON beacon_events(silo_id, received_at);
```

**Provisioning a new partner:** Generate secret, insert into `beacon_secrets`, provide to partner for their `.env`.

## GitHub Actions Workflow

`.github/workflows/deploy-beta.yml`:
```yaml
name: Deploy Beta

on:
  push:
    branches: [beta]

env:
  REGION: europe-north1
  REGISTRY: europe-north1-docker.pkg.dev/engrammic/engrammic

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write

    steps:
      - uses: actions/checkout@v4

      - name: Authenticate to GCP
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}

      - name: Configure Docker
        run: gcloud auth configure-docker ${{ env.REGION }}-docker.pkg.dev

      - name: Build and push API image
        run: |
          docker build -f docker/Dockerfile.api -t ${{ env.REGISTRY }}/engrammic-api:${{ github.sha }} .
          docker push ${{ env.REGISTRY }}/engrammic-api:${{ github.sha }}
          docker tag ${{ env.REGISTRY }}/engrammic-api:${{ github.sha }} ${{ env.REGISTRY }}/engrammic-api:latest
          docker push ${{ env.REGISTRY }}/engrammic-api:latest

      - name: Build and push Beacon image
        run: |
          docker build -f docker/Dockerfile.beacon -t ${{ env.REGISTRY }}/engrammic-beacon:${{ github.sha }} .
          docker push ${{ env.REGISTRY }}/engrammic-beacon:${{ github.sha }}
          docker tag ${{ env.REGISTRY }}/engrammic-beacon:${{ github.sha }} ${{ env.REGISTRY }}/engrammic-beacon:latest
          docker push ${{ env.REGISTRY }}/engrammic-beacon:latest

      - name: Setup Pulumi
        uses: pulumi/actions@v5

      - name: Deploy infrastructure
        run: |
          cd infra
          uv sync
          uv run pulumi up --stack beta --yes
        env:
          PULUMI_ACCESS_TOKEN: ${{ secrets.PULUMI_ACCESS_TOKEN }}

      - name: Run database migrations
        run: |
          # Use Cloud SQL Auth Proxy to connect securely
          wget -q https://dl.google.com/cloudsql/cloud_sql_proxy.linux.amd64 -O cloud_sql_proxy
          chmod +x cloud_sql_proxy
          ./cloud_sql_proxy -instances=engrammic:europe-north1:engrammic-beta=tcp:5432 &
          sleep 5
          # Run migrations
          uv run alembic upgrade head
        env:
          DATABASE_URL: postgresql://context:${{ secrets.POSTGRES_PASSWORD }}@localhost:5432/engrammic
```

**Migration strategy:** Cloud SQL Auth Proxy provides secure, IAM-authenticated access without exposing the database publicly. Migrations run after `pulumi up` creates/updates the Cloud SQL instance. Cloud Run health checks ensure new revisions don't receive traffic until the app is ready.

## Release Flow

1. Development happens on `main`
2. When ready for beta release:
   ```bash
   git checkout beta
   git merge main
   git push origin beta
   ```
3. GitHub Actions triggers:
   - Builds API and Beacon images
   - Tags with commit SHA + `latest`
   - Pushes to Artifact Registry
   - Runs `pulumi up --stack beta`
   - Runs database migrations via SSH to StatefulHost
4. Cloud Run pulls new images and deploys (after migrations complete)

## Secrets

**GCP Secret Manager (existing, grant beta stack access):**
- `postgres-password`
- `memgraph-password`
- `workos-api-key`
- `anthropic-api-key`
- `openai-api-key`
- `google-api-key`

**GitHub Actions secrets (new):**
- `GCP_WORKLOAD_IDENTITY_PROVIDER` - for keyless auth
- `GCP_SERVICE_ACCOUNT` - service account email
- `PULUMI_ACCESS_TOKEN` - Pulumi Cloud token

## DNS

| Domain | Target |
|--------|--------|
| beta.engrammic.ai | Cloud Run API service |
| tel.engrammic.ai | Cloud Run Beacon service |

Configure via Cloud Run domain mapping or Cloudflare proxy (depending on DNS provider).

## Rollback

**Quick rollback (redeploy previous image):**
```bash
cd infra
# Update image tag in Pulumi config or env
uv run pulumi up --stack beta --yes
```

**Full rollback (revert code):**
```bash
git checkout beta
git revert HEAD
git push origin beta
# GitHub Actions redeploys previous state
```

## Migrations

Run manually after deploy for beta:
```bash
# SSH to stateful host or run from local with port forward
just db-migrate
```

Future: add as post-deploy step in GitHub Actions.

## Out of Scope

- Auto-scaling configuration (use Cloud Run defaults for now)
- Monitoring/alerting setup (SigNoz already deployed, just need to point beta at it)
- Partner onboarding automation (manual WorkOS invites for now)
- Blue/green deployments (single deployment per push is fine for beta)

## Testing

1. Create beta branch locally
2. Push to trigger workflow
3. Verify images in Artifact Registry
4. Verify Cloud Run services deployed
5. Test API at beta.engrammic.ai
6. Test beacon at tel.engrammic.ai/v1/beacon
7. Verify silo isolation with test accounts

## Rollout

1. Create `beta` branch from `main`
2. Set up GitHub Actions secrets
3. Configure Workload Identity Federation for keyless auth
4. Run `pulumi up --stack beta` once manually to create initial resources
5. Push to beta to verify CI/CD
6. Configure DNS
7. Invite first design partner
