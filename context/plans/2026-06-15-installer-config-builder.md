# Installer Config Builder

**Date:** 2026-06-15
**Status:** Spec draft
**Target:** Next installer release

## Problem

The current installer has a rigid tier-based model that doesn't support mix-and-match configurations:

1. **Standalone tiers** (Lite/Standard/Pro) bundle Ollama + TEI with no flexibility
2. **Cloud tier** asks for embedding provider but not LLM provider
3. No reranker choice for cloud users (requires TEI which defeats "cloud" purpose)
4. Generated `models.yaml` was broken (everything commented out, wrong field name)

## Bugs Found During Troubleshooting

### Fixed in this session:

| Bug | Root Cause | Fix |
|-----|------------|-----|
| `models.yaml` all commented out | Static template copy, no generation | Added `generate_models_yaml()` function |
| `default_tier:` field name | Generated YAML used wrong key | Changed to `tier:` (matches schema) |
| `just ship-beta` wrong paths | `deploy.just` had stale `deploy/cloudbuild/` paths | Updated to `docker/cloudbuild-app.yaml` with substitutions |

### Known issues (not yet fixed):

| Issue | Impact | Status |
|-------|--------|--------|
| Dagster `teardown_after_execution` Pydantic error | Dagster webserver warning (not blocking) | Investigate Dagster/Pydantic compat |
| SAGE passive mode despite OpenAI key | `.env` has key but SAGE doesn't detect for reasoning | Check if models.yaml reasoning provider is read |
| Qdrant hybrid mismatch warning | Collection created without hybrid mode | Recreate collection or ignore |

## Proposed Solution: Config Builder

Replace tier selection with component-by-component configuration.

### New Wizard Flow

```
Step 1: Container Runtime
  → Docker / Podman (existing)

Step 2: LLM Provider
  → OpenAI (needs OPENAI_API_KEY)
  → Anthropic (needs ANTHROPIC_API_KEY)  
  → Vertex AI (needs GCP project + ADC)
  → Ollama (local, needs RAM based on model)
  → Other (manual litellm config)

Step 3: Embedding Provider
  → OpenAI (text-embedding-3-small/large)
  → Vertex AI (text-embedding-005, gemini-embedding-001)
  → Ollama (nomic-embed-text, mxbai-embed-large, etc.)
  → TEI (local, ~700MB, bundled with compose)
  → Other (manual)

Step 4: Reranker (optional)
  → Cohere (COHERE_API_KEY, best quality)
  → Vertex AI (semantic-ranker, needs GCP)
  → TEI (local, ~1GB, bundled)
  → None (disable reranking channel)

Step 5: License
  (existing)

Step 6: Credentials
  (collect only what's needed based on Steps 2-4)
  Show summary: "Your setup needs: OPENAI_API_KEY, COHERE_API_KEY"

Step 7: Configuration
  (ports, install dir, postgres password - existing)

Step 8: Install
  (generate files, start services)
```

### Generated Files

Based on user selections, dynamically generate:

**docker-compose.yml** - Include only required services:

| Service | When included |
|---------|---------------|
| postgres, redis, qdrant, memgraph | Always |
| app, dagster, dagster-daemon, reaction-worker | Always |
| ollama | LLM = Ollama OR Embeddings = Ollama |
| tei (embedder) | Embeddings = TEI |
| tei-reranker | Reranker = TEI |

**config/models.yaml** - Full tier config from selections:

```yaml
tier: self_hosted

tiers:
  self_hosted:
    embeddings:
      provider: {selected_embedding_provider}
      model: {selected_embedding_model}
      dimensions: {auto_or_user}
    reasoning:
      provider: {selected_llm_provider}
      model: {selected_reasoning_model}
    fast:
      provider: {selected_llm_provider}
      model: {selected_fast_model}
    reranker:  # null if None selected
      provider: {selected_reranker_provider}
      model: {selected_reranker_model}
    query_expander:
      provider: {selected_llm_provider}
      model: {selected_fast_model}
```

