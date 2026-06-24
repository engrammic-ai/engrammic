# Pulumi Beta Deployment Fix

**Date:** 2026-05-19
**Status:** Approved
**Author:** Claude + User

## Summary

Fix the broken GCP beta deployment: add missing Dagster services, complete env var configuration, add auth secrets, and create secrets sync workflow.

## Context

The Pulumi beta deployment is incomplete:
- Dagster not deployed (Custodian pipeline can't run)
- Missing env vars for Cloud Run (auth, embeddings, LLM config)
- Missing secrets (WorkOS client ID, cookie password)
- No workflow for syncing local secrets with GCP Secret Manager
- StatefulHost undersized for running Dagster alongside DBs
- Database name inconsistency (`context_service` vs `engrammic`) across config
- GitHub Actions missing Dagster image build step

Existing work already done:
- `__main__.py`: Added MEMGRAPH_URI, QDRANT_URL, REDIS_URL
- `compute.py`: Added Dagster services to docker-compose template (but with wrong DB name)

## Architecture

```
                    GitHub Actions (deploy-beta.yml)
                              |
          +-------------------+-------------------+
          v                   v                   v
    Build API image    Build Dagster image    pulumi up --stack beta
          |                   |                   |
          v                   v                   v
    Artifact Registry   Artifact Registry    GCP Resources
          |                   |                   |
          +-------------------+-------------------+
                              |
          +-------------------+-------------------+
          v                                       v
  +------------------+                  +---------------------------+
  | Cloud Run: API   |                  | GCE StatefulHost (beta)   |
  | beta.engrammic.ai|                  | e2-standard-4             |
  +--------+---------+                  | +----------+ +--------+   |
           |                            | | Memgraph | | Qdrant |   |
           | VPC Connector              | | :7687    | | :6333  |   |
           |                            | +----------+ +--------+   |
           +-------------+--------------+ +-------+ +-------------+ |
                         |              | | Redis | | Dagster     | |
                         v              | | :6379 | | code/web/   | |
              +--------------------+    | +-------+ | daemon      | |
              | Cloud SQL Postgres |    |           +-------------+ |
              | (managed)          |    +---------------------------+
              +--------------------+
```

## Design Decisions

1. **Dagster on StatefulHost** - Runs alongside Memgraph/Qdrant/Redis on same VM. Simpler than separate VM, sufficient for beta scale.

2. **e2-standard-4** - Upgrade from e2-standard-2 to avoid OOM with Dagster added (4 vCPU, 16GB RAM).

3. **Vertex AI** - Use for both embeddings and LLM. Consistent provider, uses existing GCP service account auth.

4. **Auth enabled** - Full WorkOS auth for beta. Partners get proper accounts.

5. **Custodian enabled** - Synthesis pipeline runs on schedule. Tests complete system.

6. **Internal-only Dagster UI** - Access via SSH tunnel, no public exposure.

7. **Cloud SQL IP via metadata** - Pass to StatefulHost via instance metadata instead of Secret Manager (Pulumi output, not pre-existing secret).

## File Changes

| File | Change |
|------|--------|
| `docker/Dockerfile.dagster` | Create - Dagster image based on API pattern |
| `infra/Pulumi.beta.yaml` | Upgrade instance_type to e2-standard-4 |
| `infra/__main__.py` | Add missing env vars, auth secrets, pass postgres_host |
| `infra/components/secrets.py` | Add workos-client-id, workos-cookie-password |
| `infra/components/compute.py` | Accept postgres_host, use metadata, fix DB name to `engrammic`, add Vertex/Custodian env vars |
| `src/context_service/config/settings.py` | Fix postgres_database default to `engrammic` |
| `.env.example` | Add auth, Vertex, Custodian config; fix POSTGRES_DATABASE to `engrammic` |
| `.env.beta.example` | Create - template for beta secrets |
| `justfile` | Add secrets-push, secrets-pull recipes |
| `.github/workflows/deploy-beta.yml` | Add Dagster image build/push step |

## Implementation Details

### 1. Dockerfile.dagster

New file at `docker/Dockerfile.dagster`:

```dockerfile
# Stage 1: Build
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src/ /app/src/
COPY config/ /app/config/
COPY dagster.yaml workspace.yaml ./
RUN uv sync --frozen --no-dev

# Stage 2: Runtime
FROM python:3.12-slim

RUN useradd -m -u 1000 dagster

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/config /app/config
COPY --from=builder /app/dagster.yaml /app/workspace.yaml ./

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV DAGSTER_HOME="/app"

USER dagster
```

### 2. Pulumi.beta.yaml

Change line 7:
```yaml
engrammic-infra:instance_type: e2-standard-4
```

**Note:** This change requires VM replacement, causing ~5 min outage for StatefulHost services. Schedule during maintenance window.

### 2b. settings.py

Fix the flat shim default at line ~1081:

```python
postgres_database: str = Field(default="engrammic")  # was "context_service"
```

### 3. __main__.py env_vars

Add to `env_vars={}` dict (lines 56-75):

```python
env_vars={
    # Existing
    "ENVIRONMENT": config.require("environment"),
    "MEMGRAPH_HOST": stateful_host.instance.network_interfaces[0].network_ip,
    "MEMGRAPH_URI": stateful_host.instance.network_interfaces[0].network_ip.apply(
        lambda ip: f"bolt://{ip}:7687"
    ),
    "QDRANT_HOST": stateful_host.instance.network_interfaces[0].network_ip,
    "QDRANT_URL": stateful_host.instance.network_interfaces[0].network_ip.apply(
        lambda ip: f"http://{ip}:6333"
    ),
    "REDIS_HOST": stateful_host.instance.network_interfaces[0].network_ip,
    "REDIS_URL": stateful_host.instance.network_interfaces[0].network_ip.apply(
        lambda ip: f"redis://{ip}:6379"
    ),
    "POSTGRES_HOST": postgres_host,
    "POSTGRES_USER": "context",
    "POSTGRES_DATABASE": "engrammic",
    "VERTEX_PROJECT_ID": "engrammic",
    "VERTEX_LOCATION": "europe-north1",
    # NEW
    "HOST": "0.0.0.0",
    "PORT": "8000",
    "EMBEDDING_PROVIDER": "vertex",
    "LLM_PROVIDER": "vertex_gemini",
    "DEFAULT_LLM_MODEL": "gemini-2.5-flash",
    "AUTH_ENABLED": "true",
    "CUSTODIAN__ENABLED": "true",
    "LOG_LEVEL": "INFO",
},
```

Add to `secrets={}` dict:

```python
secrets={
    "POSTGRES_PASSWORD": secrets.secrets["postgres-password"].id,
    "MEMGRAPH_PASSWORD": secrets.secrets["memgraph-password"].id,
    "WORKOS_API_KEY": secrets.secrets["workos-api-key"].id,
    # NEW
    "WORKOS_CLIENT_ID": secrets.secrets["workos-client-id"].id,
    "WORKOS_COOKIE_PASSWORD": secrets.secrets["workos-cookie-password"].id,
},
```

Pass postgres_host to StatefulHost:

```python
stateful_host = StatefulHost(
    "engrammic-stateful",
    network=network.vpc,
    subnet=network.private_subnet,
    service_account_email=iam.stateful_host.email,
    postgres_host=postgres_host if use_cloudsql else None,  # NEW
)
```

### 4. secrets.py

Update `secret_names` list:

```python
secret_names = [
    "postgres-password",
    "memgraph-password",
    "workos-api-key",
    "workos-client-id",       # NEW
    "workos-cookie-password", # NEW
]
```

### 5. compute.py

**Database name fix:** Change all `POSTGRES_DATABASE=context_service` to `POSTGRES_DATABASE=engrammic` in DAGSTER_SERVICES and POSTGRES_SERVICE templates.

**Startup script fix:** Replace Secret Manager lookup with instance metadata for Cloud SQL IP.

Add `postgres_host` parameter to `__init__`:

```python
def __init__(
    self,
    name: str,
    network: compute.Network,
    subnet: compute.Subnetwork,
    service_account_email: str,
    postgres_host: pulumi.Input[str] | None = None,  # NEW
    opts: pulumi.ResourceOptions | None = None,
):
```

Add metadata to Instance:

```python
self.instance = compute.Instance(
    f"{name}-instance",
    ...
    metadata={
        "postgres-host": postgres_host or "postgres",
    },
    ...
)
```

Update startup script to read from metadata:

```bash
if [ "$USE_CLOUDSQL" = "true" ]; then
    export POSTGRES_HOST=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/postgres-host" -H "Metadata-Flavor: Google")
else
    export POSTGRES_HOST=postgres
fi
```

Update DAGSTER_SERVICES template to include Vertex/Custodian env vars:

```python
DAGSTER_SERVICES = '''
  dagster-code-server:
    image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest
    container_name: engrammic-dagster-code
    command: ["dagster", "api", "grpc", "-h", "0.0.0.0", "-p", "4000", "-m", "context_service.pipelines.definitions"]
    ports:
      - "4000:4000"
    environment:
      - DAGSTER_HOME=/app
      - MEMGRAPH_URI=bolt://memgraph:7687
      - QDRANT_URL=http://qdrant:6333
      - REDIS_URL=redis://redis:6379
      - POSTGRES_HOST=${POSTGRES_HOST}
      - POSTGRES_USER=context
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DATABASE=engrammic
      - VERTEX_PROJECT_ID=engrammic
      - VERTEX_LOCATION=europe-north1
      - EMBEDDING_PROVIDER=vertex
      - LLM_PROVIDER=vertex_gemini
      - DEFAULT_LLM_MODEL=gemini-2.5-flash
      - CUSTODIAN__ENABLED=true
    depends_on:
      - memgraph
      - qdrant
      - redis
    restart: unless-stopped

  dagster-webserver:
    image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest
    container_name: engrammic-dagster-web
    command: ["dagster-webserver", "-h", "0.0.0.0", "-p", "3000", "-w", "workspace.yaml"]
    ports:
      - "3000:3000"
    environment:
      - DAGSTER_HOME=/app
      - MEMGRAPH_URI=bolt://memgraph:7687
      - QDRANT_URL=http://qdrant:6333
      - REDIS_URL=redis://redis:6379
      - POSTGRES_HOST=${POSTGRES_HOST}
      - POSTGRES_USER=context
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DATABASE=engrammic
      - VERTEX_PROJECT_ID=engrammic
      - VERTEX_LOCATION=europe-north1
      - EMBEDDING_PROVIDER=vertex
      - LLM_PROVIDER=vertex_gemini
      - DEFAULT_LLM_MODEL=gemini-2.5-flash
      - CUSTODIAN__ENABLED=true
    depends_on:
      - dagster-code-server
    restart: unless-stopped

  dagster-daemon:
    image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest
    container_name: engrammic-dagster-daemon
    command: ["dagster-daemon", "run"]
    environment:
      - DAGSTER_HOME=/app
      - MEMGRAPH_URI=bolt://memgraph:7687
      - QDRANT_URL=http://qdrant:6333
      - REDIS_URL=redis://redis:6379
      - POSTGRES_HOST=${POSTGRES_HOST}
      - POSTGRES_USER=context
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DATABASE=engrammic
      - VERTEX_PROJECT_ID=engrammic
      - VERTEX_LOCATION=europe-north1
      - EMBEDDING_PROVIDER=vertex
      - LLM_PROVIDER=vertex_gemini
      - DEFAULT_LLM_MODEL=gemini-2.5-flash
      - CUSTODIAN__ENABLED=true
    depends_on:
      - dagster-code-server
    restart: unless-stopped
'''
```

### 6. .env.example

Update POSTGRES_DATABASE and add new entries:

```bash
# Fix database name
POSTGRES_DATABASE=engrammic  # was context_service

# =============================================================================
# Auth (required for beta/prod)
# =============================================================================
AUTH_ENABLED=false
WORKOS_API_KEY=
WORKOS_CLIENT_ID=
WORKOS_COOKIE_PASSWORD=

# =============================================================================
# Embeddings (Vertex AI for beta/prod)
# =============================================================================
EMBEDDING_PROVIDER=vertex
# EMBEDDING_PROVIDER=jina  # alternative for local dev

# =============================================================================
# Custodian Pipeline
# =============================================================================
CUSTODIAN__ENABLED=false
```

### 7. .env.beta.example

New file:

```bash
# Engrammic Beta Environment Secrets
# Copy to .env.beta, fill values, then run: just secrets-push beta

# Auth (required)
WORKOS_API_KEY=
WORKOS_CLIENT_ID=
WORKOS_COOKIE_PASSWORD=

# Database
POSTGRES_PASSWORD=
MEMGRAPH_PASSWORD=
```

### 8. justfile

Add secrets sync recipes:

```makefile
# Push local .env.{env} secrets to GCP Secret Manager
secrets-push env="beta":
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Pushing secrets for {{env}} to GCP Secret Manager..."
    if [ ! -f ".env.{{env}}" ]; then
        echo "Error: .env.{{env}} not found"
        exit 1
    fi
    grep -E "^[A-Z_]+=.+" .env.{{env}} | while IFS= read -r line; do
        key=$(echo "$line" | cut -d= -f1 | tr '[:upper:]' '[:lower:]' | tr '_' '-')
        value=$(echo "$line" | cut -d= -f2-)
        secret_name="engrammic-{{env}}-$key"
        echo "  -> $secret_name"
        if gcloud secrets describe "$secret_name" &>/dev/null; then
            echo -n "$value" | gcloud secrets versions add "$secret_name" --data-file=-
        else
            echo -n "$value" | gcloud secrets create "$secret_name" --data-file=- --replication-policy=automatic
        fi
    done
    echo "Done."

# Pull GCP secrets to local .env.{env}
secrets-pull env="beta":
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Pulling secrets for {{env}} from GCP Secret Manager..."
    > .env.{{env}}
    for secret in $(gcloud secrets list --filter="name:engrammic-{{env}}" --format="value(name)"); do
        key=$(basename "$secret" | sed "s/engrammic-{{env}}-//" | tr '-' '_' | tr '[:lower:]' '[:upper:]')
        value=$(gcloud secrets versions access latest --secret="$secret" 2>/dev/null || echo "")
        if [ -n "$value" ]; then
            echo "$key=$value" >> .env.{{env}}
        fi
    done
    echo "Wrote .env.{{env}}"
```

### 9. deploy-beta.yml

Add Dagster image build step after the API image build:

```yaml
      - name: Build and push Dagster image
        run: |
          docker build -f docker/Dockerfile.dagster -t ${{ env.REGISTRY }}/engrammic-dagster:${{ github.sha }} .
          docker push ${{ env.REGISTRY }}/engrammic-dagster:${{ github.sha }}
          docker tag ${{ env.REGISTRY }}/engrammic-dagster:${{ github.sha }} ${{ env.REGISTRY }}/engrammic-dagster:latest
          docker push ${{ env.REGISTRY }}/engrammic-dagster:latest
```

## Pre-Deploy Steps

1. Create secrets in GCP Secret Manager (or use `just secrets-push beta`):
   - `engrammic-beta-workos-client-id`
   - `engrammic-beta-workos-cookie-password`

2. Build and push Dagster image:
   ```bash
   docker build -f docker/Dockerfile.dagster -t europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest .
   docker push europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest
   ```

3. Run Pulumi preview:
   ```bash
   cd infra && uv run pulumi preview --stack beta
   ```

## Verification

1. **Pulumi preview shows expected changes:**
   - StatefulHost instance type changed
   - New secrets referenced
   - New env vars added

2. **After deploy:**
   - Cloud Run health check passes
   - SSH to StatefulHost, verify all containers running:
     ```bash
     docker ps  # should show memgraph, qdrant, redis, dagster-*
     ```
   - Dagster webserver accessible via SSH tunnel:
     ```bash
     gcloud compute ssh engrammic-beta-stateful -- -L 3000:localhost:3000
     # Then open http://localhost:3000
     ```

3. **Custodian test:**
   - Trigger a Dagster job manually
   - Verify it can connect to Memgraph/Qdrant/Postgres

## Rollback

If deploy fails:
```bash
cd infra
uv run pulumi up --stack beta --target-replace "engrammic-stateful-instance"
```

Or revert to previous image tags in Pulumi config.

## Out of Scope

- Dagster Cloud (managed) - not needed for beta scale
- Auto-scaling StatefulHost - not feasible for stateful services
- Public Dagster UI - security risk, SSH tunnel sufficient
- Monitoring/alerting for Dagster - defer until post-beta
