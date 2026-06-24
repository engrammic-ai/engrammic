# Pulumi Beta Deployment Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix broken GCP beta deployment by adding Dagster, completing env vars, fixing database name inconsistency, and adding secrets sync workflow.

**Architecture:** StatefulHost runs Memgraph/Qdrant/Redis/Dagster on e2-standard-4. Cloud Run runs API with full env config. Cloud SQL IP passed via instance metadata. Secrets sync via justfile recipes.

**Tech Stack:** Pulumi (Python), Docker, GCP (Cloud Run, GCE, Secret Manager), GitHub Actions

---

## File Structure

| File | Responsibility |
|------|----------------|
| `docker/Dockerfile.dagster` | Dagster image for code-server, webserver, daemon |
| `infra/Pulumi.beta.yaml` | Beta stack config (instance size) |
| `infra/__main__.py` | Pulumi entrypoint - env vars, secrets, resource wiring |
| `infra/components/secrets.py` | Secret Manager resource definitions |
| `infra/components/compute.py` | StatefulHost GCE instance + docker-compose |
| `src/context_service/config/settings.py` | App settings with env var defaults |
| `.env.example` | Local dev env template |
| `.env.beta.example` | Beta secrets template |
| `justfile` | Dev commands including secrets sync |
| `.github/workflows/deploy-beta.yml` | CI/CD for beta branch |

---

## Task 1: Fix Database Name Inconsistency

**Files:**
- Modify: `src/context_service/config/settings.py:1081`
- Modify: `infra/components/compute.py:59,79,97,114`
- Modify: `.env.example`

- [ ] **Step 1: Fix settings.py default**

Edit `src/context_service/config/settings.py` line ~1081, change:

```python
postgres_database: str = Field(default="engrammic")
```

- [ ] **Step 2: Fix compute.py DAGSTER_SERVICES**

Edit `infra/components/compute.py`, in DAGSTER_SERVICES template, change all occurrences of `POSTGRES_DATABASE=context_service` to `POSTGRES_DATABASE=engrammic` (lines 59, 79, 97).

- [ ] **Step 3: Fix compute.py POSTGRES_SERVICE**

Edit `infra/components/compute.py`, in POSTGRES_SERVICE template line 114, change:

```python
      - POSTGRES_DB=engrammic
```

- [ ] **Step 4: Fix .env.example**

Edit `.env.example`, find `POSTGRES_DATABASE=context_service` and change to:

```bash
POSTGRES_DATABASE=engrammic
```

- [ ] **Step 5: Verify no other occurrences**

Run:
```bash
grep -r "context_service" src/context_service/config/ infra/ .env* --include="*.py" --include="*.yaml" --include="*.yml" --include=".env*" | grep -v ".pyc"
```

Expected: No matches related to database name.

- [ ] **Step 6: Commit**

```bash
git add src/context_service/config/settings.py infra/components/compute.py .env.example
git commit -m "fix: standardize database name to engrammic across all configs"
```

---

## Task 2: Create Dockerfile.dagster

**Files:**
- Create: `docker/Dockerfile.dagster`

- [ ] **Step 1: Create the Dockerfile**

Create `docker/Dockerfile.dagster`:

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

- [ ] **Step 2: Verify build locally**

Run:
```bash
docker build -f docker/Dockerfile.dagster -t engrammic-dagster:test .
```

Expected: Build completes successfully.

- [ ] **Step 3: Test image starts**

Run:
```bash
docker run --rm engrammic-dagster:test dagster --version
```

Expected: Prints Dagster version.

- [ ] **Step 4: Commit**

```bash
git add docker/Dockerfile.dagster
git commit -m "feat(docker): add Dagster Dockerfile for Custodian pipeline"
```

---

## Task 3: Add New Secrets to secrets.py

**Files:**
- Modify: `infra/components/secrets.py:16-19`

- [ ] **Step 1: Add new secret names**

Edit `infra/components/secrets.py`, update `secret_names` list:

```python
        secret_names = [
            "postgres-password",
            "memgraph-password",
            "workos-api-key",
            "workos-client-id",
            "workos-cookie-password",
        ]
```

- [ ] **Step 2: Commit**

```bash
git add infra/components/secrets.py
git commit -m "feat(infra): add WorkOS client-id and cookie-password secrets"
```

---

## Task 4: Update compute.py with postgres_host and Metadata

**Files:**
- Modify: `infra/components/compute.py:119-129,257-265,273-287,330-362`

- [ ] **Step 1: Add postgres_host parameter to __init__**

Edit `infra/components/compute.py`, update the `__init__` signature at line ~122:

```python
    def __init__(
        self,
        name: str,
        network: compute.Network,
        subnet: compute.Subnetwork,
        service_account_email: str,
        postgres_host: pulumi.Input[str] | None = None,
        opts: pulumi.ResourceOptions | None = None,
    ):
```

- [ ] **Step 2: Store postgres_host for use in startup script**

After line ~142 (after `zone = gcp_config.require("zone")`), add:

```python
        self._postgres_host = postgres_host
```

- [ ] **Step 3: Update startup script to use metadata**

Find the startup script section (around line 273-287) where it handles POSTGRES_HOST. Replace:

```bash
# Fetch secrets from Secret Manager
echo "Fetching Postgres password from Secret Manager..."
export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="engrammic-$ENV-postgres-password" --project="$PROJECT" 2>/dev/null || echo "devpassword")

# Set POSTGRES_HOST based on Cloud SQL config
if [ "$USE_CLOUDSQL" = "true" ]; then
    # Fetch Cloud SQL private IP from Secret Manager
    export POSTGRES_HOST=$(gcloud secrets versions access latest --secret="engrammic-$ENV-postgres-host" --project="$PROJECT" 2>/dev/null || echo "")
    if [ -z "$POSTGRES_HOST" ]; then
        echo "ERROR: POSTGRES_HOST secret not found for Cloud SQL deployment"
        exit 1
    fi
else
    export POSTGRES_HOST=postgres
fi
```

With:

```bash
# Fetch secrets from Secret Manager
echo "Fetching Postgres password from Secret Manager..."
export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="engrammic-$ENV-postgres-password" --project="$PROJECT" 2>/dev/null || echo "devpassword")

# Set POSTGRES_HOST based on Cloud SQL config
if [ "$USE_CLOUDSQL" = "true" ]; then
    # Read Cloud SQL IP from instance metadata (set by Pulumi)
    export POSTGRES_HOST=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/postgres-host" -H "Metadata-Flavor: Google")
    if [ -z "$POSTGRES_HOST" ]; then
        echo "ERROR: postgres-host metadata not found"
        exit 1
    fi
else
    export POSTGRES_HOST=postgres
fi
```

- [ ] **Step 4: Add metadata to Instance resource**

Find the `compute.Instance` definition (around line 330). Add `metadata` parameter after `tags`:

```python
            tags=["stateful-host"],
            metadata={
                "postgres-host": self._postgres_host or "postgres",
            },
            allow_stopping_for_update=True,
```

- [ ] **Step 5: Update DAGSTER_SERVICES with Vertex/Custodian env vars**

The DAGSTER_SERVICES template already exists but needs Vertex AI and Custodian env vars. Find DAGSTER_SERVICES (around line 44) and ensure each service's environment section includes:

```yaml
      - VERTEX_PROJECT_ID=engrammic
      - VERTEX_LOCATION=europe-north1
      - EMBEDDING_PROVIDER=vertex
      - LLM_PROVIDER=vertex_gemini
      - DEFAULT_LLM_MODEL=gemini-2.5-flash
      - CUSTODIAN__ENABLED=true
```

- [ ] **Step 6: Commit**

```bash
git add infra/components/compute.py
git commit -m "feat(infra): add postgres_host metadata and Vertex/Custodian env vars to StatefulHost"
```

