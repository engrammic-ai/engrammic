# Standalone and Podman Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable fully offline Engrammic deployment with local LLM (Ollama) and embeddings (TEI), plus Podman/SELinux support for RHEL/Fedora users.

**Architecture:** Flat compose files (no inheritance) for Docker lite/standard tiers, single Podman file with tier selection via `MODEL_TIER` env var. Ollama serves LLMs, TEI serves embeddings. Models pulled on first run, persisted in volumes.

**Tech Stack:** Docker Compose, Podman, Ollama, Hugging Face TEI, Just

---

## File Structure

| File | Responsibility |
|------|----------------|
| `docker/docker-compose.standalone.yml` | Standard tier compose (32GB+, deepseek-r1:7b, nomic-embed) |
| `docker/docker-compose.standalone-lite.yml` | Lite tier compose (8GB, phi4-mini, MiniLM) |
| `docker/podman-compose.standalone.yml` | Podman with SELinux labels, tier via MODEL_TIER env |
| `docker/standalone.env.example` | Environment template for standard tier |
| `docker/standalone-lite.env.example` | Environment template for lite tier |
| `config/models.yaml` | Add standalone_lite and standalone_standard tiers |
| `standalone.just` | Justfile module with up/down/pull-models commands |
| `justfile` | Import standalone.just |
| `docs/self-hosted/standalone.md` | User documentation |

---

### Task 1: Create Standard Tier Compose File

**Files:**
- Create: `docker/docker-compose.standalone.yml`

- [ ] **Step 1: Create the compose file**

```yaml
# docker/docker-compose.standalone.yml
# Engrammic Standalone - Local LLMs via Ollama (~32GB RAM recommended)
# No cloud API keys required. Models downloaded on first run.

services:
  app:
    image: europe-north1-docker.pkg.dev/engrammic/releases/engrammic-api:latest
    container_name: engrammic-app
    ports:
      - "8000:8000"
    env_file:
      - standalone.env
    environment:
      - ENVIRONMENT=standalone
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
      - POSTGRES_USER=engrammic
      - POSTGRES_DATABASE=engrammic
      - LICENSE_VALIDATION_ENABLED=true
      - EMBEDDING_PROVIDER=tei
      - TEI_URL=http://tei:8080
      - EMBEDDING_DIMENSIONS=768
      - LLM_PROVIDER=ollama
      - OLLAMA_BASE_URL=http://ollama:11434
      - DEFAULT_LLM_MODEL=deepseek-r1:7b
      - MODELS__TIER=standalone_standard
    depends_on:
      memgraph:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      ollama:
        condition: service_healthy
      tei:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 5s
      start_period: 30s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 1G
    restart: unless-stopped

  dagster:
    image: europe-north1-docker.pkg.dev/engrammic/releases/engrammic-dagster:latest
    container_name: engrammic-dagster
    ports:
      - "3000:3000"
    env_file:
      - standalone.env
    environment:
      - ENVIRONMENT=standalone
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
      - POSTGRES_USER=engrammic
      - POSTGRES_DATABASE=engrammic
      - EMBEDDING_PROVIDER=tei
      - TEI_URL=http://tei:8080
      - EMBEDDING_DIMENSIONS=768
      - LLM_PROVIDER=ollama
      - OLLAMA_BASE_URL=http://ollama:11434
      - DEFAULT_LLM_MODEL=deepseek-r1:7b
      - MODELS__TIER=standalone_standard
    depends_on:
      memgraph:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      ollama:
        condition: service_healthy
      tei:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:3000/server_info')"]
      interval: 30s
      timeout: 10s
      start_period: 30s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 1G
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    container_name: engrammic-ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama-models:/root/.ollama
    environment:
      - OLLAMA_MODEL=deepseek-r1:7b
    entrypoint: ["/bin/sh", "-c", "ollama pull deepseek-r1:7b && ollama serve"]
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:11434/api/tags || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 90s
    deploy:
      resources:
        limits:
          memory: 8G
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    restart: unless-stopped

  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
    container_name: engrammic-tei
    ports:
      - "8081:8080"
    command: ["--model-id", "nomic-ai/nomic-embed-text-v1.5"]
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s
    deploy:
      resources:
        limits:
          memory: 2G
    restart: unless-stopped

  memgraph:
    image: memgraph/memgraph-mage:3.10.1
    container_name: engrammic-memgraph
    ports:
      - "7687:7687"
    volumes:
      - memgraph-data:/var/lib/memgraph
    command: ["--log-level=WARNING", "--storage-properties-on-edges=true"]
    healthcheck:
      test: ["CMD-SHELL", "echo 'RETURN 1;' | mgconsole || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 2G
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:v1.18.0
    container_name: engrammic-qdrant
    ports:
      - "6333:6333"
    volumes:
      - qdrant-data:/qdrant/storage
    healthcheck:
      test: ["CMD-SHELL", "bash -c 'echo > /dev/tcp/localhost/6333'"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 1G
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: engrammic-redis
    volumes:
      - redis-data:/data
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "200mb"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 256M
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: engrammic-postgres
    volumes:
      - postgres-data:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=engrammic
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-engrammic}
      - POSTGRES_DB=engrammic
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U engrammic -d engrammic"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 512M
    restart: unless-stopped

volumes:
  ollama-models:
  memgraph-data:
  qdrant-data:
  redis-data:
  postgres-data:
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('docker/docker-compose.standalone.yml'))"`
Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
git add docker/docker-compose.standalone.yml
git commit -m "feat(standalone): add standard tier compose file

