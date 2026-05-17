# Stage 1: Build dependencies
FROM python:3.13-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files (uv.lock not needed - we re-resolve for PyPI primitives)
COPY context-service/pyproject.toml context-service/README.md ./

# Remove local path source override - install primitives from PyPI
RUN sed -i '/engrammic-primitives.*path/d' pyproject.toml

# Install production dependencies (re-resolves to fetch primitives from PyPI)
RUN uv sync --no-dev --no-install-project

# Stage 2: Runtime
FROM python:3.13-slim

WORKDIR /app

# Create non-root user with predictable UID for volume mounts
RUN groupadd -g 1000 engrammic && useradd -u 1000 -g engrammic -m engrammic \
    && mkdir -p /var/lib/engrammic \
    && chown engrammic:engrammic /var/lib/engrammic

# Copy virtual environment from builder (primitives installed from PyPI)
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY context-service/pyproject.toml context-service/uv.lock context-service/README.md ./
COPY context-service/config/ /app/config/
COPY context-service/src/ /app/src/
COPY context-service/alembic.ini /app/alembic.ini
COPY context-service/alembic/ /app/alembic/
COPY context-service/scripts/entrypoint.sh /entrypoint.sh

# Set environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER engrammic

EXPOSE 8000

# Health check (uses PORT env var, defaults to 8000 for local docker)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"8000\")}/health')"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "-c", "exec python -m uvicorn context_service.api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
