# Deployment Pipeline Design

**Date:** 2026-05-20  
**Status:** Ready for implementation

## Summary

Clean separation between infrastructure (Pulumi) and deployments (GitHub Actions). Same image promotes from beta to prod. Feature flags control per-environment behavior.

## Current Problems

1. Beta deploys bypass Pulumi, causing state drift
2. Inconsistent patterns between beta/prod (direct gcloud vs Pulumi)
3. Migration job name mismatches (`engrammic-migrate-beta` vs `engrammic-beta-migrate`)
4. No clear rollback story
5. Pulumi and CI fight over Cloud Run image tag
6. Beta workflow triggers on `beta` branch instead of `main`
7. Prod workflow rebuilds images instead of promoting existing SHA

## Services Covered

All three services follow this pattern:
- **API** (`engrammic-api`) - main service
- **Beacon** (`engrammic-beacon`) - telemetry
- **Dagster** (`engrammic-dagster`) - pipeline orchestration

## Architecture

```
Push to main  ──►  Build images  ──►  Deploy beta  ──►  (manual) Promote to prod
                   Tag :latest + :sha    + migrate           + migrate
```

### Separation of Concerns

| Component | Pulumi | GitHub Actions |
|-----------|--------|----------------|
| VPC, Cloud SQL, service accounts | ✓ | |
| Cloud Run service definition | ✓ | |
| Cloud Run image tag | ignore | ✓ |
| Feature flag env vars | ✓ | |
| Building images | | ✓ |
| Deploying images | | ✓ |
| Running migrations | | ✓ |

### Key Principle

Pulumi creates and configures the Cloud Run service but does NOT manage the image tag. This prevents drift - Pulumi won't try to "fix" the image back to an old version.

## Image Tagging Strategy

Every build produces two tags:
- `:latest` - always points to most recent build
- `:<short-sha>` - immutable reference for rollback

Artifact Registry lifecycle policy: delete images older than 30 days, except `:latest`.

Rollback: `gcloud run services update-traffic --to-revisions=<revision>=100`

## Feature Flags

Pulumi manages environment-specific feature flags as env vars:

```python
feature_flags = {
    "beta": {
        "ENABLE_EXPERIMENTAL_RECALL": "true",
        "ENABLE_DEBUG_ENDPOINTS": "true",
    },
    "prod": {
        "ENABLE_EXPERIMENTAL_RECALL": "false",
        "ENABLE_DEBUG_ENDPOINTS": "false",
    },
}
```

Same image runs in both environments. Behavior differs based on env vars.

Code pattern:
```python
if settings.enable_experimental_recall:
    # beta-only behavior
```

## Migrations

Unified Cloud Run Job approach for both environments:

- Job naming: `engrammic-{env}-migrate` (e.g., `engrammic-beta-migrate`)
- Triggered by CI after image deploy, before traffic routing
- Uses Cloud SQL Auth Proxy sidecar
- Same job definition, different env vars per environment

## GitHub Actions Workflows

### deploy-beta.yml

**Change:** Trigger on `main` branch (currently triggers on `beta` branch).

```yaml
on:
  push:
    branches: [main]  # CHANGE from [beta]
  workflow_dispatch:

steps:
  - Build API, Beacon, Dagster images with Cloud Build
    - Tag :latest and :$SHORT_SHA
  - Deploy all three to Cloud Run (--no-traffic)
  - Execute migration job engrammic-beta-migrate (--wait)
  - Route traffic to latest revisions
```

### deploy-prod.yml

**Change:** Remove image builds. Add SHA input. Promote existing image.

```yaml
on:
  workflow_dispatch:
    inputs:
      sha:
        description: 'SHA to promote (7 chars, must exist in registry)'
        required: true
        type: string
      confirm_deploy:
        description: 'Type "deploy" to confirm'
        required: true
        type: string

steps:
  - Verify image exists: gcloud artifacts docker images describe .../engrammic-api:$SHA
  - Deploy engrammic-prod-api --image=...:$SHA (--no-traffic)
  - Deploy engrammic-prod-beacon --image=...:$SHA (--no-traffic)
  - Deploy engrammic-prod-dagster --image=...:$SHA (--no-traffic)
  - Execute migration job engrammic-prod-migrate (--wait)
  - Route traffic to latest revisions
```

