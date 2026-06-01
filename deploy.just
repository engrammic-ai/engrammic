# Deploy commands
# Imported by main justfile

# =============================================================================
# Build & Deploy
# =============================================================================

# Build all images (tags :latest + :SHORT_SHA)
[group('deploy')]
build sha="latest":
    gcloud builds submit --config=deploy/cloudbuild/api.yaml \
        --substitutions=SHORT_SHA={{sha}} --region={{region}} .
    gcloud builds submit --config=deploy/cloudbuild/beacon.yaml \
        --substitutions=SHORT_SHA={{sha}} --region={{region}} .
    gcloud builds submit --config=deploy/cloudbuild/dagster.yaml \
        --substitutions=SHORT_SHA={{sha}} --region={{region}} .

# Build partners image (bytecode-only distribution)
[group('deploy')]
build-partners sha="latest":
    gcloud builds submit --config=deploy/cloudbuild/partners.yaml \
        --substitutions=SHORT_SHA={{sha}} --project={{project}} .

# Deploy specific SHA to beta
[group('deploy')]
deploy-beta sha="latest":
    gcloud run services update engrammic-beta-api \
        --image={{registry}}/engrammic-api:{{sha}} --region={{region}} --project={{project}}
    gcloud run services update engrammic-beta-beacon \
        --image={{registry}}/engrammic-beacon:{{sha}} --region={{region}} --project={{project}}
    gcloud run jobs execute engrammic-beta-migrate --region={{region}} --project={{project}} --wait

# Promote SHA to prod
[group('deploy')]
deploy-prod sha:
    gcloud run services update engrammic-prod-api \
        --image={{registry}}/engrammic-api:{{sha}} --region={{region}} --project={{project}}
    gcloud run services update engrammic-prod-beacon \
        --image={{registry}}/engrammic-beacon:{{sha}} --region={{region}} --project={{project}}
    gcloud run jobs execute engrammic-prod-migrate --region={{region}} --project={{project}} --wait

# Build + deploy to beta (convenience)
[group('deploy')]
ship-beta sha="latest":
    just build {{sha}}
    just deploy-beta {{sha}}

# =============================================================================
# Remote Migrations
# =============================================================================

# Run migrations via Cloud Run job
[group('deploy')]
migrate env="beta":
    gcloud run jobs execute engrammic-{{env}}-migrate \
        --region={{region}} --project={{project}} --wait

# Run migrations via StatefulHost (fallback if job doesn't exist)
[group('deploy')]
migrate-ssh env="beta":
    ./scripts/deploy/migrate-ssh.sh {{env}}

# =============================================================================
# Self-Hosted Distribution
# =============================================================================

releases_registry := "europe-north1-docker.pkg.dev/engrammic/releases"

# Build and push self-hosted images via Cloud Build
[group('deploy')]
dist version="0.1.0":
    ./scripts/deploy/dist.sh {{version}}

# Build locally (for testing, no push)
[group('deploy')]
dist-local version="0.1.0":
    docker build -f docker/Dockerfile.selfhosted.api \
        -t {{releases_registry}}/engrammic-api:v{{version}} .
    docker build -f docker/Dockerfile.selfhosted.beacon \
        -t {{releases_registry}}/engrammic-beacon:v{{version}} .
    @echo "Built locally. To push: docker push {{releases_registry}}/engrammic-api:v{{version}}"

# Verify public pull works (no auth)
[group('deploy')]
dist-verify version="0.1.0":
    ./scripts/deploy/dist-verify.sh {{version}}

# =============================================================================
# Infrastructure
# =============================================================================

# Pulumi preview (current stack)
[group('deploy')]
infra-preview:
    cd infra && pulumi preview

# Pulumi deploy (current stack)
[group('deploy')]
infra-up:
    cd infra && pulumi up

# Pulumi deploy to specific stack
[group('deploy')]
infra-up-stack stack:
    cd infra && pulumi up --stack {{stack}}

# Pulumi refresh
[group('deploy')]
infra-refresh:
    cd infra && pulumi refresh
