# Standalone Architecture Design

**Date:** 2026-06-09  
**Status:** Approved  
**Scope:** TEI reranker support, standalone tiers, installer integration

## Overview

Add fully air-gapped standalone deployment tiers with local LLM (Ollama), embeddings (TEI), and reranking (TEI cross-encoder). Keeps standalone deployment separate from beta/selfhosted without adding dependencies to the main service.

## Goals

1. Three standalone tiers (lite/standard/pro) with different RAM/quality tradeoffs
2. TEI-based reranking for standard/pro tiers (no cloud API required)
3. Same Docker images as selfhosted (compose files handle bundling)
4. Installer wizard for tier selection
5. 768d embeddings across all tiers (upgrade path without re-embedding)

## Non-Goals

- Changing beta deployment (stays on Vertex AI)
- Adding new Python dependencies
- Per-tier embedding dimensions

## Tier Specification

| Tier | RAM | LLM | Embeddings (768d) | Reranker | Multilingual |
|------|-----|-----|-------------------|----------|--------------|
| standalone_lite | 8GB | gemma4:e4b | nomic-embed-v1.5 | none | Partial |
| standalone_standard | 32GB | gemma4:12b | nomic-embed-v2 | bge-reranker-v2-m3 | Yes |
| standalone_pro | 64GB | gemma4:26b | nomic-embed-v2 | jina-reranker-v2 | Yes |

### Model Rationale

- **768d embeddings**: Consistent across tiers for upgrade path. Graph structure provides semantic differentiation beyond embedding nuance.
- **nomic-embed**: 137M params, fits lite tier, Apache 2.0, Ollama-native
- **gemma4 family**: Apache 2.0, multimodal, strong reasoning, available in Ollama
- **bge-reranker-v2-m3**: Best quality/latency for multilingual, TEI-compatible
- **jina-reranker-v2**: Slightly better for long docs, pro tier luxury

### Tier Limitations

- **Lite**: No reranker, English-focused embeddings (documented tradeoff)
- **Standard**: Recommended for most users
- **Pro**: For power users, small teams, enterprise air-gapped

## Architecture

### Code Changes

```
src/context_service/reranking/
├── reranker.py          # LiteLLMReranker (existing, unchanged)
├── tei_reranker.py      # TEIReranker (new)
└── factory.py           # get_reranker() factory (new)
```

#### tei_reranker.py (~80 lines)

```python
class TEIReranker:
    """Cross-encoder reranking via TEI /rerank endpoint."""
    
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
    ) -> None: ...
    
    async def rerank(
        self,
        query: str,
        documents: list[str],
        node_ids: list[str],
        top_k: int = 10,
    ) -> list[RerankResult]: ...
```

- Mirrors `LiteLLMReranker` interface
- HTTP POST to TEI `/rerank` endpoint
- Same retry logic pattern as `tei_embeddings.py`
- Uses existing `httpx` (no new dependencies)

#### factory.py

```python
def get_reranker(config: ModelsConfig) -> LiteLLMReranker | TEIReranker | None:
    """Factory to select reranker based on models.yaml provider."""
    spec = config.get_reranker_model()
    if spec is None:
        return None
    
    if spec.provider == "tei":
        return TEIReranker(
            base_url=spec.url,
            model=spec.model,
        )
    else:
        return LiteLLMReranker(
            model=f"{spec.provider}/{spec.model}",
        )
```

#### context_query.py changes

Replace inline instantiation:
```python
# Before
reranker = LiteLLMReranker(model=reranker_model, ...)

# After
reranker = get_reranker(models_config)
if reranker is None:
    return results, False, False
```

### Compose File Structure

```
docker/
├── docker-compose.selfhosted.yml        # Existing (user brings creds)
├── docker-compose.standalone-lite.yml   # Update existing
├── docker-compose.standalone-standard.yml  # Rename from standalone.yml
└── docker-compose.standalone-pro.yml    # New
```

#### Standalone compose services

```yaml
services:
  app:           # europe-north1-docker.pkg.dev/engrammic/releases/engrammic-api:latest
  dagster:       # europe-north1-docker.pkg.dev/engrammic/releases/engrammic-dagster:latest
  ollama:        # ollama/ollama:latest (tier-specific model pull)
  tei-embed:     # ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
  tei-reranker:  # ghcr.io/huggingface/text-embeddings-inference:cpu-1.5 (standard/pro only)
  memgraph:      # memgraph/memgraph-mage:3.10.1
  qdrant:        # qdrant/qdrant:v1.18.0
  redis:         # redis:7-alpine
  postgres:      # postgres:16-alpine
```

#### Per-tier differences