### Migration Job Naming Fix

Current inconsistency:
- `deploy-beta.yml` line 59: `engrammic-migrate-beta` (wrong)
- `justfile` line 176: `engrammic-beta-migrate` (correct)

Fix: Update `deploy-beta.yml` to use `engrammic-beta-migrate`.

## Pulumi Changes

### Ignore image tag

Use broad `template` ignore since array index syntax is fragile:

```python
cloud_run_service = gcp.cloudrunv2.Service(
    "api-service",
    ...,
    opts=pulumi.ResourceOptions(
        ignore_changes=["template"],  # CI owns template.containers[*].image
    ),
)
```

Alternative: Keep Pulumi managing template but set a placeholder image on create, then let CI update it. The `ignore_changes` approach is cleaner.

### Feature flags as env vars

```python
def get_feature_flags(env: str) -> list[dict]:
    flags = {
        "beta": {"ENABLE_EXPERIMENTAL_RECALL": "true"},
        "prod": {"ENABLE_EXPERIMENTAL_RECALL": "false"},
    }
    return [{"name": k, "value": v} for k, v in flags.get(env, {}).items()]
```

### Artifact Registry Lifecycle Policy

Add to Pulumi (or configure via console):

```python
gcp.artifactregistry.Repository(
    "engrammic-repo",
    cleanup_policies=[{
        "id": "delete-old-images",
        "action": "DELETE",
        "condition": {
            "older_than": "2592000s",  # 30 days
            "tag_state": "UNTAGGED",
        },
    }],
)
```

Note: `:latest` tag protects the most recent image from deletion.

## Justfile Commands

Replace existing `deploy-api-beta`, `deploy-api-prod`, `ship-beta` with:

```just
# Build all images (tags :latest + :SHORT_SHA)
build sha="latest":
    gcloud builds submit --config=cloudbuild.api.yaml --substitutions=SHORT_SHA={{sha}}
    gcloud builds submit --config=cloudbuild.beacon.yaml --substitutions=SHORT_SHA={{sha}}
    gcloud builds submit --config=cloudbuild.dagster.yaml --substitutions=SHORT_SHA={{sha}}

# Deploy specific SHA to beta (all services)
deploy-beta sha="latest":
    gcloud run services update engrammic-beta-api --image={{registry}}/engrammic-api:{{sha}} --region={{region}}
    gcloud run services update engrammic-beta-beacon --image={{registry}}/engrammic-beacon:{{sha}} --region={{region}}
    gcloud run jobs execute engrammic-beta-migrate --region={{region}} --wait

# Promote SHA to prod (all services)
deploy-prod sha:
    gcloud run services update engrammic-prod-api --image={{registry}}/engrammic-api:{{sha}} --region={{region}}
    gcloud run services update engrammic-prod-beacon --image={{registry}}/engrammic-beacon:{{sha}} --region={{region}}
    gcloud run jobs execute engrammic-prod-migrate --region={{region}} --wait

# Build + deploy to beta (convenience)
ship-beta sha="latest":
    just build {{sha}}
    just deploy-beta {{sha}}
```

Commands removed: `build-api`, `build-beacon`, `build-dagster`, `deploy-api-beta`, `deploy-api-prod`.

## Rollback Procedure

1. Identify good SHA: `gcloud artifacts docker images list ... --include-tags`
2. Deploy: `just deploy-beta abc123f` or `just deploy-prod abc123f`
3. Migrations are forward-only; if schema rollback needed, that's a new migration

## Success Criteria

- [ ] Push to main auto-deploys to beta within 5 minutes
- [ ] Prod promotion uses same image (no rebuild)
- [ ] `pulumi up` doesn't touch image tags
- [ ] Rollback to previous SHA works in under 2 minutes
- [ ] Migration job names consistent (`engrammic-{env}-migrate`)
- [ ] Feature flags toggle behavior without rebuild