---

## Task 5: Update __main__.py with Env Vars and Secrets

**Files:**
- Modify: `infra/__main__.py:31-36,56-81`

- [ ] **Step 1: Pass postgres_host to StatefulHost**

Edit `infra/__main__.py`, update the StatefulHost instantiation (around line 31):

```python
stateful_host = StatefulHost(
    "engrammic-stateful",
    network=network.vpc,
    subnet=network.private_subnet,
    service_account_email=iam.stateful_host.email,
    postgres_host=postgres_host if use_cloudsql else None,
)
```

Note: This requires moving the `postgres_host` definition before StatefulHost. Update the order:

```python
# Cloud SQL (if enabled) - define postgres_host early for StatefulHost
cloudsql = None
if use_cloudsql:
    cloudsql = CloudSQLPostgres(
        "engrammic-cloudsql",
        network_id=network.vpc.id,
        private_connection=network.private_connection,
    )
    postgres_host = cloudsql.instance.private_ip_address
else:
    postgres_host = None  # Will be set after StatefulHost

# Stateful host
stateful_host = StatefulHost(
    "engrammic-stateful",
    network=network.vpc,
    subnet=network.private_subnet,
    service_account_email=iam.stateful_host.email,
    postgres_host=postgres_host,
)

# Set postgres_host from StatefulHost if not using Cloud SQL
if not use_cloudsql:
    postgres_host = stateful_host.instance.network_interfaces[0].network_ip
```

- [ ] **Step 2: Add new env vars to Cloud Run**

Edit the `env_vars` dict (around line 56), add after existing entries:

```python
    "HOST": "0.0.0.0",
    "PORT": "8000",
    "EMBEDDING_PROVIDER": "vertex",
    "LLM_PROVIDER": "vertex_gemini",
    "DEFAULT_LLM_MODEL": "gemini-2.5-flash",
    "AUTH_ENABLED": "true",
    "CUSTODIAN__ENABLED": "true",
    "LOG_LEVEL": "INFO",
```

- [ ] **Step 3: Add new secrets**

Edit the `secrets` dict (around line 76), add:

```python
    "WORKOS_CLIENT_ID": secrets.secrets["workos-client-id"].id,
    "WORKOS_COOKIE_PASSWORD": secrets.secrets["workos-cookie-password"].id,
```

- [ ] **Step 4: Verify syntax**

Run:
```bash
cd infra && python -c "import __main__" 2>&1 | head -5
```

Expected: No syntax errors.

- [ ] **Step 5: Commit**

```bash
git add infra/__main__.py
git commit -m "feat(infra): add Cloud Run env vars, auth secrets, and postgres_host wiring"
```

---

## Task 6: Upgrade Pulumi.beta.yaml Instance Type

**Files:**
- Modify: `infra/Pulumi.beta.yaml:7`

- [ ] **Step 1: Update instance type**

Edit `infra/Pulumi.beta.yaml`, change line 7:

```yaml
  engrammic-infra:instance_type: e2-standard-4
```

- [ ] **Step 2: Commit**

```bash
git add infra/Pulumi.beta.yaml
git commit -m "feat(infra): upgrade beta StatefulHost to e2-standard-4 for Dagster"
```

---

## Task 7: Update Local Env Files

**Files:**
- Modify: `.env.example`
- Modify: `.env` (local dev)
- Create: `.env.beta.example`
- Create: `.env.beta` (from example, with placeholder values)

- [ ] **Step 1: Update .env.example with new sections**

Edit `.env.example`, add after the existing Auth section (or create it if missing):

```bash
# =============================================================================
# Auth (required for beta/prod)
# =============================================================================
AUTH_ENABLED=false
WORKOS_API_KEY=
WORKOS_CLIENT_ID=
WORKOS_COOKIE_PASSWORD=

# =============================================================================
# Embeddings Provider
# =============================================================================
EMBEDDING_PROVIDER=vertex
# EMBEDDING_PROVIDER=jina  # alternative for local dev

# =============================================================================
# Custodian Pipeline
# =============================================================================
CUSTODIAN__ENABLED=false
```

