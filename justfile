# context-service - Development Commands
# Run `just` to see all available commands

# =============================================================================
# Configuration
# =============================================================================

project := "engrammic"
region := "europe-north1"
zone := "europe-north1-a"
registry := "europe-north1-docker.pkg.dev/engrammic/engrammic"
dc := "docker compose --env-file .env -p engrammic -f docker/docker-compose.dev.yml"

default:
    @just --list --unsorted

# Import ops and deploy modules
import 'ops.just'
import 'deploy.just'
import 'standalone.just'

# =============================================================================
# Development
# =============================================================================

# Install dev dependencies
install:
    uv sync --all-extras

# Install only test dependencies (avoids torch download)
test-deps:
    uv sync --group dev --group api --group mcp --group graph --group postgres --group redis --group llm-core --group numeric --group custodian

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

# Generate a license key (usage: just license softlandia 20)
license customer days="90":
    cd ../cli && ENGRAMMIC_KEYS_DIR=keys uv run python -c "from typer.testing import CliRunner; from engrammic_cli.license import license_app; print(CliRunner().invoke(license_app, ['create', '-c', '{{customer}}', '-d', '{{days}}']).output)"

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
    {{dc}} up -d --build --remove-orphans

# Stop local dev services
down:
    {{dc}} down

# View local service logs
logs *args:
    {{dc}} logs -f {{args}}

# Stop and remove volumes (full reset)
reset:
    {{dc}} down -v

# Force recreate all containers (fixes state mismatches)
recreate:
    {{dc}} up -d --force-recreate --remove-orphans

# Nuke everything and start fresh (kills ALL engrammic containers)
nuke:
    docker ps -aq --filter "name=engrammic" | xargs -r docker rm -f
    docker network rm engrammic 2>/dev/null || true
    {{dc}} up -d --build

# =============================================================================
# Image Builds (Skaffold)
# =============================================================================

# Build all images via Skaffold
build-images:
    skaffold build --default-repo={{registry}}

# Build and push base images via Cloud Build (run after uv.lock changes)
build-bases:
    ./scripts/deploy/build-bases.sh

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
