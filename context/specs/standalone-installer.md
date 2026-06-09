# Standalone Installer Specification

## Overview

Enable self-hosted users to install Engrammic with local LLM/embedding infrastructure via tiered standalone bundles. Each tier bundles different model configurations optimized for different hardware profiles.

## Tiers

| Tier | RAM | LLM (Ollama) | Embeddings (TEI) | Reranker (TEI) | Use Case |
|------|-----|--------------|------------------|----------------|----------|
| **Lite** | 8GB | phi4-mini | nomic-embed-text-v1.5 (768d) | None | Laptops, dev machines |
| **Standard** | 24-32GB | gemma4:12b | nomic-embed-text-v2-moe (768d) | bge-reranker-v2-m3 | Workstations |
| **Pro** | 48-64GB | gemma4:26b | nomic-embed-text-v2-moe (768d) | jina-reranker-v2-base | Servers, production |

All tiers use Ollama for LLM and TEI for embeddings. Standard and Pro add TEI reranker.

## Distribution Channels

### 1. Installer CLI (Primary)

Interactive wizard with tier selection:

```
$ engrammic selfhost

  Engrammic Self-Hosted Setup
  
  Step 1/6: Hardware Profile
  
  Select a tier based on your available RAM:
  
  > Lite     (8GB)   - phi4-mini, basic embeddings
    Standard (24GB)  - gemma4:12b + reranker
    Pro      (48GB+) - gemma4:26b + advanced reranker
```

Non-interactive mode:

```bash
engrammic selfhost --tier=lite --license=ENGR_xxx
engrammic selfhost --tier=standard --yes
```

### 2. GitHub Releases (Secondary)

For users who prefer curl/wget without installing the CLI:

```bash
# Download and extract
curl -sL https://github.com/engrammic-ai/engrammic/releases/download/v0.4.0/standalone-lite-v0.4.0.tar.gz | tar xz
cd standalone-lite

# Configure
cp .env.example .env
# Edit .env with license key

# Start
docker compose up -d
```

Each release bundle contains:
- `docker-compose.yml` - tier-specific compose
- `.env.example` - env template
- `config/models.yaml` - model configuration
- `README.md` - quickstart guide

## Installer CLI Changes

### New: Tier Selection

Add to `selfhost.rs`:

```rust
#[derive(Debug, Clone, Copy)]
pub enum Tier {
    Lite,
    Standard,
    Pro,
}

impl Tier {
    pub fn ram_requirement(&self) -> &'static str {
        match self {
            Tier::Lite => "8GB",
            Tier::Standard => "24-32GB", 
            Tier::Pro => "48-64GB",
        }
    }
    
    pub fn compose_template(&self) -> &'static str {
        match self {
            Tier::Lite => include_str!("../assets/docker-compose.lite.yml"),
            Tier::Standard => include_str!("../assets/docker-compose.standard.yml"),
            Tier::Pro => include_str!("../assets/docker-compose.pro.yml"),
        }
    }
}
```

### New: CLI Flags

Add to `cli.rs`:

```rust
#[derive(Parser)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
    
    /// Tier for selfhost (lite, standard, pro)
    #[arg(long)]
    pub tier: Option<String>,
    
    // ... existing flags
}
```

### Modified: Wizard Flow

```
Step 1/6: Hardware Profile     <- NEW
Step 2/6: Prerequisites        (existing)
Step 3/6: License              (existing)
Step 4/6: Configuration        (existing, skip embedding prompts for standalone)
Step 5/6: Model Download       <- NEW (ollama pull)
Step 6/6: Start                (existing)
```

### New: Model Download Step

```rust
fn download_models(tier: Tier) -> Result<()> {
    // Only pull Ollama LLM model - TEI embeddings download automatically
    let model = match tier {
        Tier::Lite => "phi4-mini",
        Tier::Standard => "gemma4:12b",
        Tier::Pro => "gemma4:26b",
    };
    
    println!("Downloading models (this may take a while)...");
    for model in models {
        Command::new("docker")
            .args(["exec", "engrammic-ollama", "ollama", "pull", model])
            .status()?;
    }
    Ok(())
}
```

## Compose Templates

### Lite (`docker-compose.lite.yml`)

```yaml
services:
  app:
    image: europe-north1-docker.pkg.dev/engrammic/releases/engrammic-api:latest
    environment:
      - LLM_PROVIDER=ollama
      - DEFAULT_LLM_MODEL=phi4-mini
      - EMBEDDING_PROVIDER=tei
      - TEI_URL=http://tei:8080
      - EMBEDDING_DIMENSIONS=768
    
  ollama:
    image: ollama/ollama:latest
    deploy:
      resources:
        limits:
          memory: 4G
          
  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
    command: ["--model-id", "nomic-ai/nomic-embed-text-v1.5"]
          
  # No TEI reranker
  # Standard infra (memgraph, qdrant, redis, postgres)
```

### Standard (`docker-compose.standard.yml`)

