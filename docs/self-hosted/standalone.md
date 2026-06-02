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

To enable GPU for Ollama, edit `docker-compose.standalone.yml` and uncomment the GPU reservation block in the ollama service.

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