**.env** - Only relevant credentials:

```bash
# Always
ENGRAMMIC_LICENSE_KEY=...
POSTGRES_PASSWORD=...
ENGRAMMIC_CONFIG_DIR=/app/config-override

# Conditional
OPENAI_API_KEY=...       # if OpenAI selected for anything
ANTHROPIC_API_KEY=...    # if Anthropic selected
COHERE_API_KEY=...       # if Cohere reranker
OLLAMA_BASE_URL=...      # if external Ollama
```

### Implementation

**Files to change:**

| File | Change |
|------|--------|
| `selfhost.rs` | New wizard steps, component selection logic |
| `docker.rs` | Dynamic compose builder (base + service snippets) |
| `assets/` | Service snippet templates instead of full compose files |
| Test existing `generate_models_yaml()` | Already partially implemented |

**Estimated effort:** 1-2 days

### Presets (Optional UX Enhancement)

For users who want quick setup, offer presets that map to component selections:

```
Quick Setup (presets):
  → Cloud (OpenAI everything) - fastest, paid APIs
  → Hybrid (Ollama LLM + OpenAI embeddings) - local inference, cloud embeddings
  → Local (Ollama + TEI) - fully offline, needs GPU
  → Custom (pick each component)
```

Selecting a preset pre-fills Steps 2-4, user can still go back and change.

## Testing

1. Cloud (OpenAI LLM + embeddings, no rerank) - no TEI/Ollama containers
2. Hybrid (Ollama LLM + OpenAI embeddings + Cohere rerank) - Ollama only
3. Local (Ollama + TEI + TEI rerank) - full stack
4. External Ollama detection still works
5. Podman mode still works
6. Reconfigure mode preserves user selections

## Migration

None needed - installer generates fresh configs. Existing users can reconfigure.

---

## Comprehensive Audit Findings (6-agent review)

### 1. models.yaml Schema (Agent 1)

**Structure requirements:**
- `tier:` (not `default_tier:`) - one of 9 allowed literals
- `tiers:` dict is REQUIRED, each tier needs `embeddings`, `reasoning`, `fast` (required), `reranker`, `query_expander` (optional)
- `sparse:` optional (defaults to fastembed BM25)

**Bugs found:**
| Issue | Severity | Fix |
|-------|----------|-----|
| `gemini-3.5-flash` model doesn't exist (economy tier) | High | Change to `gemini-2.5-flash` |
| `embedding_dimensions` defaults to 2048 when unset | Note | Document or make explicit |
| `get_model()` silently falls back to `fast` on unknown task | Low | Add warning log |

### 2. Installer .env Generation (Agent 2)

**Bugs found:**
| Issue | Severity | Fix |
|-------|----------|-----|
| `MODEL_TIER` missing for Cloud tier | Medium | Add `MODEL_TIER=self_hosted` explicitly |
| `OLLAMA_HOST` written but not recognized | Medium | Change to `OLLAMA_BASE_URL` |
| `RERANKING__ENABLED=false` missing for Lite | High | Add to Lite compose or .env |
| OpenAI key commented for LLM-only use | Low | UX gap, needs manual uncomment |

**Env var status by tier:**
| Var | Cloud | Standalone |
|-----|-------|------------|
| `MODEL_TIER` | Missing (relies on models.yaml) | In compose env |
| `EMBEDDING_MODEL` | Written correctly | Not in .env (in compose) |
| `RERANKING__ENABLED` | Commented | Commented (Lite needs false) |

### 3. Compose Generation (Agent 3)

**Critical bugs:**
| Issue | Severity | Impact |
|-------|----------|--------|
| Standalone tiers missing `reaction-worker` | High | Async reactions won't process |
| Standalone tiers missing `dagster-daemon` | High | SAGE scheduled jobs won't run |
| Lite tier TEI model mismatch | Medium | Uses older bge-base vs nomic-embed |

