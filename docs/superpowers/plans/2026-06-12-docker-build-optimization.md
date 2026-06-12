# Docker Build Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce CI/CD build times from 10-15 min to ~30s for code-only deploys using two-tier base images + Skaffold.

**Architecture:** Two base images (base-api, base-dagster) contain all Python dependencies. App images inherit from them and only add code. Skaffold orchestrates builds and skips unchanged images.

**Tech Stack:** Docker, Skaffold, Cloud Build, uv, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-06-12-docker-build-optimization-design.md`

---

## File Structure

**New files:**
- `docker/Dockerfile.base-api` — base image with API dependencies
- `docker/Dockerfile.base-dagster` — base image with Dagster dependencies
- `skaffold.yaml` — build orchestration config

**Modified files:**
- `docker/Dockerfile.api` — change to inherit from base-api
- `docker/Dockerfile.dagster` — change to inherit from base-dagster
- `.github/workflows/deploy-beta.yml` — replace Cloud Build with Skaffold

**Deleted files (Phase 3):**
- `deploy/cloudbuild/api.yaml`
- `deploy/cloudbuild/dagster.yaml`
- `deploy/cloudbuild/beacon.yaml`

---

## Task 1: Create Dockerfile.base-api

**Files:**
- Create: `docker/Dockerfile.base-api`

- [ ] **Step 1: Create the base-api Dockerfile**

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
      --group llm-core --group numeric --group sparse \
      --group api --group mcp --group auth
```

- [ ] **Step 2: Verify it builds locally**

Run:
```bash
docker build -f docker/Dockerfile.base-api -t base-api:test .
```

Expected: Build succeeds, image created (~500MB)

- [ ] **Step 3: Verify deps are installed**

Run:
```bash
docker run --rm base-api:test /app/.venv/bin/python -c "import fastapi; import fastmcp; print('OK')"
```

Expected: Prints "OK"

- [ ] **Step 4: Commit**

```bash
git add docker/Dockerfile.base-api
git commit -m "feat(docker): add base-api Dockerfile with all API deps"
```

---

## Task 2: Create Dockerfile.base-dagster

**Files:**
- Create: `docker/Dockerfile.base-dagster`

- [ ] **Step 1: Create the base-dagster Dockerfile**

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
      --group llm-core --group numeric --group sparse \
      --group pipelines --group custodian --group splade
```

- [ ] **Step 2: Verify it builds locally**

Run:
```bash
docker build -f docker/Dockerfile.base-dagster -t base-dagster:test .
```

Expected: Build succeeds, image created (~2.5GB due to torch)

- [ ] **Step 3: Verify deps are installed**

Run:
```bash
docker run --rm base-dagster:test /app/.venv/bin/python -c "import dagster; import torch; print('OK')"
```

Expected: Prints "OK"

- [ ] **Step 4: Commit**

```bash
git add docker/Dockerfile.base-dagster
git commit -m "feat(docker): add base-dagster Dockerfile with all Dagster deps"
```

---

## Task 3: Create skaffold.yaml

**Files:**
- Create: `skaffold.yaml`

- [ ] **Step 1: Create the Skaffold config**

```yaml
apiVersion: skaffold/v4beta11
kind: Config
metadata:
  name: engrammic

build:
  tagPolicy:
    gitCommit:
      prefix: ""
  artifacts:
    # Base images (rebuild on uv.lock change)
    - image: europe-north1-docker.pkg.dev/engrammic/engrammic/base-api
      docker:
        dockerfile: docker/Dockerfile.base-api
        cacheFrom:
          - europe-north1-docker.pkg.dev/engrammic/engrammic/base-api:latest

    - image: europe-north1-docker.pkg.dev/engrammic/engrammic/base-dagster
      docker:
        dockerfile: docker/Dockerfile.base-dagster
        cacheFrom:
          - europe-north1-docker.pkg.dev/engrammic/engrammic/base-dagster:latest

    # App images (fast, code-only)
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

    # Beacon: standalone, no base
    - image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-beacon
      docker:
        dockerfile: docker/Dockerfile.beacon

  googleCloudBuild:
    projectId: engrammic
    machineType: E2_HIGHCPU_8
    timeout: 1200s
```

- [ ] **Step 2: Validate Skaffold config**

Run:
```bash
skaffold diagnose
```

Expected: No errors (warnings about missing images are OK at this stage)

- [ ] **Step 3: Commit**

```bash
git add skaffold.yaml
git commit -m "feat(ci): add Skaffold config for build orchestration"
```

---

## Task 4: Update Dockerfile.api to use base image

**Files:**
- Modify: `docker/Dockerfile.api`

- [ ] **Step 1: Read current Dockerfile.api**

Run:
```bash
cat docker/Dockerfile.api
```

Note the current structure (builder stage + runtime stage).

- [ ] **Step 2: Replace with base-image version**

Replace entire contents of `docker/Dockerfile.api`:

```dockerfile
ARG BASE_TAG=latest
FROM europe-north1-docker.pkg.dev/engrammic/engrammic/base-api:${BASE_TAG}

