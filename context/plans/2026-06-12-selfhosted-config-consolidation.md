# Selfhosted Config Consolidation

**Date:** 2026-06-12  
**Status:** Ready for implementation  
**Target:** Monday release

## Problem

Selfhosted config is confusing for users who don't follow our exact setup:

1. **Dual config sources** — `models.yaml` and `embeddings.yaml` can conflict
2. **Legacy env vars** — `LITELLM_EMBEDDING_MODEL`, `EMBEDDING_PROVIDER` in settings.py but superseded by tier system
3. **Ollama URL inconsistency** — `OLLAMA_BASE_URL` (LLM) vs `OLLAMA_API_BASE` (embeddings)
4. **Vertex defaults** — Users without GCP creds get cryptic ADC errors
5. **No example files** — Selfhosted compose mounts `./config/` but no examples ship

## Solution

Tier-centric consolidation: `models.yaml` becomes the single source of truth. Tiers are immutable presets; users override at top-level.

## Design

### 1. Config Consolidation

**Delete:**
- `config/embeddings.yaml` — no longer a config source

**Modify `config/models.yaml`:**

Add top-level `sparse` section (BM25 via fastembed, separate from SPLADE):
```yaml
sparse:
  enabled: true
  provider: fastembed
  model: Qdrant/bm25

# Also add embedding dimensions at top level (was in embeddings.yaml)
embedding_dimensions: 768  # override per-tier default if needed
qdrant_collection: context_vectors
```

Tiers remain immutable presets. User overrides at top-level:
```yaml
tier: standalone_lite

overrides:
  reasoning:
    model: llama3.3:70b
```

**Add to `config/models.py`:**

```python
class SparseConfig(BaseModel):
    """BM25 sparse encoder config (fastembed-based, not SPLADE)."""
    model_config = ConfigDict(frozen=True)
    
    enabled: bool = True
    provider: Literal["fastembed"] = "fastembed"
    model: str = "Qdrant/bm25"


class ModelsConfig(BaseModel):
    # ... existing fields ...
    sparse: SparseConfig = Field(default_factory=SparseConfig)
    embedding_dimensions: int | None = None  # override tier default
    qdrant_collection: str = "context_vectors"
```

**Update all `load_config("embeddings")` callsites:**

| File | Current | Change |
|------|---------|--------|
| `embeddings/__init__.py:49` | `load_config("embeddings")` | `settings.models` |
| `embeddings/litellm_embeddings.py:123` | `load_config("embeddings")` | `settings.models` |
| `stores/qdrant.py:101` | `load_config("embeddings")` | `settings.models` |
| `api/app.py:188` | `load_config("embeddings")` | `settings.models` |
| `reactions/worker.py:243` | `load_config("embeddings")` | `settings.models` |
| `pipelines/resources.py:218` | `load_config("embeddings")["dimensions"]` | `settings.models.embedding_dimensions` |
| `startup/model_check.py:51` | `load_config("embeddings")` | `settings.models` |

### 2. Env Var Cleanup

**Remove from `settings.py`:**
- `litellm_embedding_model: str` (line 1219) — superseded by tier system
- `embedding_provider: str` (line 1226) — superseded by tier system

**Remove from `.env.example`:**
- `LLM_MODEL` (never wired)
- `LLM_API_KEY` (never wired)
- `LITELLM_EMBEDDING_MODEL` (removing from settings.py)
- `EMBEDDING_PROVIDER` (removing from settings.py)

**Ollama URL unification:**

Replace the existing `ollama_base_url` field with a computed property that reads from multiple env vars:

```python
# In settings.py - REMOVE this field:
# ollama_base_url: str = Field(default="http://localhost:11434")

# ADD computed property:
@computed_field
@property
def ollama_url(self) -> str:
    """Canonical Ollama URL. Reads from OLLAMA_URL, OLLAMA_BASE_URL, or OLLAMA_API_BASE."""
    return (
        os.environ.get("OLLAMA_URL")
        or os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_API_BASE")
        or "http://localhost:11434"
    )

# Aliases for litellm conventions
@property
def ollama_base_url(self) -> str:
    """Alias for ollama_url (litellm LLM convention)."""
    return self.ollama_url

@property
def ollama_api_base(self) -> str:
    """Alias for ollama_url (litellm embeddings convention)."""
    return self.ollama_url
```

### 3. Startup Validation

New `config/validation.py`:

```python
import os
from context_service.config.logging import get_logger
from context_service.config.settings import get_settings

logger = get_logger(__name__)


class ConfigurationError(Exception):
    """Raised when config validation fails."""


def _has_adc() -> bool:
    """Check if Application Default Credentials are available."""
    try:
        import google.auth
        google.auth.default()
        return True
    except Exception:
        return False


def validate_config() -> None:
    """Validate config at startup. Fail fast with actionable errors."""
    settings = get_settings()
    tier = settings.models.tier
    active = settings.models.tiers[tier]
    errors: list[str] = []
    warnings: list[str] = []
    
    # Warn on legacy/dead env vars
    legacy_vars = {
        "LLM_MODEL": "Use MODELS__TIER or MODELS__OVERRIDES__REASONING__MODEL",
        "LLM_API_KEY": "Use provider-specific key (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)",
        "LITELLM_EMBEDDING_MODEL": "Use MODELS__TIER to select embedding model",
        "EMBEDDING_PROVIDER": "Use MODELS__TIER to select embedding provider",
    }
    for var, hint in legacy_vars.items():
        if os.environ.get(var):
            warnings.append(f"{var} is set but unused. {hint}")
    
    # Validate provider requirements
    if active.embeddings.provider == "tei" and not settings.tei_url:
        errors.append("Tier uses TEI embeddings but TEI_URL is not set")
    
    if active.reasoning.provider == "ollama":
        if not any(os.environ.get(v) for v in ["OLLAMA_URL", "OLLAMA_BASE_URL", "OLLAMA_API_BASE"]):
            errors.append("Tier uses Ollama but no OLLAMA_URL/OLLAMA_BASE_URL set")
    
    if active.reasoning.provider == "vertex_ai":
        has_project = settings.vertex_project or settings.vertex_project_id
        if not (has_project or _has_adc()):
            errors.append("Tier uses Vertex AI but no VERTEX_PROJECT or ADC credentials found")
    
    if active.embeddings.provider == "vertex_ai":
        has_project = settings.vertex_project or settings.vertex_project_id
        if not (has_project or _has_adc()):
            errors.append("Tier uses Vertex AI embeddings but no VERTEX_PROJECT or ADC credentials found")
    
    # Log warnings
    for w in warnings:
        logger.warning("config_warning", msg=w)
    
    # Fail on errors
    if errors:
        msg = "Config validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.error("config_validation_failed", errors=errors)
        raise ConfigurationError(msg)
    
    logger.info("config_validated", tier=tier)
```

**Call from `entrypoint.py`:**

```python
# Near the top, after settings load but before server start
from context_service.config.validation import validate_config

def main():
    validate_config()  # Fail fast
    # ... rest of startup
```

### 4. Example Files

**New `docker/selfhosted.env.ollama.example`:**
```bash
# Selfhosted with local Ollama + TEI
# Copy to .env and customize

POSTGRES_PASSWORD=changeme

# Pick a tier (standalone_lite, standalone_standard, standalone_pro)
MODELS__TIER=standalone_lite

# Local LLM endpoints (set one of these)
OLLAMA_URL=http://ollama:11434
TEI_URL=http://tei:8080

# Optional: override specific models
# MODELS__OVERRIDES__REASONING__MODEL=llama3.3:70b
```

**New `docker/selfhosted.env.vertex.example`:**
```bash
# Selfhosted with Vertex AI
# Copy to .env and customize

POSTGRES_PASSWORD=changeme

# Pick a tier (economy, balanced, premium)
MODELS__TIER=balanced

# Vertex AI (requires ADC or service account)
VERTEX_PROJECT=my-project
VERTEX_LOCATION=us-central1
# Or mount service account JSON and set:
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
```

**Update `docker/docker-compose.selfhosted.yml`:**
```yaml
# Engrammic Self-Hosted
#
# Quick start:
#   1. Copy selfhosted.env.ollama.example or selfhosted.env.vertex.example to .env
#   2. Edit .env with your settings
#   3. docker compose -f docker-compose.selfhosted.yml up -d
#
# For local LLMs (Ollama + TEI), you'll also need to run those services.
# See standalone-lite.yml for a batteries-included local setup.
```

**Update `.env.example`:**
- Remove legacy vars
- Add `OLLAMA_URL` with comment
- Add section header pointing to models.yaml for LLM config

## Files Changed

| File | Change |
|------|--------|
| `config/embeddings.yaml` | DELETE |
| `config/models.yaml` | Add `sparse`, `embedding_dimensions`, `qdrant_collection` |
| `src/context_service/config/models.py` | Add `SparseConfig`, new fields to `ModelsConfig` |
| `src/context_service/config/settings.py` | Remove `ollama_base_url` field, `litellm_embedding_model`, `embedding_provider`; add `ollama_url` computed property with aliases |
| `src/context_service/config/validation.py` | NEW — startup validation |
| `src/context_service/entrypoint.py` | Call `validate_config()` |
| `src/context_service/embeddings/__init__.py` | Use `settings.models`, not `load_config("embeddings")` |
| `src/context_service/embeddings/litellm_embeddings.py` | Use `settings.models` |
| `src/context_service/stores/qdrant.py` | Use `settings.models` |
| `src/context_service/api/app.py` | Use `settings.models` |
| `src/context_service/reactions/worker.py` | Use `settings.models` |
| `src/context_service/pipelines/resources.py` | Use `settings.models.embedding_dimensions` |
| `src/context_service/startup/model_check.py` | Use `settings.models` |
| `.env.example` | Remove legacy vars, add OLLAMA_URL |
| `docker/selfhosted.env.ollama.example` | NEW |
| `docker/selfhosted.env.vertex.example` | NEW |
| `docker/docker-compose.selfhosted.yml` | Update header comments |

## Testing

1. Selfhosted with `MODELS__TIER=standalone_lite` + `OLLAMA_URL` boots without errors
2. Selfhosted with `MODELS__TIER=balanced` + Vertex ADC boots
3. Legacy env var (`LLM_MODEL`) triggers warning in logs
4. Missing `TEI_URL` with TEI tier triggers clear error at startup (not runtime)
5. Missing `OLLAMA_URL` with Ollama tier triggers clear error at startup
6. Existing standalone compose files (standalone-lite.yml, etc.) still work
7. `just check` passes (mypy, ruff)
8. `just test` passes

## Migration

None required — no existing selfhosted users. Hard break is acceptable.

## Notes

- **SPLADE vs BM25:** The `sparse` config is for BM25 via fastembed. SPLADE is a separate encoder with its own `SpladeConfig` in settings.py. They coexist; this change only affects BM25 config location.
- **Embedding dimensions:** Tier defines default dimensions, but `embedding_dimensions` at top-level overrides. Changing dimensions requires Qdrant collection recreation.
