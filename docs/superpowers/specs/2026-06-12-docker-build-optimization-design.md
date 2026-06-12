# Docker Build Optimization: Three-Tier Base Images + Skaffold

## Problem

Current CI/CD builds take 10-15 minutes per deploy. Each Dockerfile (api, dagster, beacon) independently installs ~2GB of Python dependencies, even though most are shared. This causes:

- Slow deploys (uv sync 2-8 min per image)
- Cloud Run cold start latency (large images)
- Memory overhead (deps loaded that aren't used)
- Registry pull latency on scaling

## Solution

Three-tier base image hierarchy managed by Skaffold:

```
base-common (shared deps, ~400MB)
├── base-api (+ api/mcp/auth, ~100MB)
│   └── engrammic-api (+ code, ~10MB)
└── base-dagster (+ pipelines/splade, ~2GB)
    └── engrammic-dagster (+ code, ~10MB)

engrammic-beacon (standalone, python:slim)
```

Skaffold handles build ordering and skips unchanged images automatically.

## Image Hierarchy

### Registry Structure

```
europe-north1-docker.pkg.dev/engrammic/engrammic/
├── base-common:latest
├── base-common:<lock-hash>
├── base-api:latest
├── base-dagster:latest
├── engrammic-api:latest
├── engrammic-dagster:latest
└── engrammic-beacon:latest
```

### Dependency Groups Per Image

| Image | Dependency Groups | Est. Size |
|-------|-------------------|-----------|
| base-common | graph, postgres, redis, llm-core, numeric, sparse | ~400MB |
| base-api | + api, mcp, auth | ~100MB delta |
| base-dagster | + pipelines, custodian, splade | ~2GB delta |
| engrammic-beacon | standalone (no base) | ~200MB |

## Dockerfiles

### Dockerfile.base-common

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./

ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
      --group graph --group postgres --group redis \
      --group llm-core --group numeric --group sparse
```

### Dockerfile.base-api

```dockerfile
ARG BASE_TAG=latest
FROM europe-north1-docker.pkg.dev/engrammic/engrammic/base-common:${BASE_TAG}

COPY pyproject.toml uv.lock README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
      --group api --group mcp --group auth
```

### Dockerfile.base-dagster

```dockerfile
ARG BASE_TAG=latest
FROM europe-north1-docker.pkg.dev/engrammic/engrammic/base-common:${BASE_TAG}

COPY pyproject.toml uv.lock README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
      --group pipelines --group custodian --group splade
```

### Dockerfile.api (updated)

```dockerfile
ARG BASE_TAG=latest
FROM europe-north1-docker.pkg.dev/engrammic/engrammic/base-api:${BASE_TAG}

WORKDIR /app

RUN groupadd -g 1000 engrammic && useradd -u 1000 -g engrammic -m engrammic

COPY pyproject.toml uv.lock README.md ./
COPY config/ /app/config/
COPY src/ /app/src/
COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/
COPY skills/ /app/skills/
COPY scripts/validate_imports.py /app/scripts/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /app/.cache/huggingface /app/.cache/fastembed && \
    chown -R engrammic:engrammic /app/.cache

RUN SKIP_MODEL_CHECK=1 python /app/scripts/validate_imports.py

USER engrammic

EXPOSE 8000

CMD ["python", "-m", "context_service.entrypoint"]
```

## Skaffold Configuration

```yaml
# skaffold.yaml
apiVersion: skaffold/v4beta11
kind: Config
metadata:
  name: engrammic

build:
  tagPolicy:
    gitCommit:
      prefix: ""
  artifacts:
    - image: europe-north1-docker.pkg.dev/engrammic/engrammic/base-common
      docker:
        dockerfile: docker/Dockerfile.base-common
        cacheFrom:
          - europe-north1-docker.pkg.dev/engrammic/engrammic/base-common:latest

    - image: europe-north1-docker.pkg.dev/engrammic/engrammic/base-api
      docker:
        dockerfile: docker/Dockerfile.base-api
      requires:
        - image: europe-north1-docker.pkg.dev/engrammic/engrammic/base-common

    - image: europe-north1-docker.pkg.dev/engrammic/engrammic/base-dagster
      docker:
        dockerfile: docker/Dockerfile.base-dagster
      requires:
        - image: europe-north1-docker.pkg.dev/engrammic/engrammic/base-common

    - image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-api
      docker:
        dockerfile: docker/Dockerfile.api
      requires:
        - image: europe-north1-docker.pkg.dev/engrammic/engrammic/base-api

    - image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster
      docker:
        dockerfile: docker/Dockerfile.dagster
      requires:
        - image: europe-north1-docker.pkg.dev/engrammic/engrammic/base-dagster

    - image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-beacon
      docker:
        dockerfile: docker/Dockerfile.beacon

  googleCloudBuild:
    projectId: engrammic
    machineType: E2_HIGHCPU_8
    timeout: 1200s
```

## CI/CD Workflow

### deploy-beta.yml (updated)

```yaml
name: Deploy Beta

on:
  push:
    branches: [beta]
  workflow_dispatch:

env:
  REGION: europe-north1
  PROJECT_ID: engrammic

jobs:
  build:
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
          token_format: access_token

      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v2

      - name: Install Skaffold
        run: |
          curl -Lo skaffold https://storage.googleapis.com/skaffold/releases/latest/skaffold-linux-amd64
          chmod +x skaffold && sudo mv skaffold /usr/local/bin/

      - name: Build & Push via Skaffold
        run: skaffold build --file-output=tags.json

  deploy:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    steps:
      # ... existing deploy steps (Cloud Run, VM, migrations) unchanged
```

## Rollout Strategy

### Phase 1: Add New Files (no disruption)

- Create `docker/Dockerfile.base-common`
- Create `docker/Dockerfile.base-api`
- Create `docker/Dockerfile.base-dagster`
- Create `skaffold.yaml`
- Manually build and push base images once

### Phase 2: Migrate CI (single PR)

- Update `deploy-beta.yml` to use Skaffold
- Update `Dockerfile.api` and `Dockerfile.dagster` to use `FROM base-*`
- Test on feature branch before merging

### Phase 3: Cleanup

- Remove `deploy/cloudbuild/api.yaml`, `dagster.yaml`, `beacon.yaml`
- Update justfile if needed
- Update documentation

### Phase 4: Selfhosted (optional, future)

Selfhosted images (`Dockerfile.selfhosted.*`) could reuse `base-common` but have a Cython compilation step. Since releases are infrequent and GHA cache is adequate, this is lower priority.

If implemented later:
- Selfhosted Dockerfiles would `FROM base-common` then add Cython step
- Reduces release build time by ~3-5 minutes

## Rollback Plan

- Keep old Dockerfiles functional for 1 week (comment out `FROM base-*`)
- Old Cloud Build configs remain in git history
- Skaffold can be removed by reverting to direct `docker build` calls

## Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Code-only deploy | 10-15 min | ~30s |
| Dep change deploy | 10-15 min | 3-5 min |
| Cold start (API) | ~15s | ~8s |
| Image size (API) | ~1.2GB | ~600MB |

## Files to Create/Modify

**New files:**
- `docker/Dockerfile.base-common`
- `docker/Dockerfile.base-api`
- `docker/Dockerfile.base-dagster`
- `skaffold.yaml`

**Modified files:**
- `docker/Dockerfile.api`
- `docker/Dockerfile.dagster`
- `.github/workflows/deploy-beta.yml`

**Deleted files (Phase 3):**
- `deploy/cloudbuild/api.yaml`
- `deploy/cloudbuild/dagster.yaml`
- `deploy/cloudbuild/beacon.yaml`
