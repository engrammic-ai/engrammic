# Standalone and Podman Deployment

## Context

Users want to run Engrammic without cloud LLM dependencies. Two drivers:
1. **Air-gap deployments** - enterprises that can't call external APIs
2. **Cost control** - developers who want zero ongoing API costs
3. **RHEL/Fedora users** - need Podman support with SELinux compatibility

Current state: self-hosted config (`docker-compose.selfhosted.yml`) exists but requires cloud LLM credentials (Vertex/OpenAI/Anthropic). LiteLLM abstraction already supports Ollama. TEI embedding service already implemented with fallback.

## Design

### Compose File Structure

Flat, self-contained files (no inheritance due to GPU passthrough fragility):

```
docker/
  docker-compose.selfhosted.yml         # existing (cloud LLMs)
  docker-compose.standalone.yml         # 32GB+ target, deepseek-r1:7b + nomic-embed
  docker-compose.standalone-lite.yml    # 8GB target, phi4-mini + MiniLM
  podman-compose.standalone.yml         # SELinux-aware, MODEL_TIER env selects tier
```

### Model Selection

| Tier | Target | Reasoning Model | Embedding Model | Embedding Dims |
|------|--------|-----------------|-----------------|----------------|
| Lite | 8GB RAM, no GPU | phi4-mini (3.8B) | all-MiniLM-L6-v2 | 384 |
| Standard | 32GB+ RAM, optional GPU | deepseek-r1:7b | nomic-embed-text-v1.5 | 768 |

Memory budget (lite): phi4-mini ~3GB + MiniLM ~500MB + services ~3GB = 6.5GB. Document "8GB minimum, 12GB recommended".

### New Services

**Ollama (LLM server):**
```yaml
ollama:
  image: ollama/ollama:latest
  ports:
    - "11434:11434"
  volumes:
    - ollama-models:/root/.ollama
  environment:
    - OLLAMA_MODEL=${OLLAMA_MODEL:-phi4-mini}
  entrypoint: ["/bin/sh", "-c", "ollama pull $OLLAMA_MODEL && ollama serve"]
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 90s
  deploy:
    resources:
      limits:
        memory: 4G  # lite: 4G, standard: 8G
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu]
```

**TEI (embedding server):**
```yaml
tei:
  image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
  ports:
    - "8081:8080"
  command: ["--model-id", "sentence-transformers/all-MiniLM-L6-v2"]
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 60s
  deploy:
    resources:
      limits:
        memory: 1G  # lite: 1G, standard: 2G
```

### App Service Configuration

Environment variables for standalone mode:
```yaml
environment:
  - EMBEDDING_PROVIDER=tei
  - TEI_URL=http://tei:8080
  - EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS:-384}
  - LLM_PROVIDER=ollama
  - OLLAMA_BASE_URL=http://ollama:11434
  - DEFAULT_LLM_MODEL=${OLLAMA_MODEL:-phi4-mini}
  - MODELS__TIER=standalone_lite  # or standalone_standard
```

### Config Alignment

Add to `config/models.yaml`:
```yaml
tiers:
  standalone_lite:
    embeddings:
      provider: tei
      model: all-MiniLM-L6-v2
      dimensions: 384
    reasoning:
      provider: ollama
      model: phi4-mini
    fast:
      provider: ollama
      model: phi4-mini

  standalone_standard:
    embeddings:
      provider: tei
      model: nomic-embed-text-v1.5
      dimensions: 768
    reasoning:
      provider: ollama
      model: deepseek-r1:7b
    fast:
      provider: ollama
      model: deepseek-r1:7b
```

### Embedding Dimension Handling

Collection name derived from dimensions to prevent mixing:
- Lite tier: `context_vectors_384`
- Standard tier: `context_vectors_768`

Switching tiers requires re-embedding. Document as explicit migration step.

### Podman Specifics

