# context-service - Development Commands
# Run `just` to see all available commands

# =============================================================================
# Configuration
# =============================================================================

dc := "docker compose -f docker-compose.dev.yml"
project := "engrammic"
region := "europe-north1"
zone := "europe-north1-a"
registry := "europe-north1-docker.pkg.dev/engrammic/engrammic"

default:
    @just --list --unsorted

# =============================================================================
# Development
# =============================================================================

# Install dev dependencies
install:
    uv sync --all-extras

# Run all checks (lint + typecheck)
check:
    uv run ruff check src tests
    uv run mypy src

# Format code
fmt:
    uv run ruff format src tests
    uv run ruff check --fix src tests

# Run tests (pass args like: just test -k test_name)
test *args:
    uv run pytest {{args}}

# Run dev server with reload
dev:
    RELOAD=true uv run python -m context_service

# Remove cache artifacts
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
    rm -rf htmlcov .coverage 2>/dev/null || true

# =============================================================================
# Local Docker Stack
# =============================================================================

# Start local dev services (Memgraph, Qdrant, Redis)
up:
    {{dc}} up -d --build

# Stop local dev services
down:
    {{dc}} down

# View local service logs
logs *args:
    {{dc}} logs -f {{args}}

# Stop and remove volumes (full reset)
reset:
    {{dc}} down -v

# =============================================================================
# Database (Local)
# =============================================================================

# Run local migrations
db-migrate:
    uv run alembic upgrade head

# Generate new migration
db-revision message:
    uv run alembic revision --autogenerate -m "{{message}}"

# Show current migration version
db-version:
    uv run alembic current

# =============================================================================
# Dagster (Local)
# =============================================================================

# Start Dagster webserver
dagster-web:
    uv run dagster-webserver -h 0.0.0.0 -p 3000 -m context_service.pipelines.definitions

# Start Dagster daemon
dagster-daemon:
    uv run dagster-daemon run -m context_service.pipelines.definitions

# =============================================================================
# Observability
# =============================================================================

# Start SigNoz stack
signoz-up:
    docker compose -f docker-compose.signoz.yml up -d

# Stop SigNoz stack
signoz-down:
    docker compose -f docker-compose.signoz.yml down

# =============================================================================
# GCP Infrastructure
# =============================================================================

# Pulumi preview
infra-preview:
    cd infra && pulumi preview

# Pulumi deploy
infra-up:
    cd infra && pulumi up

# Pulumi refresh
infra-refresh:
    cd infra && pulumi refresh

# =============================================================================
# Build & Deploy
# =============================================================================

# Build and push API image
build-api tag="latest":
    gcloud builds submit --config=cloudbuild.api.yaml \
        --substitutions=_IMAGE={{registry}}/engrammic-api,SHORT_SHA={{tag}} \
        --region={{region}} .

# Build and push Dagster image
build-dagster tag="latest":
    gcloud builds submit --config=cloudbuild.dagster.yaml \
        --substitutions=_IMAGE={{registry}}/engrammic-dagster,SHORT_SHA={{tag}} \
        --region={{region}} .

# Build and push Beacon image
build-beacon tag="latest":
    gcloud builds submit --config=cloudbuild.beacon.yaml \
        --substitutions=_IMAGE={{registry}}/engrammic-beacon,SHORT_SHA={{tag}} \
        --region={{region}} .

# Build all images
build-all tag="latest":
    just build-api {{tag}}
    just build-dagster {{tag}}
    just build-beacon {{tag}}

# Deploy API to Cloud Run (beta)
deploy-api-beta:
    gcloud run services update engrammic-beta-api \
        --image={{registry}}/engrammic-api:latest \
        --region={{region}} --project={{project}}

# Deploy API to Cloud Run (prod)
deploy-api-prod:
    gcloud run services update engrammic-prod-api \
        --image={{registry}}/engrammic-api:latest \
        --region={{region}} --project={{project}}

# Build and deploy API (beta)
ship-beta: (build-api "latest") deploy-api-beta migrate-beta
    @echo "Shipped to beta"

# =============================================================================
# Database (Remote)
# =============================================================================

# Run migrations via Cloud Run job (beta)
migrate-beta:
    gcloud run jobs execute engrammic-beta-migrate \
        --region={{region}} --project={{project}} --wait

# Run migrations via Cloud Run job (prod)
migrate-prod:
    gcloud run jobs execute engrammic-prod-migrate \
        --region={{region}} --project={{project}} --wait

# Run migrations via StatefulHost (fallback if job doesn't exist)
migrate-beta-ssh:
    #!/usr/bin/env bash
    set -euo pipefail
    PGPASSWORD=$(gcloud secrets versions access latest --secret=engrammic-beta-postgres-password --project={{project}})
    CLOUDSQL_IP=$(gcloud sql instances describe engrammic-beta --project={{project}} --format='value(ipAddresses[0].ipAddress)')
    gcloud compute ssh engrammic-beta-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap \
        --command="docker run --rm postgres:16-alpine psql 'postgresql://context:${PGPASSWORD}@${CLOUDSQL_IP}/engrammic' -c 'SELECT version();'"
    echo "Connection OK. Running migrations..."
    gcloud compute ssh engrammic-beta-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap \
        --command="docker run --rm -e DATABASE_URL='postgresql+asyncpg://context:${PGPASSWORD}@${CLOUDSQL_IP}/engrammic' {{registry}}/engrammic-api:latest alembic upgrade head"