WORKDIR /app

# Create non-root user
RUN groupadd -g 1000 engrammic && useradd -u 1000 -g engrammic -m engrammic

# Copy application code (deps already in base image)
COPY pyproject.toml uv.lock README.md ./
COPY config/ /app/config/
COPY src/ /app/src/
COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/
COPY skills/ /app/skills/
COPY scripts/validate_imports.py /app/scripts/

# Set environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create cache directories with proper ownership
RUN mkdir -p /app/.cache/huggingface /app/.cache/fastembed && \
    chown -R engrammic:engrammic /app/.cache

# Validate critical imports at build time
RUN SKIP_MODEL_CHECK=1 python /app/scripts/validate_imports.py

USER engrammic

EXPOSE 8000

CMD ["python", "-m", "context_service.entrypoint"]
```

- [ ] **Step 3: Test build with local base image**

Run:
```bash
docker build -f docker/Dockerfile.api \
  --build-arg BASE_TAG=test \
  -t engrammic-api:test .
```

Expected: Build succeeds quickly (no uv sync, just code copy)

- [ ] **Step 4: Verify the app starts**

Run:
```bash
docker run --rm -e SKIP_MODEL_CHECK=1 engrammic-api:test python -c "from context_service.entrypoint import app; print('OK')"
```

Expected: Prints "OK" (may have import warnings, that's fine)

- [ ] **Step 5: Commit**

```bash
git add docker/Dockerfile.api
git commit -m "feat(docker): update Dockerfile.api to use base-api image"
```

---

## Task 5: Update Dockerfile.dagster to use base image

**Files:**
- Modify: `docker/Dockerfile.dagster`

- [ ] **Step 1: Replace with base-image version**

Replace entire contents of `docker/Dockerfile.dagster`:

```dockerfile
ARG BASE_TAG=latest
FROM europe-north1-docker.pkg.dev/engrammic/engrammic/base-dagster:${BASE_TAG}

WORKDIR /app

RUN useradd -m -u 1000 dagster

# Copy application code (deps already in base image)
COPY pyproject.toml uv.lock README.md ./
COPY src/ /app/src/
COPY config/ /app/config/
COPY dagster.yaml workspace.yaml ./
COPY scripts/validate_imports.py /app/scripts/
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV DAGSTER_HOME="/app"

# Validate critical imports at build time
RUN BUILD_TARGET=dagster python /app/scripts/validate_imports.py

RUN chown -R dagster:dagster /app

USER dagster

ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 2: Test build with local base image**

Run:
```bash
docker build -f docker/Dockerfile.dagster \
  --build-arg BASE_TAG=test \
  -t engrammic-dagster:test .
```

Expected: Build succeeds quickly

- [ ] **Step 3: Commit**

```bash
git add docker/Dockerfile.dagster
git commit -m "feat(docker): update Dockerfile.dagster to use base-dagster image"
```

---

## Task 6: Update deploy-beta.yml workflow

**Files:**
- Modify: `.github/workflows/deploy-beta.yml`

- [ ] **Step 1: Read current workflow structure**

Run:
```bash
cat .github/workflows/deploy-beta.yml
```

Note: Has separate `build-api`, `build-dagster`, `build-beacon` jobs using Cloud Build.

- [ ] **Step 2: Replace build jobs with single Skaffold job**

Replace the `changes`, `build-api`, `build-beacon`, `build-dagster` jobs with:

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
    if: always() && needs.build.result == 'success'
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

      - name: Cleanup old images on VM
        run: |
          gcloud compute ssh engrammic-beta-stateful \
            --zone ${{ env.REGION }}-a \
            --tunnel-through-iap \
            --command "sudo docker image prune -af --filter 'until=72h' && sudo docker system prune -f --volumes"

      - name: Deploy to VM
        run: |
          gcloud compute ssh engrammic-beta-stateful \
            --zone ${{ env.REGION }}-a \
            --tunnel-through-iap \
            --command "cd /opt/engrammic && sudo docker compose pull && sudo docker compose up -d"

      - name: Wait for VM services to be healthy
        run: |
          sleep 30
          gcloud compute ssh engrammic-beta-stateful \
            --zone ${{ env.REGION }}-a \
            --tunnel-through-iap \
            --command "docker ps --format '{{.Names}}: {{.Status}}' | grep -E 'qdrant|memgraph|redis'"

      - name: Deploy API to Cloud Run
        run: |
          gcloud run deploy engrammic-beta-api \
            --image ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/engrammic/engrammic-api:latest \
            --region ${{ env.REGION }} \
            --min-instances 1 \
            --no-cpu-throttling \
            --session-affinity \
            --timeout 3600 \
            --no-traffic

      - name: Run migrations via Cloud Run Job
        run: |
          gcloud run jobs execute engrammic-beta-migrate \
            --region ${{ env.REGION }} \
            --wait

      - name: Route traffic to new revision
        run: |
          gcloud run services update-traffic engrammic-beta-api \
            --region ${{ env.REGION }} \
            --to-latest
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy-beta.yml
git commit -m "feat(ci): replace Cloud Build with Skaffold in deploy-beta"
```

---

## Task 7: Push base images to registry (one-time setup)

**Files:** None (manual registry push)

- [ ] **Step 1: Authenticate to Artifact Registry**

Run:
```bash
gcloud auth configure-docker europe-north1-docker.pkg.dev
```

- [ ] **Step 2: Build and push base-api**

Run:
```bash
docker build -f docker/Dockerfile.base-api \
  -t europe-north1-docker.pkg.dev/engrammic/engrammic/base-api:latest .

