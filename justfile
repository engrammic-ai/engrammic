# context-service - Development Commands

# Variables
dc := "docker compose"

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
    uv run pytest -m integration -v

# Run tests with coverage report
coverage:
    uv run pytest --cov=context_service --cov-report=html --cov-report=term-missing

# --- Dagster ---

# Start Dagster webserver (local)
dagster-web:
    uv run dagster-webserver -h 0.0.0.0 -p 3000 -m context_service.pipelines

# Start Dagster daemon (local)
dagster-daemon:
    uv run dagster-daemon run -m context_service.pipelines

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