| Service | lite | standard | pro |
|---------|------|----------|-----|
| ollama entrypoint | `ollama pull gemma4:e4b` | `ollama pull gemma4:12b` | `ollama pull gemma4:26b` |
| tei-embed model | nomic-embed-v1.5 | nomic-embed-v2-moe | nomic-embed-v2-moe |
| tei-reranker | absent | bge-reranker-v2-m3 | jina-reranker-v2 |
| ollama memory limit | 4G | 8G | 20G |
| app memory limit | 512M | 512M | 512M |

### models.yaml Configuration

```yaml
standalone_lite:
  embeddings:
    provider: tei
    model: nomic-ai/nomic-embed-text-v1.5
    dimensions: 768
  reasoning:
    provider: ollama
    model: gemma4:e4b
  fast:
    provider: ollama
    model: gemma4:e4b
  # reranker: intentionally absent

standalone_standard:
  embeddings:
    provider: tei
    model: nomic-ai/nomic-embed-text-v2-moe
    dimensions: 768
  reasoning:
    provider: ollama
    model: gemma4:12b
  fast:
    provider: ollama
    model: gemma4:12b
  reranker:
    provider: tei
    model: BAAI/bge-reranker-v2-m3
    url: http://tei-reranker:8080

standalone_pro:
  embeddings:
    provider: tei
    model: nomic-ai/nomic-embed-text-v2-moe
    dimensions: 768
  reasoning:
    provider: ollama
    model: gemma4:26b
  fast:
    provider: ollama
    model: gemma4:12b
  reranker:
    provider: tei
    model: jinaai/jina-reranker-v2-base-multilingual
    url: http://tei-reranker:8080
```

### Installer Changes (mcp-client)

#### Deployment mode selection

```
Deployment mode:
  1. Cloud - connect to mcp.engrammic.ai (free tier available)
  2. Self-hosted - run locally with Docker (bring your own embeddings)
  3. Standalone - fully local, no API keys (8-64GB RAM)
```

#### Standalone tier selection

```
Standalone tier:
  1. Lite (8GB RAM) - gemma4:e4b, no reranker, English-focused
  2. Standard (32GB RAM) - gemma4:12b, reranker, multilingual [Recommended]
  3. Pro (64GB+ RAM) - gemma4:26b, best quality reranker
```

#### Files to add/modify

- `src/standalone.rs` — standalone wizard (or extend `selfhost.rs`)
- `assets/docker-compose.standalone-{lite,standard,pro}.yml`
- `assets/models-standalone-{lite,standard,pro}.yaml`
- License key prompt (same as selfhosted)

#### Installer writes

- `docker-compose.yml` (tier-specific)
- `config/models.yaml` (tier-specific)
- `.env` (license key, telemetry consent, postgres password)

## Health & Observability

### Health check response

```json
{
  "status": "healthy",
  "reranker": "disabled",  // lite tier
  "reranker": "ready",     // standard/pro with working reranker
  "reranker": "unavailable"  // config error or TEI down
}
```

Distinguishes intentional (disabled) from broken (unavailable).

### Lazy loading

Reranker initializes on first query, not at startup. Reduces cold-start RAM spike for standard/pro tiers.

## Testing

### Unit tests

- `tests/reranking/test_tei_reranker.py` — mocked HTTP responses
- `tests/reranking/test_factory.py` — provider selection logic

### Integration tests

- CI job with TEI container + small cross-encoder (ms-marco-MiniLM-L-12-v2)
- Existing `LiteLLMReranker` tests unchanged

### Manual testing

- Each compose file boots and reaches healthy state
- Recall query with reranking enabled returns reranked results
- Recall query with reranking disabled returns cosine-ordered results

## Documentation

### Updates needed

- `docker/README.md` — tier comparison table, RAM requirements
- `docs/self-hosted/standalone.md` — setup guide, model pull times, GPU notes
- Tier limitation callouts: "lite = English-focused, no reranker"

## Migration

No migration needed. New tiers are additive. Existing selfhosted users unaffected.

## Rollout

1. Implement TEIReranker + factory (context-service)
2. Update/add compose files (context-service)
3. Add standalone tiers to models.yaml (context-service)
4. Build and push images (CI/CD)
5. Update installer with standalone wizard (mcp-client)
6. Documentation updates
7. Announce in release notes

## Open Questions

None — all questions resolved during design.

## References

- [TEI Rerank Documentation](https://huggingface.co/docs/text-embeddings-inference/en/quick_tour)
- [BGE Reranker v2 m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- [Jina Reranker v2](https://jina.ai/models/jina-reranker-v2-base-multilingual/)
- [Nomic Embed Text](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5)
- [Gemma 4 Ollama](https://ollama.com/library/gemma4)