- [ ] **Step 2: Create .env.beta.example**

Create `.env.beta.example`:

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

- [ ] **Step 3: Commit**

```bash
git add .env.example .env.beta.example
git commit -m "docs: add auth/embedding/custodian config to env examples"
```

---

## Task 8: Add Justfile Secrets Recipes

**Files:**
- Modify: `justfile`

- [ ] **Step 1: Add secrets-push recipe**

Edit `justfile`, add at the end:

```makefile
# --- Secrets Management ---

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

- [ ] **Step 2: Verify just lists new commands**

Run:
```bash
just --list | grep secrets
```

Expected: Shows `secrets-push` and `secrets-pull`.

- [ ] **Step 3: Commit**

```bash
git add justfile
git commit -m "feat: add secrets-push and secrets-pull justfile recipes"
```

---

## Task 9: Update deploy-beta.yml with Dagster Build

**Files:**
- Modify: `.github/workflows/deploy-beta.yml:40-48`

- [ ] **Step 1: Add Dagster build step**

Edit `.github/workflows/deploy-beta.yml`, add after the Beacon image build step (after line 48):

```yaml
      - name: Build Dagster image with Cloud Build
        run: |
          gcloud builds submit \
            --tag ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/engrammic/engrammic-dagster:${{ github.sha }} \
            --dockerfile docker/Dockerfile.dagster \
            --timeout 600s
          gcloud artifacts docker tags add \
            ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/engrammic/engrammic-dagster:${{ github.sha }} \
            ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/engrammic/engrammic-dagster:latest
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy-beta.yml
git commit -m "ci: add Dagster image build to beta deployment workflow"
```

---

## Task 10: Verification

**Files:** None (verification only)

- [ ] **Step 1: Run Pulumi preview**

Run:
```bash
cd infra && uv run pulumi preview --stack beta
```

Expected: Shows changes for:
- StatefulHost instance type change (replacement)
- New secret references
- Updated Cloud Run env vars

- [ ] **Step 2: Verify Dockerfile builds**

Run:
```bash
docker build -f docker/Dockerfile.dagster -t engrammic-dagster:verify .
```

Expected: Build completes.

- [ ] **Step 3: Run lint/typecheck**

Run:
```bash
just check
```

Expected: Passes with no errors.

- [ ] **Step 4: Create final commit summary**

Run:
```bash
git log --oneline -10
```

Verify commits are:
1. fix: standardize database name to engrammic across all configs
2. feat(docker): add Dagster Dockerfile for Custodian pipeline
3. feat(infra): add WorkOS client-id and cookie-password secrets
4. feat(infra): add postgres_host metadata and Vertex/Custodian env vars to StatefulHost
5. feat(infra): add Cloud Run env vars, auth secrets, and postgres_host wiring
6. feat(infra): upgrade beta StatefulHost to e2-standard-4 for Dagster
7. docs: add auth/embedding/custodian config to env examples
8. feat: add secrets-push and secrets-pull justfile recipes
9. ci: add Dagster image build to beta deployment workflow

---

## Pre-Deploy Checklist

After implementation, before running `pulumi up`:

1. [ ] Populate secrets in GCP Secret Manager:
   ```bash
   cp .env.beta.example .env.beta
   # Edit .env.beta with real values
   just secrets-push beta
   ```

2. [ ] Build and push Dagster image manually (first time):
   ```bash
   gcloud auth configure-docker europe-north1-docker.pkg.dev
   docker build -f docker/Dockerfile.dagster -t europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest .
   docker push europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest
   ```

3. [ ] Schedule maintenance window (~5 min outage for StatefulHost resize)

4. [ ] Run deployment:
   ```bash
   cd infra && uv run pulumi up --stack beta
   ```
