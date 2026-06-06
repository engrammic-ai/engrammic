# Local Model Setup

Status: Draft
Author: Claude
Date: 2026-06-06

## Problem

Self-hosted Engrammic requires external AI providers (Vertex AI, OpenAI) for embeddings and reranking. This creates friction:
- API key management
- Cost concerns for high-volume usage
- Data privacy (embeddings sent to cloud)
- Network dependency

## Solution

Extend the Engrammic installer (`get.engrammic.ai`) to download and configure local models at setup time. Models are cached on disk; self-hosted services mount the cache volume.

## Design

### Model Selection

Interactive or flag-based selection:

```bash
engrammic setup models [--lang <code>] [--dir <path>] [--apply]

# Interactive mode
engrammic setup models
  Embedding model:
    [1] bge-base-en-v1.5    (English, 440MB model + 2.1GB runtime = 2.5GB)
    [2] bge-m3              (Multilingual 100+ langs, 2.2GB model + 2.1GB runtime = 4.3GB)
    [3] custom              (HuggingFace model ID)
  
  Reranker:
    [1] bge-reranker-base   (1.1GB, adds ~3GB RAM at runtime)
    [2] bge-reranker-v2-m3  (Multilingual, 2.2GB, adds ~5GB RAM)
    [3] skip                (use embedding similarity)
  
  LLM for SAGE synthesis:
    [1] ollama              (configure separately)
    [2] skip                (disable background synthesis)

# Non-interactive
engrammic setup models --embedding bge-m3 --reranker skip --dir /data/models --apply
```

### Storage Location

Configurable with sensible defaults:

| Platform | Default |
|----------|---------|
| Linux    | `~/.local/share/engrammic/models` |
| macOS    | `~/Library/Application Support/engrammic/models` |
| Windows  | `%APPDATA%\engrammic\models` |
| Docker   | `/var/lib/engrammic/models` (volume mount) |

Override via:
- `--dir` flag
- `ENGRAMMIC_MODELS_DIR` env var
- Config file (`~/.engrammic/config.toml`)

### Directory Structure

```
<models_dir>/
  embeddings/
    bge-m3@1.0.0/           # versioned directory
      config.json
      model.safetensors     # safetensors ONLY, no pickle
      tokenizer.json
      ...
  rerankers/
    bge-reranker-base@1.0.0/
      ...
  cache/                    # ONNX runtime cache, writable
    onnx_optimized/
  manifest.json             # tracks installed models + versions + dimensions
```

### Model Versioning

Manifest tracks exact versions for reproducibility:

```json
{
  "schema_version": 1,
  "installed": {
    "embeddings/bge-m3": {
      "version": "1.0.0",
      "revision": "abc123",
      "dimensions": 1024,
      "installed_at": "2026-06-06T12:00:00Z",
      "checksum": "sha256:..."
    }
  },
  "lockfile": true
}
```

Pin versions with `--lock` to prevent auto-updates:
```bash
engrammic setup models --lock
engrammic update models  # respects lockfile, only security patches
engrammic update models --upgrade  # ignores lock, pulls latest
```

### Download Mechanism

1. Installer fetches model metadata from HuggingFace Hub API
2. **Validates model uses safetensors format** (rejects pickle for security)
3. Downloads model files with progress bar
4. Verifies SHA256 checksums
5. Updates manifest.json with version + dimensions

Resume support for interrupted downloads. Proxy-aware (respects `HTTP_PROXY`).

### Offline / Air-Gapped Installation

For environments without internet access:

```bash
# On connected machine: export to tarball
engrammic export models --preset standard -o engrammic-models.tar.gz

# On air-gapped machine: import
engrammic import models engrammic-models.tar.gz --dir /data/models
```

Tarball includes models + manifest + checksums.

### Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| Linux x86_64 | Full | Primary target |
| Linux ARM64 | Full | Graviton, Ampere |
| macOS x86_64 | Full | Intel Macs |
| macOS ARM64 | Full | Apple Silicon (MPS acceleration) |
| Windows x86_64 | Full | WSL2 recommended for Docker |

ARM64 uses `torch` ARM wheels. Apple Silicon gets MPS acceleration automatically.

### Self-Hosted Integration

Docker Compose mounts the models directory:

