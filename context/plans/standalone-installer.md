# Standalone Installer Implementation Plan

**Spec:** `context/specs/standalone-installer.md` (needs sync after this plan is approved)  
**Repos:** `mcp-client` (installer CLI), `context-service` (compose templates, workflow)

## Current State

Compose files exist but have inconsistencies with spec and models.yaml. This plan fixes them first.

## Tier Summary (Corrected)

| Tier | RAM | LLM | Embeddings | Reranker |
|------|-----|-----|------------|----------|
| **Lite** | 8GB | phi4-mini (Ollama) | nomic-embed-text-v1.5 (TEI, 768d) | None |
| **Standard** | 24-32GB | gemma4:12b (Ollama) | nomic-embed-text-v2-moe (TEI, 768d) | bge-reranker-v2-m3 (TEI) |
| **Pro** | 48-64GB | gemma4:26b (Ollama) | nomic-embed-text-v2-moe (TEI, 768d) | jina-reranker-v2-base (TEI) |

All tiers use TEI for embeddings (not Ollama). Standard/Pro add TEI reranker.

---

## Phase 1: Fix Compose Files (context-service)

### 1.1 Fix lite compose inconsistencies

File: `docker/docker-compose.standalone-lite.yml`

- [ ] Change `DEFAULT_LLM_MODEL=gemma4:e4b` to `phi4-mini`
- [ ] Change ollama entrypoint to pull `phi4-mini` instead of `gemma4:e4b`
- [ ] Change ollama env `OLLAMA_MODEL=gemma4:e4b` to `phi4-mini`

### 1.2 Standardize env file references

- [ ] Standard compose: change `env_file: standalone.env` to `standalone-standard.env`
- [ ] Pro compose: change `env_file: standalone.env` to `standalone-pro.env`
- [ ] Create `docker/standalone-standard.env.example` (copy from standalone.env.example)
- [ ] Create `docker/standalone-pro.env.example` (copy from standalone.env.example)

### 1.3 Fix models.yaml lite tier

File: `config/models.yaml`

The `standalone_lite` tier uses MiniLM (384d) but compose uses nomic (768d). Sync to compose:

- [ ] Change `standalone_lite.embeddings.model` to `nomic-ai/nomic-embed-text-v1.5`
- [ ] Change `standalone_lite.embeddings.dimensions` to `768`
- [ ] Change `standalone_lite.reasoning.model` to `phi4-mini`
- [ ] Change `standalone_lite.fast.model` to `phi4-mini`

### 1.4 Update compose RAM comments

- [ ] Lite: keep "8GB RAM" (correct)
- [ ] Standard: "24GB RAM minimum, 32GB recommended" (was "32GB recommended")
- [ ] Pro: "48GB RAM minimum, 64GB recommended" (was "64GB recommended")

**Estimate:** 1 hour

---

## Phase 2: Publish Workflow (context-service)

### 2.1 Add bundle job to publish-selfhosted.yml

- [ ] Add `create-standalone-bundles` job
- [ ] Create tarballs: `standalone-{lite,standard,pro}-v{VERSION}.tar.gz`
- [ ] Each contains: `docker-compose.yml`, `.env.example`, `README.md`
- [ ] Attach to GitHub Release

**Estimate:** 1 hour

---

## Phase 3: Installer CLI (mcp-client repo)

> This phase is in a different repo. Document here for reference, implement there.

### 3.1 Add Tier enum and RAM detection

```rust
pub enum Tier {
    Lite,      // 8GB+
    Standard,  // 24GB+
    Pro,       // 48GB+
    Cloud,     // Any (existing API flow)
}

fn prompt_tier() -> Result<Tier> {
    let ram = get_available_memory_gb();
    let recommended = if ram >= 48.0 { 0 }      // Pro
        else if ram >= 24.0 { 1 }               // Standard
        else if ram >= 8.0 { 2 }                // Lite
        else { 3 };                             // Cloud
    
    let tiers = vec![
        format!("Pro      (48GB+) - gemma4:26b + jina reranker{}", if recommended == 0 { " (Recommended)" } else { "" }),
        format!("Standard (24GB)  - gemma4:12b + bge reranker{}", if recommended == 1 { " (Recommended)" } else { "" }),
        format!("Lite     (8GB)   - phi4-mini{}", if recommended == 2 { " (Recommended)" } else { "" }),
        "Cloud    (any)   - Use cloud APIs".to_string(),
    ];
    
    // ...
}
```

