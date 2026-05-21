# Deployment Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean separation between infrastructure (Pulumi) and deployments (CI), with SHA-based tagging and unified migrations.

**Architecture:** Pulumi manages Cloud Run service config but ignores image tag. GitHub Actions builds images and deploys. Same image promotes from beta to prod. Feature flags via env vars control per-environment behavior.

**Tech Stack:** Pulumi (Python), GitHub Actions, Cloud Build, Cloud Run, Artifact Registry

**Spec:** `docs/superpowers/specs/2026-05-20-deployment-pipeline-design.md`

---

### Task 1: Add ignore_changes to Cloud Run components

**Files:**
- Modify: `infra/components/cloudrun.py`
- Modify: `infra/components/beacon.py`
- Modify: `infra/components/migration_job.py`

- [ ] **Step 1: Update ContextServiceRun to ignore template changes**

In `infra/components/cloudrun.py`, add `ignore_changes` to the Service resource:

```python
# Cloud Run v2 Service
self.service = cloudrunv2.Service(
    f"{name}-service",
    name=f"engrammic-{env}-api",
    location=region,
    deletion_protection=False,
    template=cloudrunv2.ServiceTemplateArgs(
        # ... existing template config ...
    ),
    opts=pulumi.ResourceOptions(
        parent=self,
        ignore_changes=["template"],  # CI owns image updates
    ),
)
```

Change the `opts` parameter from just `parent=self` to include `ignore_changes`.

- [ ] **Step 2: Update BeaconServiceRun similarly**

In `infra/components/beacon.py`, add the same `ignore_changes` to the Service resource:

```python
opts=pulumi.ResourceOptions(
    parent=self,
    ignore_changes=["template"],
),
```

- [ ] **Step 3: Update MigrationJob similarly**

In `infra/components/migration_job.py`, add `ignore_changes` to the Job resource:

```python
opts=pulumi.ResourceOptions(
    parent=self,
    ignore_changes=["template"],
),
```

- [ ] **Step 4: Verify Pulumi preview shows no drift**

```bash
cd infra && pulumi preview --stack beta
```

Expected: No changes to Cloud Run services (image changes ignored).

- [ ] **Step 5: Commit**

```bash
git add infra/components/cloudrun.py infra/components/beacon.py infra/components/migration_job.py
git commit -m "infra: ignore template changes in Cloud Run (CI owns image)"
```

---

### Task 2: Add feature flags env vars to Pulumi

**Files:**
- Modify: `infra/__main__.py`

- [ ] **Step 1: Define feature flags config**

Add feature flags dict near the top of `infra/__main__.py` (after the `config` lines):

```python
config = pulumi.Config()
use_cloudsql = config.get_bool("use_cloudsql") or False
env = config.require("environment")

# Feature flags per environment
feature_flags = {
    "beta": {
        "ENABLE_EXPERIMENTAL_RECALL": "true",
        "ENABLE_DEBUG_ENDPOINTS": "true",
    },
    "prod": {
        "ENABLE_EXPERIMENTAL_RECALL": "false",
        "ENABLE_DEBUG_ENDPOINTS": "false",
    },
    "dev": {
        "ENABLE_EXPERIMENTAL_RECALL": "true",
        "ENABLE_DEBUG_ENDPOINTS": "true",
    },
}
```

- [ ] **Step 2: Merge feature flags into env_vars**

Update the `ContextServiceRun` call to include feature flags:

```python
context_service = ContextServiceRun(
    "engrammic-context-service",
    vpc_id=network.vpc.id,
    connector_subnet_id=network.private_subnet.name,
    service_account_email=iam.context_service_run.email,
    image="europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-api:latest",
    env_vars={
        "ENVIRONMENT": env,
        # ... existing env vars ...
        "OAUTH__ISSUER": "https://api.engrammic.ai" if env == "prod" else f"https://{env}.engrammic.ai",
        # Feature flags
        **feature_flags.get(env, {}),
    },
    secrets={...},
)
```

- [ ] **Step 3: Commit**

```bash
git add infra/__main__.py
git commit -m "infra: add feature flags env vars per environment"
```

---

### Task 3: Update deploy-beta.yml workflow