# Check migration status (beta)
migrate-status-beta:
    #!/usr/bin/env bash
    set -euo pipefail
    PGPASSWORD=$(gcloud secrets versions access latest --secret=engrammic-beta-postgres-password --project={{project}})
    CLOUDSQL_IP=$(gcloud sql instances describe engrammic-beta --project={{project}} --format='value(ipAddresses[0].ipAddress)')
    gcloud compute ssh engrammic-beta-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap \
        --command="docker run --rm -e PGPASSWORD='${PGPASSWORD}' postgres:16-alpine psql 'postgresql://context@${CLOUDSQL_IP}/engrammic' -c 'SELECT * FROM alembic_version;'"

# Interactive psql (beta)
psql-beta:
    #!/usr/bin/env bash
    set -euo pipefail
    PGPASSWORD=$(gcloud secrets versions access latest --secret=engrammic-beta-postgres-password --project={{project}})
    CLOUDSQL_IP=$(gcloud sql instances describe engrammic-beta --project={{project}} --format='value(ipAddresses[0].ipAddress)')
    gcloud compute ssh engrammic-beta-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap \
        --command="docker run -it --rm -e PGPASSWORD='${PGPASSWORD}' postgres:16-alpine psql 'postgresql://context@${CLOUDSQL_IP}/engrammic'"

# =============================================================================
# StatefulHost Management
# =============================================================================

# SSH into stateful host (beta)
ssh-beta:
    gcloud compute ssh engrammic-beta-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap

# SSH into stateful host (dev)
ssh-dev:
    gcloud compute ssh engrammic-dev-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap

# Check docker containers on stateful host (beta)
status-beta:
    gcloud compute ssh engrammic-beta-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap \
        --command="docker ps --format 'table {{{{.Names}}}}\t{{{{.Status}}}}'"

# Check docker containers on stateful host (dev)
status-dev:
    gcloud compute ssh engrammic-dev-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap \
        --command="docker ps --format 'table {{{{.Names}}}}\t{{{{.Status}}}}'"

# Tunnel services to localhost (beta)
tunnel-beta:
    gcloud compute ssh engrammic-beta-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap \
        -- -NL 7687:localhost:7687 -L 6333:localhost:6333 -L 6334:localhost:6334 -L 6379:localhost:6379 -L 3000:localhost:3000

# Tunnel services to localhost (dev)
tunnel-dev:
    gcloud compute ssh engrammic-dev-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap \
        -- -NL 7687:localhost:7687 -L 6333:localhost:6333 -L 6334:localhost:6334 -L 6379:localhost:6379 -L 3000:localhost:3000

# Start instance (beta)
start-beta:
    gcloud compute instances start engrammic-beta-stateful --zone={{zone}} --project={{project}}

# Stop instance (beta) - saves cost
stop-beta:
    gcloud compute instances stop engrammic-beta-stateful --zone={{zone}} --project={{project}}

# Start instance (dev)
start-dev:
    gcloud compute instances start engrammic-dev-stateful --zone={{zone}} --project={{project}}

# Stop instance (dev) - saves cost
stop-dev:
    gcloud compute instances stop engrammic-dev-stateful --zone={{zone}} --project={{project}}

# =============================================================================
# Secrets Management
# =============================================================================

# Push local .env.{env} to GCP Secret Manager
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
        if gcloud secrets describe "$secret_name" --project={{project}} &>/dev/null; then
            echo -n "$value" | gcloud secrets versions add "$secret_name" --project={{project}} --data-file=-
        else
            echo -n "$value" | gcloud secrets create "$secret_name" --project={{project}} --data-file=- --replication-policy=automatic
        fi
    done
    echo "Done."

# Pull GCP secrets to local .env.{env}
secrets-pull env="beta":
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Pulling secrets for {{env}} from GCP Secret Manager..."
    > .env.{{env}}
    for secret in $(gcloud secrets list --project={{project}} --filter="name:engrammic-{{env}}" --format="value(name)"); do
        key=$(basename "$secret" | sed "s/engrammic-{{env}}-//" | tr '-' '_' | tr '[:lower:]' '[:upper:]')
        value=$(gcloud secrets versions access latest --secret="$secret" --project={{project}} 2>/dev/null || echo "")
        if [ -n "$value" ]; then
            echo "$key=$value" >> .env.{{env}}
        fi
    done
    echo "Wrote .env.{{env}}"

# =============================================================================
# Logs
# =============================================================================

# View Cloud Run logs (beta API)
logs-api-beta:
    gcloud run services logs read engrammic-beta-api --region={{region}} --project={{project}} --limit=50

# View Cloud Run logs (prod API)
logs-api-prod:
    gcloud run services logs read engrammic-prod-api --region={{region}} --project={{project}} --limit=50

# Tail Cloud Run logs (beta API)
logs-api-beta-tail:
    gcloud alpha run services logs tail engrammic-beta-api --region={{region}} --project={{project}}
