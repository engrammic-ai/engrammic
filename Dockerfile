# Stage 1: Build dependencies
FROM python:3.13-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy primitives (local dependency)
COPY primitives/ /primitives/

# Copy dependency files
COPY context-service/pyproject.toml context-service/uv.lock context-service/README.md ./

# Install production dependencies only
RUN uv sync --frozen --no-dev --no-install-project

# Stage 2: Runtime
FROM python:3.13-slim

WORKDIR /app

# Create non-root user
RUN groupadd -r context-service && useradd -r -g context-service context-service \
    && mkdir -p /var/lib/engrammic \
    && chown context-service:context-service /var/lib/engrammic

# Copy virtual environment and primitives from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /primitives /primitives

# Copy application code
COPY context-service/pyproject.toml context-service/uv.lock context-service/README.md ./
COPY context-service/config/ /app/config/
COPY context-service/src/ /app/src/
COPY context-service/alembic.ini /app/alembic.ini
COPY context-service/alembic/ /app/alembic/
# Set environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER context-service

EXPOSE 8000

# Health check (uses PORT env var, defaults to 8000 for local docker)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"8000\")}/health')"

CMD ["sh", "-c", "exec python -m uvicorn context_service.api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