**Files:**
- Modify: `.github/workflows/deploy-beta.yml`

- [ ] **Step 1: Change trigger from beta to main branch**

```yaml
name: Deploy Beta

on:
  push:
    branches: [main]  # Changed from [beta]
  workflow_dispatch:
```

- [ ] **Step 2: Fix migration job name**

Change line ~59 from:
```yaml
gcloud run jobs execute engrammic-migrate-beta \
```

To:
```yaml
gcloud run jobs execute engrammic-beta-migrate \
```

- [ ] **Step 3: Add SHORT_SHA for consistent tagging**

After checkout step, add:
```yaml
- name: Set short SHA
  run: echo "SHORT_SHA=${GITHUB_SHA:0:7}" >> $GITHUB_ENV
```

Update Cloud Build steps to use `${{ env.SHORT_SHA }}`:
```yaml
- name: Build API image with Cloud Build
  run: |
    gcloud builds submit --config cloudbuild.api.yaml --timeout 600s \
      --substitutions SHORT_SHA=${{ env.SHORT_SHA }}
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy-beta.yml
git commit -m "ci(beta): trigger on main, fix migration job name, use short SHA"
```

---

### Task 4: Rewrite deploy-prod.yml for promotion

**Files:**
- Modify: `.github/workflows/deploy-prod.yml`

- [ ] **Step 1: Replace entire workflow with promotion-based approach**

```yaml
name: Deploy Production

on:
  workflow_dispatch:
    inputs:
      sha:
        description: 'SHA to promote (7 chars, from beta deploy)'
        required: true
        type: string
      confirm_deploy:
        description: 'Type "deploy" to confirm'
        required: true
        type: string

env:
  REGION: europe-north1
  PROJECT_ID: engrammic
  REGISTRY: europe-north1-docker.pkg.dev/engrammic/engrammic

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Validate confirmation
        if: ${{ github.event.inputs.confirm_deploy != 'deploy' }}
        run: |
          echo "Must type 'deploy' to confirm"
          exit 1

  deploy:
    needs: validate
    runs-on: ubuntu-latest
    environment: production
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

      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v2

      - name: Verify images exist
        run: |
          gcloud artifacts docker images describe ${{ env.REGISTRY }}/engrammic-api:${{ github.event.inputs.sha }} --quiet
          gcloud artifacts docker images describe ${{ env.REGISTRY }}/engrammic-beacon:${{ github.event.inputs.sha }} --quiet

      - name: Deploy API (no traffic)
        run: |
          gcloud run services update engrammic-prod-api \
            --image ${{ env.REGISTRY }}/engrammic-api:${{ github.event.inputs.sha }} \
            --region ${{ env.REGION }} \
            --no-traffic

      - name: Deploy Beacon (no traffic)
        run: |
          gcloud run services update engrammic-prod-beacon \
            --image ${{ env.REGISTRY }}/engrammic-beacon:${{ github.event.inputs.sha }} \
            --region ${{ env.REGION }} \
            --no-traffic

      - name: Run migrations
        run: |
          gcloud run jobs execute engrammic-prod-migrate \
            --region ${{ env.REGION }} \
            --wait

      - name: Route traffic
        run: |
          gcloud run services update-traffic engrammic-prod-api \
            --region ${{ env.REGION }} \
            --to-latest
          gcloud run services update-traffic engrammic-prod-beacon \
            --region ${{ env.REGION }} \
            --to-latest

      - name: Summary
        run: |
          echo "Deployed SHA ${{ github.event.inputs.sha }} to production"
          echo "API: https://api.engrammic.ai"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy-prod.yml
git commit -m "ci(prod): promote existing SHA instead of rebuilding"
```

---

### Task 5: Simplify justfile commands

**Files:**
- Modify: `justfile`

- [ ] **Step 1: Replace build commands**

Find and replace the build commands section (~lines 130-155):