### 3.2 Embed compose templates

Copy from context-service releases:
- `assets/docker-compose.lite.yml`
- `assets/docker-compose.standard.yml`
- `assets/docker-compose.pro.yml`

### 3.3 Model download step

Start ollama container, then `ollama pull <model>` for the tier's LLM.
TEI models download automatically on first run (no ollama pull needed).

```rust
fn download_models(tier: Tier, install_dir: &Path) -> Result<()> {
    let model = match tier {
        Tier::Lite => "phi4-mini",
        Tier::Standard => "gemma4:12b",
        Tier::Pro => "gemma4:26b",
        Tier::Cloud => return Ok(()), // no local models
    };
    
    // Start ollama, wait for ready, pull model
    // TEI models auto-download on container start
}
```

### 3.4 Update wizard flow

```
Step 1/6: Hardware Profile     <- NEW (tier selection)
Step 2/6: Prerequisites
Step 3/6: License
Step 4/6: Configuration        (simplified for standalone)
Step 5/6: Model Download       <- NEW (ollama pull only, TEI auto-downloads)
Step 6/6: Start
```

**Estimate:** 4-6 hours (in mcp-client repo)

---

## Phase 4: Manual Install Page (web/docs)

Fallback for users when installer fails. Copy-paste snippets on docs site.

### 4.1 Create manual install page

File: `web/docs/content/docs/selfhosted/manual-install.mdx`

Tabbed interface with Lite/Standard/Pro/Cloud options, each showing:
- One-liner curl script
- Expandable docker-compose.yml
- Expandable .env.example

### 4.2 One-liner install scripts

Host on `get.engrammic.ai`:
- `/lite` - downloads lite bundle, sets up directory
- `/standard` - downloads standard bundle
- `/pro` - downloads pro bundle

**Estimate:** 2 hours

---

## Phase 5: Testing

### 5.1 Validate compose files

```bash
docker compose -f docker/docker-compose.standalone-lite.yml config
docker compose -f docker/docker-compose.standalone-standard.yml config
docker compose -f docker/docker-compose.standalone-pro.yml config
```

### 5.2 Test lite tier locally

- [ ] Start with `docker compose up -d`
- [ ] Verify phi4-mini downloads
- [ ] Verify TEI embeddings work (768d vectors)
- [ ] Test MCP tools

### 5.3 CI smoke tests

- [ ] Add workflow to validate compose syntax
- [ ] Test bundle extraction

**Estimate:** 2 hours

---

## Phase 6: Documentation

- [ ] Update docs site with tier comparison (correct RAM numbers)
- [ ] Add hardware requirements page
- [ ] Update selfhost quickstart with tier selection
- [ ] Add troubleshooting for common model download issues
- [ ] Sync spec file with this plan

**Estimate:** 1 hour

---

## Task Breakdown (context-service only)

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 1 | Fix lite LLM model | docker-compose.standalone-lite.yml | Done |
| 2 | Standardize env file refs | standalone-standard.yml, standalone-pro.yml | Done |
| 3 | Create missing env examples | standalone-{standard,pro}.env.example | Done |
| 4 | Sync models.yaml lite tier | config/models.yaml | Done |
| 5 | Update RAM comments | all 3 compose files | Done |
| 6 | Add bundle workflow job | .github/workflows/publish-selfhosted.yml | Done |
| 7 | Validate compose files | - | Done |
| 8 | Test lite tier | - | Deferred (needs hardware) |

## Completed 2026-06-09

- context-service: commit 69829554
- mcp-client: commit 9d2ad38
- web: commit 7bdf80d

---

## Decisions Made

1. **Lite LLM:** `phi4-mini` (not gemma4:e4b which doesn't exist as a real model tag)
2. **Embeddings:** TEI with nomic-embed for all tiers (768d), NOT Ollama
3. **Env files:** Tier-specific (`standalone-{tier}.env`) for clarity
4. **RAM corrected:** Lite 8GB, Standard 24-32GB, Pro 48-64GB
5. **Task 1.2 from old plan removed:** models.yaml already has tiers, no need for separate files

---

## Rollout

1. Fix compose files and models.yaml (this plan Phase 1)
2. Merge to main, validate with `docker compose config`
3. Add bundle workflow (Phase 2)
4. Tag release with bundles
5. Hand off to mcp-client repo for installer CLI work (Phase 3)
6. Manual install page (Phase 4)
7. Update docs and sync spec
