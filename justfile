# context-service - Development Commands

dc := "docker compose -f docker-compose.dev.yml"

default:
    @just --list

# --- Daily Workflow ---

# Install dev dependencies
install-dev:
    uv sync --all-extras

# Run all checks (lint + typecheck)
check:
    uv run ruff check src tests
    uv run mypy src

# Format code
format:
    uv run ruff format src tests
    uv run ruff check --fix src tests

# Run tests
test *args:
    uv run pytest {{args}}

# Run dev server with reload
dev:
    RELOAD=true uv run python -m context_service

# --- Docker ---

# Start dev services
docker-up:
    {{dc}} up -d --build

# Stop dev services
docker-down:
    {{dc}} down

# View logs
docker-logs *args:
    {{dc}} logs -f {{args}}

# Stop and remove volumes
docker-clean:
    {{dc}} down -v

# --- Database ---

# Run migrations
db-migrate:
    uv run alembic upgrade head

# Generate new migration
db-revision message:
    uv run alembic revision --autogenerate -m "{{message}}"

# --- Dagster ---

# Start Dagster webserver
dagster-web:
    uv run dagster-webserver -h 0.0.0.0 -p 3000 -m context_service.pipelines.definitions

# Start Dagster daemon
dagster-daemon:
    uv run dagster-daemon run -m context_service.pipelines.definitions

# --- Observability ---

# Start SigNoz stack
signoz-up:
    docker compose -f docker-compose.signoz.yml up -d

# Stop SigNoz stack
signoz-down:
    docker compose -f docker-compose.signoz.yml down

# --- Cleanup ---

# Remove cache artifacts
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
    rm -rf htmlcov .coverage 2>/dev/null || true

# --- GCP Infrastructure ---

instance := "engrammic-dev-stateful"
zone := "europe-north1-a"
region := "europe-north1"
project := "engrammic"
registry := "europe-north1-docker.pkg.dev/engrammic/engrammic"

# SSH into stateful host
ssh:
    gcloud compute ssh {{instance}} --zone={{zone}} --tunnel-through-iap

# Tunnel all services to localhost
tunnel:
    gcloud compute ssh {{instance}} --zone={{zone}} --tunnel-through-iap -- -NL 7687:localhost:7687 -L 6333:localhost:6333 -L 6334:localhost:6334 -L 6379:localhost:6379 -L 5432:localhost:5432 -L 3000:localhost:3000

# Check instance status
status:
    gcloud compute instances describe {{instance}} --zone={{zone}} --format="table(name,status,networkInterfaces[0].networkIP)"

# Check docker on instance
docker-status:
    gcloud compute ssh {{instance}} --zone={{zone}} --tunnel-through-iap --command="docker ps --format 'table {{{{.Names}}}}\t{{{{.Status}}}}'"

# Pulumi preview
infra-preview:
    cd infra && pulumi preview

# Pulumi deploy
infra-up:
    cd infra && pulumi up

# Start instance
infra-start:
    gcloud compute instances start {{instance}} --zone={{zone}}

# Stop instance (saves cost)
infra-stop:
    gcloud compute instances stop {{instance}} --zone={{zone}}

# Build and push API image
build tag="latest":
    gcloud builds submit --config=cloudbuild.api.yaml --substitutions=_IMAGE={{registry}}/engrammic-api:{{tag}} --region={{region}} .

# Build and push beacon image
build-beacon tag="latest":
    gcloud builds submit --config=cloudbuild.beacon.yaml --substitutions=_IMAGE={{registry}}/engrammic-beacon:{{tag}} --region={{region}} .

# Build and push dagster image
build-dagster tag="latest":
    gcloud builds submit --config=cloudbuild.dagster.yaml --substitutions=_IMAGE={{registry}}/engrammic-dagster,SHORT_SHA={{tag}} --region={{region}} .

# Build all images
build-all tag="latest":
    just build {{tag}}
    just build-beacon {{tag}}
    just build-dagster {{tag}}

# Sync secrets to GCP Secret Manager (dev)
secrets-sync:
    ENVIRONMENT=dev GCP_PROJECT={{project}} uv run python scripts/sync_secrets.py

# Sync secrets to GCP Secret Manager (beta)
secrets-sync-beta:
    ENVIRONMENT=beta GCP_PROJECT={{project}} uv run python scripts/sync_secrets.py

# Run migrations on beta Cloud SQL (via API container on stateful host)
db-migrate-beta:
    gcloud compute ssh engrammic-beta-stateful --project={{project}} --zone={{zone}} --tunnel-through-iap --command='export PGPASSWORD=$$(gcloud secrets versions access latest --secret=engrammic-beta-postgres-password --project={{project}}) && docker run --rm -e POSTGRES_HOST=10.162.0.3 -e POSTGRES_PORT=5432 -e POSTGRES_USER=context -e POSTGRES_PASSWORD="$$PGPASSWORD" -e POSTGRES_DATABASE=engrammic {{registry}}/engrammic-api:latest alembic upgrade head'

# Check beta database tables
db-tables-beta:
    gcloud compute ssh engrammic-beta-stateful --project={{project}} --zone={{zone}} --tunnel-through-iap --command='export PGPASSWORD=$$(gcloud secrets versions access latest --secret=engrammic-beta-postgres-password --project={{project}}) && docker run --rm -e PGPASSWORD="$$PGPASSWORD" postgres:16-alpine psql "postgresql://context@10.162.0.3:5432/engrammic" -c "\dt"'

# Check alembic version on beta
db-version-beta:
    gcloud compute ssh engrammic-beta-stateful --project={{project}} --zone={{zone}} --tunnel-through-iap --command='export PGPASSWORD=$$(gcloud secrets versions access latest --secret=engrammic-beta-postgres-password --project={{project}}) && docker run --rm -e PGPASSWORD="$$PGPASSWORD" postgres:16-alpine psql "postgresql://context@10.162.0.3:5432/engrammic" -c "SELECT * FROM alembic_version;"'

# Interactive psql on beta (via stateful host)
db-psql-beta:
    gcloud compute ssh engrammic-beta-stateful --project={{project}} --zone={{zone}} --tunnel-through-iap --command='export PGPASSWORD=$$(gcloud secrets versions access latest --secret=engrammic-beta-postgres-password --project={{project}}) && docker run -it --rm -e PGPASSWORD="$$PGPASSWORD" postgres:16-alpine psql "postgresql://context@10.162.0.3:5432/engrammic"'

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