Includes Ollama (deepseek-r1:7b) and TEI (nomic-embed) for fully
offline deployment. Targets 32GB+ RAM systems."
```

---

### Task 2: Create Lite Tier Compose File

**Files:**
- Create: `docker/docker-compose.standalone-lite.yml`

- [ ] **Step 1: Create the lite compose file**

```yaml
# docker/docker-compose.standalone-lite.yml
# Engrammic Standalone Lite - Minimal footprint (~8GB RAM minimum, 12GB recommended)
# No cloud API keys required. Models downloaded on first run.

services:
  app:
    image: europe-north1-docker.pkg.dev/engrammic/releases/engrammic-api:latest
    container_name: engrammic-app
    ports:
      - "8000:8000"
    env_file:
      - standalone-lite.env
    environment:
      - ENVIRONMENT=standalone
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
      - POSTGRES_USER=engrammic
      - POSTGRES_DATABASE=engrammic
      - LICENSE_VALIDATION_ENABLED=true
      - EMBEDDING_PROVIDER=tei
      - TEI_URL=http://tei:8080
      - EMBEDDING_DIMENSIONS=384
      - LLM_PROVIDER=ollama
      - OLLAMA_BASE_URL=http://ollama:11434
      - DEFAULT_LLM_MODEL=phi4-mini
      - MODELS__TIER=standalone_lite
    depends_on:
      memgraph:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      ollama:
        condition: service_healthy
      tei:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 5s
      start_period: 30s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 512M
    restart: unless-stopped

  dagster:
    image: europe-north1-docker.pkg.dev/engrammic/releases/engrammic-dagster:latest
    container_name: engrammic-dagster
    ports:
      - "3000:3000"
    env_file:
      - standalone-lite.env
    environment:
      - ENVIRONMENT=standalone
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
      - POSTGRES_USER=engrammic
      - POSTGRES_DATABASE=engrammic
      - EMBEDDING_PROVIDER=tei
      - TEI_URL=http://tei:8080
      - EMBEDDING_DIMENSIONS=384
      - LLM_PROVIDER=ollama
      - OLLAMA_BASE_URL=http://ollama:11434
      - DEFAULT_LLM_MODEL=phi4-mini
      - MODELS__TIER=standalone_lite
    depends_on:
      memgraph:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      ollama:
        condition: service_healthy
      tei:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:3000/server_info')"]
      interval: 30s
      timeout: 10s
      start_period: 30s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 512M
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    container_name: engrammic-ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama-models:/root/.ollama
    environment:
      - OLLAMA_MODEL=phi4-mini
    entrypoint: ["/bin/sh", "-c", "ollama pull phi4-mini && ollama serve"]
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:11434/api/tags || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 90s
    deploy:
      resources:
        limits:
          memory: 4G
    restart: unless-stopped

  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
    container_name: engrammic-tei
    ports:
      - "8081:8080"
    command: ["--model-id", "sentence-transformers/all-MiniLM-L6-v2"]
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s
    deploy:
      resources:
        limits:
          memory: 1G
    restart: unless-stopped

  memgraph:
    image: memgraph/memgraph-mage:3.10.1
    container_name: engrammic-memgraph
    ports:
      - "7687:7687"
    volumes:
      - memgraph-data:/var/lib/memgraph
    command: ["--log-level=WARNING", "--storage-properties-on-edges=true"]
    healthcheck:
      test: ["CMD-SHELL", "echo 'RETURN 1;' | mgconsole || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 1G
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:v1.18.0
    container_name: engrammic-qdrant
    ports:
      - "6333:6333"
    volumes:
      - qdrant-data:/qdrant/storage
    healthcheck:
      test: ["CMD-SHELL", "bash -c 'echo > /dev/tcp/localhost/6333'"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 512M
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: engrammic-redis
    volumes:
      - redis-data:/data
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "100mb"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 128M
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: engrammic-postgres
    volumes:
      - postgres-data:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=engrammic
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-engrammic}
      - POSTGRES_DB=engrammic
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U engrammic -d engrammic"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 256M
    restart: unless-stopped

volumes:
  ollama-models:
  memgraph-data:
  qdrant-data:
  redis-data:
  postgres-data:
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('docker/docker-compose.standalone-lite.yml'))"`
Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
git add docker/docker-compose.standalone-lite.yml
git commit -m "feat(standalone): add lite tier compose file

