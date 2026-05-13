# context-service - Development Commands

# Variables
dc := "docker compose -f docker-compose.dev.yml"

# Import infra recipes
import 'infra/just.infra'

# List available recipes
default:
    @just --list

# --- Setup ---

# Lock dependencies
lock:
    uv lock

# Sync dependencies
sync:
    uv sync

# Install production dependencies
install:
    uv sync --no-dev

# Install development dependencies
install-dev:
    uv sync --all-extras

# --- Code Quality ---

# Run ruff linter
lint:
    uv run ruff check src tests

# Format code with ruff
format:
    uv run ruff format src tests
    uv run ruff check --fix src tests

# Check formatting without modifying
format-check:
    uv run ruff format --check src tests

# Run mypy type checker
typecheck:
    uv run mypy src

# Run all checks (lint + typecheck)
check: lint typecheck

# --- Testing ---

# Run all tests
test:
    uv run pytest

# Run integration tests (requires live docker stack)
test-integration:
    env $(cat .env.test | grep -v '^#' | xargs) uv run pytest -m integration -v

# Run tests with coverage report
coverage:
    uv run pytest --cov=context_service --cov-report=html --cov-report=term-missing

# --- Dagster ---

# Start Dagster webserver (local)
dagster-web:
    uv run dagster-webserver -h 0.0.0.0 -p 3000 -m context_service.pipelines.definitions

# Start Dagster daemon (local)
dagster-daemon:
    uv run dagster-daemon run -m context_service.pipelines.definitions

# Trigger heat asset recompute for all silos (backfill after enabling unified_decay)
heat-recompute:
    uv run dagster asset materialize -m context_service.pipelines.definitions --select heat

# --- Running ---

# Run FastAPI server (production)
run:
    uv run python -m context_service

# Run FastAPI server (development with reload)
dev:
    RELOAD=true uv run python -m context_service

# --- Docker ---

# Start app + infrastructure services
docker-up:
    {{dc}} up -d --build

# Stop app + infrastructure services
docker-down:
    {{dc}} down

# View service logs
docker-logs:
    {{dc}} logs -f

# Stop and remove volumes
docker-clean:
    {{dc}} down -v

# Check service status
docker-ps:
    {{dc}} ps

# --- Production Docker ---

# Start production services
docker-prod-up:
    {{dc}} -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Stop production services
docker-prod-down:
    {{dc}} -f docker-compose.yml -f docker-compose.prod.yml down

# View production service logs
docker-prod-logs:
    {{dc}} -f docker-compose.yml -f docker-compose.prod.yml logs -f

# --- Dagger CI ---

# Run lint via dagger
dagger-lint:
    dagger call lint --source=. --primitives=../primitives

# Run typecheck via dagger
dagger-typecheck:
    dagger call typecheck --source=. --primitives=../primitives

# Run unit tests via dagger
dagger-test:
    dagger call test --source=. --primitives=../primitives

# Run integration tests via dagger (spins up services)
dagger-test-integration:
    dagger call test-integration --source=. --primitives=../primitives

# Run lint + typecheck via dagger
dagger-check:
    dagger call check --source=. --primitives=../primitives

# Run full pipeline via dagger
dagger-all:
    dagger call all --source=. --primitives=../primitives

# --- Release ---

# Preview next release (dry run)
release-preview:
    npx release-please release-pr --dry-run --repo-url=. --token=fake

# Create release PR locally (inspect CHANGELOG before committing)
release-pr:
    npx release-please release-pr --repo-url=. --token=fake

# Tag release after PR merge
release-tag:
    npx release-please github-release --repo-url=. --token=fake

# --- Quality evals ---

# Run HIL quality evals
evals:
    uv run python scripts/run_evals.py

# Run evals with LLM agent mode
evals-llm:
    uv run python scripts/run_evals.py --with-llm

# Run evals with verbose output
evals-verbose:
    uv run python scripts/run_evals.py -v

# Run a single eval scenario by keyword (e.g. just evals-scenario recall)
evals-scenario scenario:
    uv run python scripts/run_evals.py --scenario {{scenario}} -v

# Run evals and write results to evals-output.json
evals-output:
    uv run python scripts/run_evals.py --output evals-output.json -v

# --- Observability (SigNoz) ---

# Start SigNoz observability stack
signoz-up:
    docker compose -f docker-compose.signoz.yml up -d

# Stop SigNoz stack
signoz-down:
    docker compose -f docker-compose.signoz.yml down

# View SigNoz logs
signoz-logs:
    docker compose -f docker-compose.signoz.yml logs -f

# Restart OTEL collector (after config changes)
otel-restart:
    docker restart context-service-otel

# --- Cleanup ---

# Remove cache and build artifacts
clean:
    #!/usr/bin/env bash
    set -euo pipefail
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    rm -rf htmlcov .coverage coverage.xml 2>/dev/null || true