**Service matrix:**
| Service | Cloud | Lite | Standard | Pro |
|---------|-------|------|----------|-----|
| reaction-worker | Yes | **NO** | **NO** | **NO** |
| dagster-daemon | Yes | **NO** | **NO** | **NO** |
| tei-reranker | No | **NO** | Yes | Yes |

### 4. Config Validation (Agent 4)

**Validation gaps:**
| Gap | Severity | Affected |
|-----|----------|----------|
| No vLLM URL check | High | self_hosted, self_hosted_budget tiers |
| No OpenAI/Anthropic API key check | Medium | Any tier with cloud provider override |
| `fast` model provider not validated | Medium | Mixed-provider tiers |
| TEI not checked for reranker-only configs | Low | standalone_standard, standalone_pro |

**Recommendations:**
- Add vLLM URL validation
- Validate API keys for all configured providers
- Check all model slots, not just reasoning/embeddings

### 5. Settings Integration (Agent 5)

**Config precedence (highest to lowest):**
1. `MODEL_TIER` env var (wins over `MODELS__TIER`)
2. `MODELS__TIER` env var
3. `tier:` in models.yaml
4. Default: `balanced`

**Edge cases:**
| Issue | Impact |
|-------|--------|
| `ENGRAMMIC_CONFIG_DIR` replaces whole file, no merge | Operators must provide complete config |
| `embedding_dimensions` exists in both Settings and ModelsConfig | Can diverge if only one is set |
| `Org.default_llm` column is dead weight | Docstring claims per-org override but not implemented |

### 6. Self-hosted vs Managed (Agent 6)

**Detection:**
- `ENGRAMMIC_DEPLOYMENT_TYPE=selfhosted` (in Dockerfile) gates license validation
- `ENVIRONMENT=self-hosted` (in compose) only controls log format

**Dead code:**
| Env Var | Status |
|---------|--------|
| `LICENSE_VALIDATION_ENABLED` | Set in all compose files, **never read by Python** |

**SAGE passive mode issues:**
- Triggered when `settings.llm.api_key` is None
- Only advisory - logs warning + health endpoint shows `sage_mode: passive`
- **Does NOT disable Dagster jobs** - custodian/synthesizer will still attempt LLM calls and fail

**Confusing env vars:**
| Var | Purpose |
|-----|---------|
| `ENVIRONMENT=self-hosted` | Log format, Swagger visibility |
| `ENGRAMMIC_DEPLOYMENT_TYPE=selfhosted` | License gating |

---

## Healthcheck Issue

**Problem:** App container exits with code 137 (SIGKILL) during startup.

**Root cause:** `start_period: 15s` but app takes ~22s to start. Health check fails before uvicorn binds.

**Fix:** Increase `start_period` to 60s in compose templates:
```yaml
healthcheck:
  start_period: 60s  # was 15s
```

---

## Priority Fixes

### P0 (Blocking) - Installer/Compose

| # | Issue | File(s) | Status |
|---|-------|---------|--------|
| 1 | Add `reaction-worker` and `dagster-daemon` to standalone composes | `assets/docker-compose.{lite,standard,pro}.yml` | DONE |
| 2 | Increase healthcheck `start_period` to 60s | `assets/docker-compose.*.yml` | DONE |
| 3 | Fix `gemini-3.5-flash` → `gemini-2.5-flash` | `context-service/config/models.yaml` | DONE |
| 4 | Add `RERANKING__ENABLED=false` to Lite tier | `assets/docker-compose.lite.yml` | DONE |
| 5 | Remove dead `LICENSE_VALIDATION_ENABLED` | All compose templates | DONE |

### P1 (Important) - Installer/Config

| # | Issue | File(s) |
|---|-------|---------|
| 5 | Add `MODEL_TIER=self_hosted` to Cloud tier .env | `selfhost.rs generate_env()` |
| 6 | Fix `OLLAMA_HOST` → `OLLAMA_BASE_URL` | `selfhost.rs` line 2138 |
| 7 | Remove dead `LICENSE_VALIDATION_ENABLED` | All compose templates |
| 8 | Add vLLM URL validation | `context-service/config/validation.py` |
| 9 | Fix SAGE passive mode to disable Dagster jobs | `context-service/license/startup.py` |