**Volume labels** - all mounts get `:Z` suffix for SELinux:
```yaml
volumes:
  - ollama-models:/root/.ollama:Z
  - postgres-data:/var/lib/postgresql/data:Z
  - qdrant-data:/qdrant/storage:Z
```

**GPU passthrough** - CDI syntax (documented, not in compose):
```bash
podman run --device nvidia.com/gpu=all ollama/ollama
```

**Rootless support** - documented workaround for volume permissions:
```bash
podman-compose --podman-run-args="--userns=keep-id" up -d
```

**Tier selection** via environment:
```bash
MODEL_TIER=lite podman-compose -f podman-compose.standalone.yml up -d
```

### Model Delivery

**Default (pull on run):**
- Ollama entrypoint: `ollama pull $OLLAMA_MODEL && ollama serve`
- TEI downloads model weights on first start, cached in container layer

**Air-gap (documented):**
```bash
# Pre-pull Ollama models to volume
docker run -v ollama-models:/root/.ollama ollama/ollama pull phi4-mini

# For TEI, use pre-downloaded model mount
docker run -v ./models:/data ghcr.io/huggingface/text-embeddings-inference:cpu-1.5 \
  --model-id /data/all-MiniLM-L6-v2
```

### Justfile Module

New file `standalone.just`:
```just
# Standalone deployment with local models

standalone := "docker/docker-compose.standalone.yml"
standalone_lite := "docker/docker-compose.standalone-lite.yml"
podman_standalone := "docker/podman-compose.standalone.yml"

[group('standalone')]
up-standalone *args:
    docker compose -f {{standalone}} up -d {{args}}

[group('standalone')]
up-standalone-lite *args:
    docker compose -f {{standalone_lite}} up -d {{args}}

[group('standalone')]
down-standalone:
    docker compose -f {{standalone}} down

[group('standalone')]
up-podman tier="standard":
    MODEL_TIER={{tier}} podman-compose -f {{podman_standalone}} up -d

[group('standalone')]
down-podman:
    podman-compose -f {{podman_standalone}} down

[group('standalone')]
pull-models tier="standard":
    @echo "Pulling models for {{tier}} tier..."
    docker compose -f {{standalone}} run --rm ollama ollama pull ${OLLAMA_MODEL}
```

Add to main `justfile`:
```just
import 'standalone.just'
```

## Files to Create/Modify

| File | Action |
|------|--------|
| `docker/docker-compose.standalone.yml` | Create - standard tier |
| `docker/docker-compose.standalone-lite.yml` | Create - lite tier |
| `docker/podman-compose.standalone.yml` | Create - Podman with tier selection |
| `docker/standalone.env.example` | Create - env template |
| `docker/standalone-lite.env.example` | Create - lite env template |
| `config/models.yaml` | Modify - add standalone tiers |
| `standalone.just` | Create - justfile module |
| `justfile` | Modify - import standalone.just |
| `docs/self-hosted/standalone.md` | Create - user documentation |

## Verification

1. **Lite tier smoke test:**
   ```bash
   just up-standalone-lite
   # Wait for healthchecks
   curl http://localhost:8000/health
   # Test MCP tool
   curl -X POST http://localhost:8000/mcp -d '{"method": "remember", ...}'
   just down-standalone
   ```

2. **Standard tier smoke test:**
   ```bash
   just up-standalone
   # Same verification
   just down-standalone
   ```

3. **Podman smoke test (on Fedora/RHEL):**
   ```bash
   just up-podman tier=lite
   # Verify no SELinux denials: ausearch -m avc -ts recent
   just down-podman
   ```

4. **Model persistence test:**
   ```bash
   just up-standalone-lite
   # Wait for model download
   just down-standalone
   just up-standalone-lite
   # Should start faster (model cached in volume)
   ```

5. **Embedding dimension test:**
   - Store a node with lite tier
   - Verify Qdrant collection is `context_vectors_384`
   - Switch to standard, verify new collection `context_vectors_768`
