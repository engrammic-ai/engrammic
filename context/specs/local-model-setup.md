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
engrammic setup models [--lang <code>] [--dir <path>]

# Interactive mode
engrammic setup models
  Embedding model:
    [1] bge-base-en-v1.5    (English, 440MB)
    [2] bge-m3              (Multilingual 100+ langs, 2.2GB)
    [3] custom              (HuggingFace model ID)
  
  Reranker:
    [1] bge-reranker-base   (1.1GB)
    [2] bge-reranker-v2-m3  (Multilingual, 2.2GB)
    [3] skip                (use embedding similarity)
  
  LLM for SAGE synthesis:
    [1] ollama              (configure separately)
    [2] skip                (disable background synthesis)

# Non-interactive
engrammic setup models --embedding bge-m3 --reranker skip --dir /data/models
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
    bge-m3/
      config.json
      model.safetensors
      tokenizer.json
      ...
  rerankers/
    bge-reranker-base/
      ...
  manifest.json   # tracks installed models + versions
```

### Download Mechanism

1. Installer fetches model metadata from HuggingFace Hub API
2. Downloads model files with progress bar
3. Verifies checksums
4. Updates manifest.json

Resume support for interrupted downloads. Proxy-aware (respects `HTTP_PROXY`).

### Self-Hosted Integration

Docker Compose mounts the models directory:

```yaml
services:
  api:
    volumes:
      - ${ENGRAMMIC_MODELS_DIR:-~/.local/share/engrammic/models}:/models:ro
    environment:
      - EMBEDDING_PROVIDER=local
      - EMBEDDING_MODEL_PATH=/models/embeddings/bge-m3
      - RERANKER_PROVIDER=local
      - RERANKER_MODEL_PATH=/models/rerankers/bge-reranker-base
```

### Provider Configuration

New settings in `settings.py`:

```python
class EmbeddingConfig(BaseSettings):
    provider: Literal["vertex", "openai", "local"] = "vertex"
    model_path: str | None = None  # for local provider
    
class RerankerConfig(BaseSettings):
    provider: Literal["vertex", "local", "none"] = "vertex"
    model_path: str | None = None
```

Local provider uses `sentence-transformers` for embeddings, `transformers` for reranking.

### Model Recommendations

| Use Case | Embedding | Reranker | Total Size |
|----------|-----------|----------|------------|
| English-only, minimal | bge-base-en-v1.5 | skip | 440MB |
| English, quality | bge-base-en-v1.5 | bge-reranker-base | 1.5GB |
| Multilingual, quality | bge-m3 | bge-reranker-v2-m3 | 4.4GB |

### Presets

Shorthand for common configurations:

```bash
engrammic setup models --preset minimal    # English embed only
engrammic setup models --preset standard   # English + reranker
engrammic setup models --preset multilingual  # Full multilingual
```

## Prerequisites (User Responsibility)

What the user must have before running our installer:

### Required

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Docker + Compose | v24+ / v2.20+ | For running self-hosted services |
| Disk space | 2GB | Minimum for English-only; 5GB+ for multilingual |
| RAM | 8GB | 16GB+ recommended for reranker |

### Optional (for GPU acceleration)

| Requirement | Version | Notes |
|-------------|---------|-------|
| NVIDIA GPU | Compute 7.0+ | RTX 20xx or newer |
| NVIDIA Driver | 525+ | `nvidia-smi` should work |
| NVIDIA Container Toolkit | latest | `nvidia-ctk --version` |

User verifies prerequisites themselves. Our installer checks and warns but doesn't install system deps.

### Prerequisite Check Command

```bash
engrammic doctor
  [ok] Docker 24.0.7
  [ok] Docker Compose 2.23.0
  [ok] Disk: 42GB free
  [ok] RAM: 32GB
  [--] GPU: not detected (CPU inference will be used)
```

## Installation Steps (Our Responsibility)

What `engrammic setup models` does:

### Step 1: Validate Environment

- Check Docker running
- Check disk space sufficient for selected models
- Warn if RAM < recommended for model size

### Step 2: Download Models

```
Downloading bge-m3 (2.2GB)...
  [=================>          ] 68% 1.5GB/2.2GB  ETA 45s
```

- Fetch from HuggingFace Hub
- Resume interrupted downloads
- Verify SHA256 checksums
- Write to configured `--dir`

### Step 3: Generate Config

- Write `manifest.json` tracking installed models
- Generate `.env` snippet for self-hosted compose:
  ```
  EMBEDDING_PROVIDER=local
  EMBEDDING_MODEL_PATH=/models/embeddings/bge-m3
  RERANKER_PROVIDER=local
  RERANKER_MODEL_PATH=/models/rerankers/bge-reranker-base
  ```

### Step 4: Verify

- Load model, run test embedding
- Report success + next steps

```
Models installed to ~/.local/share/engrammic/models

Next steps:
  1. Add to your .env:
     ENGRAMMIC_MODELS_DIR=~/.local/share/engrammic/models
  2. Run: docker compose up -d
```

## Implementation Phases

### Phase 1: Installer CLI

1. `engrammic doctor` - prerequisite checker
2. `engrammic setup models` - download + configure
3. Manifest tracking, resume support

### Phase 2: context-service Local Providers

1. `LocalEmbeddingProvider` (sentence-transformers)
2. `LocalRerankerProvider` (transformers)
3. Config-driven provider selection
4. Self-hosted compose template with volume mount

### Phase 3: Documentation

1. Self-hosted quickstart with local models
2. Model selection guide
3. GPU setup guide (optional)

## Open Questions

1. **GPU support**: Ship CUDA-enabled torch wheels? Or CPU-only with optional GPU guide?
2. **Model updates**: Auto-update models? Manual `engrammic update models`?
3. **Disk space checks**: Warn if insufficient space before download?
4. **Ollama integration**: Auto-configure ollama for SAGE, or just document?

## Non-Goals

- Bundling models in Docker images (too large)
- Custom model training
- Model fine-tuning UI