```yaml
services:
  api:
    volumes:
      - ${ENGRAMMIC_MODELS_DIR:-~/.local/share/engrammic/models}:/models:ro
      - engrammic-model-cache:/models/cache:rw  # ONNX cache needs write
    environment:
      - EMBEDDING_PROVIDER=local
      - EMBEDDING_MODEL_PATH=/models/embeddings/bge-m3@1.0.0
      - RERANKER_PROVIDER=local
      - RERANKER_MODEL_PATH=/models/rerankers/bge-reranker-base@1.0.0
    user: "1000:1000"  # match host UID/GID for volume permissions

volumes:
  engrammic-model-cache:
```

### Provider Configuration

New settings in `settings.py`:

```python
class EmbeddingConfig(BaseSettings):
    provider: Literal["vertex", "openai", "local"] = "vertex"
    model_path: str | None = None
    use_onnx: bool = True  # ONNX runtime for faster CPU inference
    
class RerankerConfig(BaseSettings):
    provider: Literal["vertex", "local", "none"] = "vertex"
    model_path: str | None = None
    use_onnx: bool = True
```

Local provider uses ONNX Runtime (preferred) or PyTorch fallback.

### Model Recommendations

| Use Case | Embedding | Reranker | Disk | RAM | CPU Latency |
|----------|-----------|----------|------|-----|-------------|
| Minimal | bge-base-en-v1.5 | skip | 2.5GB | 4GB | ~50ms |
| Standard | bge-base-en-v1.5 | bge-reranker-base | 5GB | 8GB | ~150ms |
| Multilingual | bge-m3 | bge-reranker-v2-m3 | 8GB | 16GB | ~300ms |

Note: Latency is per-query on 4-core CPU. GPU reduces 5-10x.

### Presets

```bash
engrammic setup models --preset minimal      # 2.5GB disk, 4GB RAM, English
engrammic setup models --preset standard     # 5GB disk, 8GB RAM, English + rerank
engrammic setup models --preset multilingual # 8GB disk, 16GB RAM, 100+ languages
```

### Custom Models

For `--embedding custom`:

```bash
engrammic setup models --embedding sentence-transformers/all-MiniLM-L6-v2
```

Validation:
- Must be sentence-transformers compatible architecture
- Must use safetensors format
- Dimensions extracted and stored in manifest

### Switching Models (Dimension Mismatch)

Changing embedding models invalidates existing vectors:

```bash
engrammic setup models --embedding bge-m3

WARNING: Embedding model change detected!
  Current: bge-base-en-v1.5 (768 dimensions)
  New: bge-m3 (1024 dimensions)

Existing Qdrant vectors are INCOMPATIBLE with the new model.
You must re-embed all content. Options:

  [1] Proceed and re-embed (may take hours for large datasets)
  [2] Cancel

Continue? [1/2]:
```

### Uninstall / Cleanup

```bash
engrammic uninstall models                    # remove all models
engrammic uninstall models --embedding bge-m3 # remove specific model
engrammic cleanup models                      # remove old versions, clear cache
```

## Prerequisites (User Responsibility)

What the user must have before running our installer:

### Required

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Docker + Compose | v24+ / v2.20+ | For running self-hosted services |
| Disk space | 3GB | Minimum; 10GB+ for multilingual |
| RAM | 8GB | 16GB+ recommended for reranker |

### Optional (for GPU acceleration)

| Requirement | Version | Notes |
|-------------|---------|-------|
| NVIDIA GPU | Compute 7.0+ | RTX 20xx or newer |
| NVIDIA Driver | 525+ | `nvidia-smi` should work |
| NVIDIA Container Toolkit | latest | `nvidia-ctk --version` |
| Apple Silicon | M1+ | MPS acceleration automatic |

### Prerequisite Check Command

```bash
engrammic doctor
  [ok] Docker 24.0.7
  [ok] Docker Compose 2.23.0
  [ok] Disk: 42GB free (need 5GB for standard preset)
  [ok] RAM: 32GB (need 8GB for standard preset)
  [ok] Platform: linux/amd64
  [--] GPU: not detected (CPU inference will be used, expect ~150ms latency)
```

## Installation Steps (Our Responsibility)

What `engrammic setup models` does:

### Step 1: Validate Environment

- Check Docker running
- Check disk space sufficient for selected models + torch runtime
- Warn if RAM < recommended for model size
- Detect platform (x86_64/ARM64)

### Step 2: Download Models

```
Downloading bge-m3 (2.2GB)...
  [=================>          ] 68% 1.5GB/2.2GB  ETA 45s

Downloading PyTorch runtime (2.1GB, one-time)...
  [=========>                  ] 34% 720MB/2.1GB  ETA 2m

Verifying checksums...
  [ok] bge-m3: sha256:abc123...

Loading model for verification (this takes 30-60 seconds on CPU)...
  [=================>          ] Loading weights...
```