```yaml
services:
  app:
    image: europe-north1-docker.pkg.dev/engrammic/releases/engrammic-api:latest
    environment:
      - LLM_PROVIDER=ollama
      - DEFAULT_LLM_MODEL=gemma4:12b
      - EMBEDDING_PROVIDER=tei
      - TEI_URL=http://tei:8080
      - EMBEDDING_DIMENSIONS=768
      - TEI_RERANKER_URL=http://tei-reranker:8080
      
  ollama:
    image: ollama/ollama:latest
    deploy:
      resources:
        limits:
          memory: 8G
          
  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
    command: ["--model-id", "nomic-ai/nomic-embed-text-v2-moe"]
    
  tei-reranker:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
    command: ["--model-id", "BAAI/bge-reranker-v2-m3"]
    
  # Standard infra
```

### Pro (`docker-compose.pro.yml`)

```yaml
services:
  app:
    image: europe-north1-docker.pkg.dev/engrammic/releases/engrammic-api:latest
    environment:
      - LLM_PROVIDER=ollama
      - DEFAULT_LLM_MODEL=gemma4:26b
      - EMBEDDING_PROVIDER=tei
      - TEI_URL=http://tei:8080
      - EMBEDDING_DIMENSIONS=768
      - TEI_RERANKER_URL=http://tei-reranker:8080
      
  ollama:
    image: ollama/ollama:latest
    deploy:
      resources:
        limits:
          memory: 20G
          
  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
    command: ["--model-id", "nomic-ai/nomic-embed-text-v2-moe"]
    
  tei-reranker:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
    command: ["--model-id", "jinaai/jina-reranker-v2-base-multilingual"]
    
  # Standard infra
```

## GitHub Releases Workflow

Add to `publish-selfhosted.yml`:

```yaml
create-standalone-bundles:
  needs: [build-selfhosted-api, build-selfhosted-dagster]
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    
    - name: Create bundles
      run: |
        VERSION=${{ needs.build-selfhosted-api.outputs.version }}
        
        for tier in lite standard pro; do
          mkdir -p standalone-${tier}
          cp docker/docker-compose.standalone-${tier}.yml standalone-${tier}/docker-compose.yml
          cp docker/standalone-${tier}.env.example standalone-${tier}/.env.example
          cp -r config standalone-${tier}/
          # Generate README
          cat > standalone-${tier}/README.md << 'EOF'
        # Engrammic Standalone (${tier})
        
        ## Quick Start
        
        1. Copy .env.example to .env and add your license key
        2. Run: docker compose up -d
        3. Wait for models to download (first run only)
        
        See https://docs.engrammic.ai/selfhosted for full documentation.
        EOF
          
          tar -czf standalone-${tier}-v${VERSION}.tar.gz standalone-${tier}
        done
    
    - name: Create GitHub Release
      uses: softprops/action-gh-release@v1
      with:
        files: |
          standalone-lite-v*.tar.gz
          standalone-standard-v*.tar.gz
          standalone-pro-v*.tar.gz
        generate_release_notes: true
```

## User Experience

### Interactive Flow

```
$ engrammic selfhost

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Engrammic Self-Hosted Setup
  Memory infrastructure for AI agents

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1/6: Hardware Profile

  Your system: 32 GB RAM detected

  > Pro      (48GB+) - gemma4:26b + jina-reranker-v2 (Recommended)
    Standard (24GB)  - gemma4:12b + bge-reranker-v2
    Lite     (8GB)   - phi4-mini, no reranker
    Cloud    (any)   - Use cloud APIs (OpenAI, Anthropic, etc.)

Step 2/6: Prerequisites

  Checking Docker... ok
  Checking Docker Compose... ok (v2.27.0)
  Checking disk space... ok (50 GB free)

Step 3/6: License

  License key: ENGR_xxx
  ✓ Valid - Acme Corp, 89 days remaining

Step 4/6: Configuration

  Install directory: ~/.engrammic
  MCP port: 8000
  Dagster port: 3000

Step 5/6: Model Download

  Pulling gemma4:26b... (15 GB)
  [████████████████░░░░] 80% - 2m remaining
  ✓ Complete
  
  (TEI embeddings download automatically on first container start)

Step 6/6: Start

  Starting services...
  ✓ All services healthy

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Setup complete!

  MCP endpoint: http://localhost:8000/mcp
  
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Non-Interactive

```bash
# CI/automation
engrammic selfhost \
  --tier=standard \
  --license=ENGR_xxx \
  --port=9000 \
  --yes

# Outputs:
# ✓ Tier: Standard
# ✓ License validated
# ✓ Config written to ~/.engrammic
# ✓ Models downloaded
# ✓ Services started
# 
# MCP endpoint: http://localhost:9000/mcp
```

## Migration Path

Existing selfhost users (cloud API tier):
- No changes required
- `engrammic selfhost` without `--tier` defaults to cloud API flow (current behavior)
- Add "Cloud" as a tier option in the wizard for clarity

## Success Metrics

- Time to first memory stored < 10 minutes (including model download on fast connection)
- Zero external API calls required for Lite/Standard/Pro tiers
- Works offline after initial model download