Includes Ollama (phi4-mini) and TEI (MiniLM) for minimal footprint.
Targets 8GB RAM minimum, 12GB recommended."
```

---

### Task 3: Create Podman Compose File

**Files:**
- Create: `docker/podman-compose.standalone.yml`

- [ ] **Step 1: Create the Podman compose file with SELinux labels**

```yaml
# docker/podman-compose.standalone.yml
# Engrammic Standalone for Podman (RHEL/Fedora with SELinux)
# Set MODEL_TIER=lite or MODEL_TIER=standard (default)
#
# Usage:
#   MODEL_TIER=lite podman-compose -f podman-compose.standalone.yml up -d
#
# For rootless Podman with volume permission issues:
#   podman-compose --podman-run-args="--userns=keep-id" up -d
#
# For GPU passthrough (not in compose, run manually):
#   podman run --device nvidia.com/gpu=all ollama/ollama

services:
  app:
    image: europe-north1-docker.pkg.dev/engrammic/releases/engrammic-api:latest
    container_name: engrammic-app
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=standalone
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
      - POSTGRES_USER=engrammic
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-engrammic}
      - POSTGRES_DATABASE=engrammic
      - LICENSE_VALIDATION_ENABLED=true
      - EMBEDDING_PROVIDER=tei
      - TEI_URL=http://tei:8080
      - EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS:-768}
      - LLM_PROVIDER=ollama
      - OLLAMA_BASE_URL=http://ollama:11434
      - DEFAULT_LLM_MODEL=${OLLAMA_MODEL:-deepseek-r1:7b}
      - MODELS__TIER=${MODEL_TIER:-standalone_standard}
    depends_on:
      memgraph:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      ollama:
        condition: service_healthy
      tei:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 5s
      start_period: 30s
      retries: 3
    restart: unless-stopped

  dagster:
    image: europe-north1-docker.pkg.dev/engrammic/releases/engrammic-dagster:latest
    container_name: engrammic-dagster
    ports:
      - "3000:3000"
    environment:
      - ENVIRONMENT=standalone
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
      - POSTGRES_USER=engrammic
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-engrammic}
      - POSTGRES_DATABASE=engrammic
      - EMBEDDING_PROVIDER=tei
      - TEI_URL=http://tei:8080
      - EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS:-768}
      - LLM_PROVIDER=ollama
      - OLLAMA_BASE_URL=http://ollama:11434
      - DEFAULT_LLM_MODEL=${OLLAMA_MODEL:-deepseek-r1:7b}
      - MODELS__TIER=${MODEL_TIER:-standalone_standard}
    depends_on:
      memgraph:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      ollama:
        condition: service_healthy
      tei:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:3000/server_info')"]
      interval: 30s
      timeout: 10s
      start_period: 30s
      retries: 3
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    container_name: engrammic-ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama-models:/root/.ollama:Z
    environment:
      - OLLAMA_MODEL=${OLLAMA_MODEL:-deepseek-r1:7b}
    entrypoint: ["/bin/sh", "-c", "ollama pull ${OLLAMA_MODEL:-deepseek-r1:7b} && ollama serve"]
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:11434/api/tags || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 90s
    restart: unless-stopped

  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
    container_name: engrammic-tei
    ports:
      - "8081:8080"
    command: ["--model-id", "${TEI_MODEL:-nomic-ai/nomic-embed-text-v1.5}"]
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s
    restart: unless-stopped

  memgraph:
    image: memgraph/memgraph-mage:3.10.1
    container_name: engrammic-memgraph
    ports:
      - "7687:7687"
    volumes:
      - memgraph-data:/var/lib/memgraph:Z
    command: ["--log-level=WARNING", "--storage-properties-on-edges=true"]
    healthcheck:
      test: ["CMD-SHELL", "echo 'RETURN 1;' | mgconsole || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:v1.18.0
    container_name: engrammic-qdrant
    ports:
      - "6333:6333"
    volumes:
      - qdrant-data:/qdrant/storage:Z
    healthcheck:
      test: ["CMD-SHELL", "bash -c 'echo > /dev/tcp/localhost/6333'"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: engrammic-redis
    volumes:
      - redis-data:/data:Z
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "200mb"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: engrammic-postgres
    volumes:
      - postgres-data:/var/lib/postgresql/data:Z
    environment:
      - POSTGRES_USER=engrammic
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-engrammic}
      - POSTGRES_DB=engrammic
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U engrammic -d engrammic"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

volumes:
  ollama-models:
  memgraph-data:
  qdrant-data:
  redis-data:
  postgres-data:
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('docker/podman-compose.standalone.yml'))"`
Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
git add docker/podman-compose.standalone.yml
git commit -m "feat(standalone): add Podman compose with SELinux support