docker push europe-north1-docker.pkg.dev/engrammic/engrammic/base-api:latest
```

Expected: Image pushed successfully

- [ ] **Step 3: Build and push base-dagster**

Run:
```bash
docker build -f docker/Dockerfile.base-dagster \
  -t europe-north1-docker.pkg.dev/engrammic/engrammic/base-dagster:latest .

docker push europe-north1-docker.pkg.dev/engrammic/engrammic/base-dagster:latest
```

Expected: Image pushed successfully (takes a few minutes due to size)

- [ ] **Step 4: Verify images in registry**

Run:
```bash
gcloud artifacts docker images list europe-north1-docker.pkg.dev/engrammic/engrammic --filter="package:base"
```

Expected: Lists `base-api` and `base-dagster`

---

## Task 8: Test full Skaffold build

**Files:** None (validation)

- [ ] **Step 1: Run Skaffold build locally**

Run:
```bash
skaffold build --default-repo=europe-north1-docker.pkg.dev/engrammic/engrammic
```

Expected: All 5 images build successfully. Base images should be fast (cache hit), app images should be ~30s.

- [ ] **Step 2: Verify build times**

Check output for timing. App images (engrammic-api, engrammic-dagster, engrammic-beacon) should each take <1 minute.

---

## Task 9: Cleanup old Cloud Build configs

**Files:**
- Delete: `deploy/cloudbuild/api.yaml`
- Delete: `deploy/cloudbuild/dagster.yaml`
- Delete: `deploy/cloudbuild/beacon.yaml`

- [ ] **Step 1: Remove old Cloud Build configs**

Run:
```bash
git rm deploy/cloudbuild/api.yaml deploy/cloudbuild/dagster.yaml deploy/cloudbuild/beacon.yaml
```

- [ ] **Step 2: Check if cloudbuild directory is now empty**

Run:
```bash
ls deploy/cloudbuild/
```

If empty, remove the directory:
```bash
rmdir deploy/cloudbuild
```

- [ ] **Step 3: Commit cleanup**

```bash
git commit -m "chore(ci): remove old Cloud Build configs (replaced by Skaffold)"
```

---

## Task 10: Update justfile (if needed)

**Files:**
- Modify: `justfile` (if it references old build commands)

- [ ] **Step 1: Check justfile for docker/build references**

Run:
```bash
grep -n "cloudbuild\|docker build" justfile || echo "No matches"
```

- [ ] **Step 2: Add Skaffold commands if useful**

If there are existing docker build commands, consider adding:

```just
# Build all images via Skaffold
build-images:
    skaffold build --default-repo=europe-north1-docker.pkg.dev/engrammic/engrammic

# Build base images only (run after uv.lock changes)
build-bases:
    docker build -f docker/Dockerfile.base-api -t europe-north1-docker.pkg.dev/engrammic/engrammic/base-api:latest .
    docker build -f docker/Dockerfile.base-dagster -t europe-north1-docker.pkg.dev/engrammic/engrammic/base-dagster:latest .
```

- [ ] **Step 3: Commit if changes made**

```bash
git add justfile
git commit -m "chore: add Skaffold build commands to justfile"
```

---

## Summary

After completing all tasks:

1. Base images (`base-api`, `base-dagster`) contain all deps, rebuild only on `uv.lock` change
2. App images inherit from bases, build in ~30s (code copy only)
3. Skaffold orchestrates builds and handles dependency ordering
4. `deploy-beta.yml` uses single `skaffold build` instead of separate Cloud Build jobs
5. Old Cloud Build configs removed

**Expected impact:**
- Code-only deploys: 10-15 min → ~30s
- Dep change deploys: 10-15 min → 3-5 min
