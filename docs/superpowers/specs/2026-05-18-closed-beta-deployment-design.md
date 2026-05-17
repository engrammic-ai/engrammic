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
+--------+---------+                +------------------+
         | VPC Connector
         v
+------------------------------------------------------+
| GCE StatefulHost (beta)                              |
| +----------+ +--------+ +-------+ +----------------+ |
| | Memgraph | | Qdrant | | Redis | | Postgres       | |
| | :7687    | | :6333  | | :6379 | | :5432          | |
| +----------+ +--------+ +-------+ +----------------+ |
+------------------------------------------------------+
```

## File Changes

| Path | Change |
|------|--------|
| `docker/Dockerfile.api` | Move/update from existing Dockerfile |
| `docker/Dockerfile.beacon` | New: minimal FastAPI beacon receiver |
| `src/beacon_service/__init__.py` | New: package init |
| `src/beacon_service/main.py` | New: FastAPI app with POST /v1/beacon |
| `src/beacon_service/config.py` | New: Postgres connection config |
| `infra/Pulumi.beta.yaml` | New: beta stack config |
| `infra/components/beacon.py` | New: BeaconServiceRun component |
| `infra/components/cloudrun.py` | Update: support multiple services |
| `infra/__main__.py` | Update: add beacon service |
| `.github/workflows/deploy-beta.yml` | New: CI/CD workflow |

## Pulumi Beta Stack Config

`infra/Pulumi.beta.yaml`:
```yaml
config:
  gcp:project: engrammic
  engrammic-infra:environment: beta
  engrammic-infra:instance_type: e2-standard-4
  engrammic-infra:min_cloudrun_instances: 1
  engrammic-infra:use_spot: false
  engrammic-infra:disk_size_memgraph: 50
  engrammic-infra:disk_size_qdrant: 50
  engrammic-infra:disk_size_postgres: 20
```

Sizing rationale: between dev (e2-standard-2) and prod (e2-standard-8). No spot instances for reliability during partner demos.

## Beacon Service

Minimal FastAPI service to receive telemetry beacons:

```python
# src/beacon_service/main.py
from fastapi import FastAPI, Request
from datetime import datetime, UTC
import structlog

app = FastAPI(title="Engrammic Beacon")
log = structlog.get_logger()

@app.post("/v1/beacon")
async def receive_beacon(request: Request):
    """Receive and store telemetry beacon from self-hosted instances."""
    payload = await request.json()
    # Store to Postgres (beacon_events table)
    # Fields: silo_id, event_type, payload, received_at
    log.info("beacon_received", silo_id=payload.get("silo_id"))
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

Database table (add to existing Postgres):
```sql
CREATE TABLE beacon_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    silo_id VARCHAR(255),
    event_type VARCHAR(100),
    payload JSONB,
    received_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_beacon_silo_time ON beacon_events(silo_id, received_at);
```

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
```

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
4. Cloud Run pulls new images and deploys

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