Volume labels (:Z) for SELinux, MODEL_TIER env for tier selection.
Documents rootless workaround and GPU passthrough."
```

---

### Task 4: Create Environment Templates

**Files:**
- Create: `docker/standalone.env.example`
- Create: `docker/standalone-lite.env.example`

- [ ] **Step 1: Create standard tier env template**

```bash
# docker/standalone.env.example
# Engrammic Standalone - Standard Tier Configuration
# Copy to standalone.env and customize

# Database password (change in production!)
POSTGRES_PASSWORD=engrammic

# License key (required for self-hosted)
# ENGRAMMIC_LICENSE_KEY=your-license-key

# Optional: Override default models
# OLLAMA_MODEL=deepseek-r1:7b
# TEI_MODEL=nomic-ai/nomic-embed-text-v1.5
# EMBEDDING_DIMENSIONS=768
```

- [ ] **Step 2: Create lite tier env template**

```bash
# docker/standalone-lite.env.example
# Engrammic Standalone - Lite Tier Configuration
# Copy to standalone-lite.env and customize

# Database password (change in production!)
POSTGRES_PASSWORD=engrammic

# License key (required for self-hosted)
# ENGRAMMIC_LICENSE_KEY=your-license-key

# Optional: Override default models
# OLLAMA_MODEL=phi4-mini
# TEI_MODEL=sentence-transformers/all-MiniLM-L6-v2
# EMBEDDING_DIMENSIONS=384
```

- [ ] **Step 3: Commit**

```bash
git add docker/standalone.env.example docker/standalone-lite.env.example
git commit -m "feat(standalone): add environment templates

Standard tier (deepseek-r1, nomic-embed) and lite tier (phi4-mini, MiniLM)."
```

---

### Task 5: Add Standalone Tiers to models.yaml

**Files:**
- Modify: `config/models.yaml`

- [ ] **Step 1: Add standalone_lite tier after self_hosted_budget**

Add this block after line 127 (after `self_hosted_budget` tier closes):

```yaml

  # Standalone lite - minimal footprint for laptops
  # Requires: Ollama (phi4-mini), TEI (MiniLM), 8GB+ RAM
  standalone_lite:
    embeddings:
      provider: tei
      model: sentence-transformers/all-MiniLM-L6-v2
      dimensions: 384
    reasoning:
      provider: ollama
      model: phi4-mini
    fast:
      provider: ollama
      model: phi4-mini

  # Standalone standard - balanced offline deployment
  # Requires: Ollama (deepseek-r1:7b), TEI (nomic-embed), 32GB+ RAM
  standalone_standard:
    embeddings:
      provider: tei
      model: nomic-ai/nomic-embed-text-v1.5
      dimensions: 768
    reasoning:
      provider: ollama
      model: deepseek-r1:7b
    fast:
      provider: ollama
      model: deepseek-r1:7b
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('config/models.yaml'))"`
Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
git add config/models.yaml
git commit -m "feat(standalone): add standalone_lite and standalone_standard tiers

