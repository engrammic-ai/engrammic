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

# Install uv for runtime commands (dagster, etc.)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root user and writable directories
RUN groupadd -r context-service && useradd -r -g context-service context-service \
    && mkdir -p /var/lib/engrammic /home/context-service/.cache/uv /app/history \
    && chown -R context-service:context-service /var/lib/engrammic /home/context-service /app/history

# Copy virtual environment from builder (chown for uv to modify)
COPY --from=builder --chown=context-service:context-service /app/.venv /app/.venv

# Copy primitives (needed at runtime for imports)
COPY --from=builder --chown=context-service:context-service /primitives /primitives

# Copy application code
COPY context-service/pyproject.toml context-service/uv.lock context-service/README.md ./
COPY context-service/config/ /app/config/
COPY context-service/src/ /app/src/
COPY context-service/alembic.ini /app/alembic.ini
COPY context-service/alembic/ /app/alembic/
COPY context-service/docker/app-entrypoint.sh /app/entrypoint.sh

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Set environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER context-service

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "context_service.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