```just
# =============================================================================
# Build & Deploy
# =============================================================================

# Build all images (tags :latest + :SHORT_SHA)
build sha="latest":
    gcloud builds submit --config=cloudbuild.api.yaml \
        --substitutions=SHORT_SHA={{sha}} --region={{region}} .
    gcloud builds submit --config=cloudbuild.beacon.yaml \
        --substitutions=SHORT_SHA={{sha}} --region={{region}} .
    gcloud builds submit --config=cloudbuild.dagster.yaml \
        --substitutions=SHORT_SHA={{sha}} --region={{region}} .

# Deploy specific SHA to beta
deploy-beta sha="latest":
    gcloud run services update engrammic-beta-api \
        --image={{registry}}/engrammic-api:{{sha}} --region={{region}} --project={{project}}
    gcloud run services update engrammic-beta-beacon \
        --image={{registry}}/engrammic-beacon:{{sha}} --region={{region}} --project={{project}}
    gcloud run jobs execute engrammic-beta-migrate --region={{region}} --project={{project}} --wait

# Promote SHA to prod
deploy-prod sha:
    gcloud run services update engrammic-prod-api \
        --image={{registry}}/engrammic-api:{{sha}} --region={{region}} --project={{project}}
    gcloud run services update engrammic-prod-beacon \
        --image={{registry}}/engrammic-beacon:{{sha}} --region={{region}} --project={{project}}
    gcloud run jobs execute engrammic-prod-migrate --region={{region}} --project={{project}} --wait

# Build + deploy to beta (convenience)
ship-beta sha="latest":
    just build {{sha}}
    just deploy-beta {{sha}}
```

- [ ] **Step 2: Remove old commands**

Delete these commands if they still exist:
- `build-api`
- `build-beacon`
- `build-dagster`
- `deploy-api-beta`
- `deploy-api-prod`
- `build-all`

- [ ] **Step 3: Commit**

```bash
git add justfile
git commit -m "build: simplify justfile with unified build/deploy commands"
```

---

### Task 6: Add Artifact Registry lifecycle policy

**Files:**
- Modify: `infra/components/storage.py` (or create new component)

- [ ] **Step 1: Check if Artifact Registry is managed by Pulumi**

```bash
grep -r "artifactregistry" infra/
```

If not managed, add it to Pulumi. If managed via console, skip this task.

- [ ] **Step 2: Add cleanup policy to existing or new component**

If adding to Pulumi:

```python
from pulumi_gcp import artifactregistry

repo = artifactregistry.Repository(
    "engrammic-repo",
    repository_id="engrammic",
    location=region,
    format="DOCKER",
    cleanup_policies=[
        artifactregistry.RepositoryCleanupPolicyArgs(
            id="delete-old-untagged",
            action="DELETE",
            condition=artifactregistry.RepositoryCleanupPolicyConditionArgs(
                older_than="2592000s",  # 30 days
                tag_state="UNTAGGED",
            ),
        ),
    ],
    opts=pulumi.ResourceOptions(protect=True),
)
```

- [ ] **Step 3: Commit (if changes made)**

```bash
git add infra/
git commit -m "infra: add Artifact Registry cleanup policy (30 days)"
```

---

### Task 7: Test the pipeline

**Files:** None (verification only)

- [ ] **Step 1: Test Pulumi ignores image changes**

```bash
cd infra && pulumi preview --stack beta
```

Expected: No pending changes (or only feature flag env var additions).

- [ ] **Step 2: Test local build command**

```bash
just build test123
```

Expected: All three images build and are tagged with `:latest` and `:test123`.

- [ ] **Step 3: Test local deploy-beta**

```bash
just deploy-beta latest
```

Expected: Services update, migration runs.

- [ ] **Step 4: Verify beta is working**

```bash
curl https://beta.engrammic.ai/health
```

Expected: `{"status": "healthy", ...}`

- [ ] **Step 5: Push and verify GitHub Actions**

```bash
git push
```

Watch the GitHub Actions run. Expected: beta deploy workflow triggers on push to main.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "ci: deployment pipeline refactor complete"
```

---

## Verification Checklist

- [ ] Push to main auto-deploys to beta
- [ ] `pulumi up` doesn't touch image tags
- [ ] Prod workflow accepts SHA input and promotes (no rebuild)
- [ ] Migration job names are consistent (`engrammic-{env}-migrate`)
- [ ] `just ship-beta` builds and deploys in one command
- [ ] `just deploy-prod <sha>` promotes to prod