standalone_lite: phi4-mini + MiniLM (384 dims) for 8GB systems
standalone_standard: deepseek-r1:7b + nomic-embed (768 dims) for 32GB+ systems"
```

---

### Task 6: Create Justfile Module

**Files:**
- Create: `standalone.just`
- Modify: `justfile`

- [ ] **Step 1: Create standalone.just**

```just
# Standalone deployment with local models
# Imported by main justfile

standalone := "docker/docker-compose.standalone.yml"
standalone_lite := "docker/docker-compose.standalone-lite.yml"
podman_standalone := "docker/podman-compose.standalone.yml"

# =============================================================================
# Docker Standalone
# =============================================================================

# Start standalone stack (standard tier, 32GB+ RAM)
[group('standalone')]
up-standalone *args:
    docker compose -f {{standalone}} up -d {{args}}

# Start standalone stack (lite tier, 8GB+ RAM)
[group('standalone')]
up-standalone-lite *args:
    docker compose -f {{standalone_lite}} up -d {{args}}

# Stop standalone stack
[group('standalone')]
down-standalone:
    docker compose -f {{standalone}} down || docker compose -f {{standalone_lite}} down

# View standalone logs
[group('standalone')]
logs-standalone service="":
    docker compose -f {{standalone}} logs -f {{service}}

# =============================================================================
# Podman Standalone
# =============================================================================

# Start Podman standalone (tier: standard or lite)
[group('standalone')]
up-podman tier="standard" *args:
    #!/usr/bin/env bash
    if [ "{{tier}}" = "lite" ]; then
        MODEL_TIER=standalone_lite \
        OLLAMA_MODEL=phi4-mini \
        TEI_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
        EMBEDDING_DIMENSIONS=384 \
        podman-compose -f {{podman_standalone}} up -d {{args}}
    else
        MODEL_TIER=standalone_standard \
        OLLAMA_MODEL=deepseek-r1:7b \
        TEI_MODEL=nomic-ai/nomic-embed-text-v1.5 \
        EMBEDDING_DIMENSIONS=768 \
        podman-compose -f {{podman_standalone}} up -d {{args}}
    fi

# Stop Podman standalone
[group('standalone')]
down-podman:
    podman-compose -f {{podman_standalone}} down

# =============================================================================
# Model Management
# =============================================================================

# Pre-pull models for offline use (tier: standard or lite)
[group('standalone')]
pull-models tier="standard":
    #!/usr/bin/env bash
    if [ "{{tier}}" = "lite" ]; then
        echo "Pulling phi4-mini for lite tier..."
        docker run --rm -v ollama-models:/root/.ollama ollama/ollama pull phi4-mini
    else
        echo "Pulling deepseek-r1:7b for standard tier..."
        docker run --rm -v ollama-models:/root/.ollama ollama/ollama pull deepseek-r1:7b
    fi
    echo "TEI models are pulled on first container start."
```

- [ ] **Step 2: Add import to main justfile**

Add after line 19 (after `import 'deploy.just'`):

```just
import 'standalone.just'
```

- [ ] **Step 3: Verify just syntax**

Run: `just --list --group standalone`
Expected: Shows standalone commands (up-standalone, up-standalone-lite, etc.)

- [ ] **Step 4: Commit**

```bash
git add standalone.just justfile
git commit -m "feat(standalone): add justfile module

Commands: up-standalone, up-standalone-lite, up-podman, down-standalone,
down-podman, pull-models, logs-standalone"
```

---

### Task 7: Create User Documentation

**Files:**
- Create: `docs/self-hosted/standalone.md`

- [ ] **Step 1: Create docs directory if needed**

Run: `mkdir -p docs/self-hosted`

- [ ] **Step 2: Create documentation**

```markdown
# Standalone Deployment

Run Engrammic without cloud API dependencies using local LLMs and embeddings.

## Requirements

| Tier | RAM | GPU | Models |
|------|-----|-----|--------|
| Lite | 8GB min, 12GB recommended | Optional | phi4-mini (3.8B), MiniLM |
| Standard | 32GB+ | Optional (improves speed) | deepseek-r1:7b, nomic-embed |

## Quick Start

