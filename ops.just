# Operations commands
# Imported by main justfile

# =============================================================================
# Dev Box
# =============================================================================

# Manage the dev box: ssh (default) | iap | start | stop | status
[group('ops')]
dev-box action="ssh":
    ./scripts/ops/dev-box.sh {{action}}

# =============================================================================
# StatefulHost Management
# =============================================================================

# SSH into stateful host
[group('ops')]
ssh env="beta":
    gcloud compute ssh engrammic-{{env}}-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap

# Check docker containers on stateful host
[group('ops')]
status env="beta":
    gcloud compute ssh engrammic-{{env}}-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap \
        --command="docker ps --format 'table {{{{.Names}}}}\t{{{{.Status}}}}'"

# Tunnel services to localhost (Memgraph 7687, Qdrant, Redis, Dagster 3000, Postgres). Memgraph binds 0.0.0.0 so the memgraph-lab container can reach it.
[group('ops')]
tunnel env="beta":
    gcloud compute ssh engrammic-{{env}}-stateful --zone={{zone}} --project={{project}} --tunnel-through-iap \
        -- -N -L 0.0.0.0:7687:localhost:7687 -L 6333:localhost:6333 -L 6334:localhost:6334 -L 6379:localhost:6379 -L 3000:localhost:3000 -L 5432:10.162.0.3:5432

# Start stateful instance
[group('ops')]
start env="beta":
    gcloud compute instances start engrammic-{{env}}-stateful --zone={{zone}} --project={{project}}

# Stop stateful instance (saves cost)
[group('ops')]
stop env="beta":
    gcloud compute instances stop engrammic-{{env}}-stateful --zone={{zone}} --project={{project}}

# Run Memgraph Lab UI locally against beta. Run `just tunnel beta` concurrently first. UI: http://localhost:3002
[group('ops')]
memgraph-lab:
    docker run --rm -p 3002:3000 \
        --add-host=host.docker.internal:host-gateway \
        -e QUICK_CONNECT_MG_HOST=host.docker.internal -e QUICK_CONNECT_MG_PORT=7687 \
        memgraph/lab

# =============================================================================
# Observability
# =============================================================================

# Open IAP tunnel to SigNoz UI
[group('ops')]
signoz-tunnel:
    gcloud compute start-iap-tunnel engrammic-beta-signoz 3301 --local-host-port=localhost:3301 --zone=europe-north1-b

# =============================================================================
# Database (Remote)
# =============================================================================

# Interactive psql
[group('ops')]
psql env="beta":
    ./scripts/ops/psql.sh {{env}}

# Check migration status
[group('ops')]
migrate-status env="beta":
    ./scripts/ops/migrate-status.sh {{env}}

# =============================================================================
# Secrets Management
# =============================================================================

# Push local .env.{env} to GCP Secret Manager
[group('ops')]
secrets-push env="beta":
    ./scripts/ops/secrets-push.sh {{env}}

# Pull GCP secrets to local .env.{env}
[group('ops')]
secrets-pull env="beta":
    ./scripts/ops/secrets-pull.sh {{env}}

# =============================================================================
# Logs
# =============================================================================

# View Cloud Run logs
[group('ops')]
logs-api env="beta":
    gcloud run services logs read engrammic-{{env}}-api --region={{region}} --project={{project}} --limit=50

# Tail Cloud Run logs
[group('ops')]
logs-api-tail env="beta":
    gcloud alpha run services logs tail engrammic-{{env}}-api --region={{region}} --project={{project}}