### P2 (Cleanup/Docs)

| # | Issue |
|---|-------|
| 10 | Consolidate `ENVIRONMENT` vs `ENGRAMMIC_DEPLOYMENT_TYPE` |
| 11 | Add API key validation for all providers |
| 12 | Fix docs: remove "Cloud" tier, fix `vertex` → `vertex_ai` |
| 13 | Fix docs: update `EMBEDDING_DIMENSIONS` default to 2048 |
| 14 | Fix docs: remove phantom `embeddings.yaml` reference |
| 15 | Add OpenAI/Anthropic cloud-only example to docs |

---

## Documentation Gaps

### Installer CLI Docs (Agent 7)

**Missing entirely:**
| Gap | Impact |
|-----|--------|
| Subcommand reference (14 commands) | Users don't know what `doctor`, `scale`, `status` do |
| Self-hosted tier requirements | No written reference for Lite/Standard/Pro/Cloud specs |
| `models.yaml` format | Points to docs.engrammic.ai that may not exist |
| Podman support | Only in generated README, not public docs |

**Incomplete:**
- `TROUBLESHOOTING.md` has only 3 scenarios (needs license errors, OOM, port conflicts)
- `remove` vs `uninstall` distinction not explained
- `engrammic upgrade` not documented
- Reranking provider options not listed
- Skills path format per harness not explained

### Self-hosted Docs (Agent 8)

**HIGH severity:**
| Issue | Fix |
|-------|-----|
| "Cloud" listed as tier name but doesn't exist | Remove, use valid tier names |
| Pro tier says `jina-reranker` but uses `bge-reranker-v2-m3` | Fix to match models.yaml |
| Provider `vertex` should be `vertex_ai` | Update all docs |
| `EMBEDDING_MODEL` env var has no effect | Remove or caveat |
| `embeddings.yaml` listed but doesn't exist | Remove from config-files table |

**MEDIUM severity:**
| Issue | Fix |
|-------|-----|
| `EMBEDDING_DIMENSIONS` default wrong (768 vs 2048) | Update to 2048 |
| No OpenAI/Anthropic cloud-only example | Add end-to-end example |

**LOW severity:**
- `MODELS__OVERRIDES__*` pattern undocumented
- `MODEL_TIER` alias undocumented

### Config Reference Docs (Agent 9)

**Outdated documentation:**
| Issue | Current State | Fix |
|-------|---------------|-----|
| Tier list | Only lists economy/balanced/premium | Add 7 missing tiers |
| `EMBEDDING_DIMENSIONS` default | Says 768 | Should be 2048 |
| `self-hosted/models.mdx` | Stale draft with OpenAI defaults | Retire or rewrite |

**Missing from docs:**
| Variable/Feature | Why needed |
|------------------|------------|
| `TEI_URL` / `RERANKER_URL` | Required for standalone/hybrid tiers |
| `OLLAMA_URL` unified alias | Works for both LLM and embeddings |
| `GOOGLE_APPLICATION_CREDENTIALS` | SA JSON alternative to gcloud mount |
| `MODEL_TIER` alias | Accepted alongside `MODELS__TIER` |
| `MODELS__OVERRIDES__*` pattern | Shown in .env but not documented |
| `reranker` role in tier schema | Needed for standalone_standard/pro |
| Config dir fallthrough behavior | Users don't know partial overrides work |

---

## Next Steps

1. **Immediate fixes** (can do now):
   - Fix `gemini-3.5-flash` in bundled models.yaml
   - Increase healthcheck `start_period` in all compose templates
   - Add `reaction-worker` and `dagster-daemon` to standalone composes

2. **Config builder implementation** (1-2 days):
   - New wizard flow with component selection
   - Dynamic compose generation
   - Dynamic models.yaml generation

3. **Documentation sprint**:
   - Write subcommand reference
   - Document tier requirements
   - Document models.yaml schema
   - Update troubleshooting guide