### Docker (Standard Tier)

```bash
# Copy environment template
cp docker/standalone.env.example docker/standalone.env
# Edit standalone.env with your license key

# Start the stack (first run downloads ~4GB of models)
just up-standalone

# Wait for healthchecks (2-3 minutes on first run)
docker ps

# Verify
curl http://localhost:8000/health
```

### Docker (Lite Tier)

```bash
cp docker/standalone-lite.env.example docker/standalone-lite.env
just up-standalone-lite
```

### Podman (RHEL/Fedora)

```bash
# Standard tier
just up-podman

# Lite tier
just up-podman tier=lite

# For rootless Podman with volume permission issues:
podman-compose --podman-run-args="--userns=keep-id" \
    -f docker/podman-compose.standalone.yml up -d
```

## Ports

| Service | Port | Purpose |
|---------|------|---------|
| App | 8000 | API + MCP |
| Dagster | 3000 | Pipeline UI |
| Ollama | 11434 | LLM server |
| TEI | 8081 | Embeddings |
| Memgraph | 7687 | Graph DB |
| Qdrant | 6333 | Vector DB |

## Model Persistence

Models are stored in Docker volumes and persist across restarts:
- `ollama-models` - LLM weights (~4GB standard, ~2GB lite)
- TEI caches models in the container layer

To pre-pull models for air-gap deployment:

```bash
# Standard tier
just pull-models

# Lite tier
just pull-models tier=lite
```

## GPU Acceleration

### Docker

GPU support is automatic if NVIDIA Container Toolkit is installed:

```bash
# Verify GPU is detected
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

### Podman

GPU passthrough uses CDI (not in compose file):

```bash
# Run Ollama manually with GPU
podman run --device nvidia.com/gpu=all -v ollama-models:/root/.ollama:Z \
    ollama/ollama serve
```

## Switching Tiers

Switching between lite and standard requires re-embedding due to different vector dimensions:

1. Stop current stack: `just down-standalone`
2. Remove Qdrant data: `docker volume rm engrammic_qdrant-data`
3. Start new tier: `just up-standalone` or `just up-standalone-lite`
4. Re-ingest your data

## Troubleshooting

### Services fail to start

Check if models are still downloading:
```bash
docker logs engrammic-ollama
docker logs engrammic-tei
```

### Out of memory

Lite tier minimum is 8GB but 12GB is recommended. Reduce Memgraph memory if needed:
```yaml
# In docker-compose.standalone-lite.yml
memgraph:
  deploy:
    resources:
      limits:
        memory: 512M  # Down from 1G
```

### SELinux denials (Podman)

Check for denials:
```bash
ausearch -m avc -ts recent
```

All volumes should have `:Z` suffix in podman-compose.standalone.yml.

### Slow inference

Without GPU, inference is CPU-bound. For better performance:
1. Use lite tier (smaller model)
2. Add NVIDIA GPU with Container Toolkit
3. Increase CPU allocation in compose resource limits
```

- [ ] **Step 3: Commit**

```bash
git add docs/self-hosted/standalone.md
git commit -m "docs: add standalone deployment guide

Covers Docker/Podman setup, tier selection, GPU acceleration,
model persistence, and troubleshooting."
```

---

### Task 8: Verification

- [ ] **Step 1: Verify all files created**

Run: `ls -la docker/docker-compose.standalone*.yml docker/podman-compose.standalone.yml docker/standalone*.env.example standalone.just`

Expected: All 6 files listed

- [ ] **Step 2: Verify justfile imports work**

Run: `just --list --group standalone`

Expected: Lists up-standalone, up-standalone-lite, up-podman, down-standalone, down-podman, pull-models, logs-standalone

- [ ] **Step 3: Validate all compose files**

Run:
```bash
for f in docker/docker-compose.standalone*.yml docker/podman-compose.standalone.yml; do
    echo "Validating $f..."
    docker compose -f "$f" config --quiet && echo "OK" || echo "FAIL"
done
```

Expected: All files show "OK"

- [ ] **Step 4: Verify models.yaml has new tiers**

Run: `grep -E "standalone_(lite|standard):" config/models.yaml`

Expected: Shows both `standalone_lite:` and `standalone_standard:`

- [ ] **Step 5: Final commit with all changes**

If any files were missed:
```bash
git status
git add -A
git commit -m "feat(standalone): complete standalone and podman deployment support"
```