- Fetch from HuggingFace Hub (safetensors only)
- Download torch/ONNX runtime if not cached
- Resume interrupted downloads
- Verify SHA256 checksums
- Write to configured `--dir`

### Step 3: Generate Config

- Write `manifest.json` tracking installed models + versions + dimensions
- Generate `.env` snippet:
  ```
  EMBEDDING_PROVIDER=local
  EMBEDDING_MODEL_PATH=/models/embeddings/bge-m3@1.0.0
  RERANKER_PROVIDER=local
  RERANKER_MODEL_PATH=/models/rerankers/bge-reranker-base@1.0.0
  ```

With `--apply` flag: auto-append to `.env` file.

### Step 4: Verify

- Load model (show progress, ~30-60s on CPU)
- Run test embedding
- Report latency baseline
- Report success + next steps

```
Models installed to ~/.local/share/engrammic/models
Test embedding latency: 47ms (CPU)

Next steps:
  docker compose up -d
```

### Error Handling

| Error | Recovery |
|-------|----------|
| Download interrupted | Resume with `engrammic setup models --resume` |
| Disk full | Clear space, run again (partial downloads preserved) |
| Checksum mismatch | Auto-retry download; if persistent, report and abort |
| Model load fails | Check RAM, suggest smaller model |
| Permission denied | Print required UID/GID for volume mount |

## Config File Schema

`~/.engrammic/config.toml`:

```toml
[models]
dir = "/data/engrammic/models"
auto_update = false
lockfile = true

[models.embedding]
name = "bge-m3"
version = "1.0.0"
use_onnx = true

[models.reranker]
name = "bge-reranker-base"
version = "1.0.0"
use_onnx = true

[models.llm]
provider = "ollama"
model = "llama3:8b"
endpoint = "http://localhost:11434"
```

## Ollama Integration for SAGE

SAGE synthesis requires an LLM with:
- Structured output / JSON mode
- 8K+ context window
- Instruction following

Recommended models:
| Model | Size | RAM | Notes |
|-------|------|-----|-------|
| llama3:8b | 4.7GB | 8GB | Good balance |
| mistral:7b | 4.1GB | 8GB | Fast, good JSON |
| llama3:70b | 40GB | 48GB | Best quality |

Setup:
```bash
# Install ollama (user responsibility)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull model
ollama pull llama3:8b

# Configure in .env
SAGE_LLM_PROVIDER=ollama
SAGE_LLM_MODEL=llama3:8b
SAGE_LLM_ENDPOINT=http://host.docker.internal:11434
```

## Security Considerations

1. **safetensors only**: Reject models using pickle format (arbitrary code execution risk)
2. **Checksum verification**: All downloads verified against HuggingFace-published SHA256
3. **Read-only mount**: Models mounted `:ro` in containers (cache volume separate)
4. **No network in inference**: Local models don't phone home
5. **Supply chain**: Consider mirroring to private registry for enterprise (future)

## Implementation Phases

### Phase 1: Installer CLI

1. `engrammic doctor` - prerequisite checker
2. `engrammic setup models` - download + configure
3. `engrammic uninstall models` - cleanup
4. `engrammic export/import models` - offline support
5. Manifest tracking, versioning, resume support

### Phase 2: context-service Local Providers

1. `LocalEmbeddingProvider` (ONNX Runtime, PyTorch fallback)
2. `LocalRerankerProvider` (ONNX Runtime, PyTorch fallback)
3. Config-driven provider selection
4. Lazy model loading (don't block startup)
5. Self-hosted compose template with volume mount

### Phase 3: Documentation

1. Self-hosted quickstart with local models
2. Model selection guide (size/quality/language tradeoffs)
3. GPU setup guide (NVIDIA, Apple Silicon)
4. Ollama setup for SAGE
5. Air-gapped installation guide

## Open Questions

1. **ONNX conversion**: Ship pre-converted ONNX models, or convert on first load?
2. **Model mirroring**: Host models on our own CDN/registry for reliability?
3. **Telemetry**: Anonymous usage stats for model selection (opt-in)?

## Non-Goals

- Bundling models in Docker images (too large)
- Custom model training
- Model fine-tuning UI
- Automatic SAGE LLM download (ollama handles this)
