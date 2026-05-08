# Partner Deployment Spec

## Goal

Single curl command deploys Engrammic for design partners. They add an LLM key, run docker compose, done.

## User Experience

```bash
curl -sSL https://get.engrammic.ai | bash
cd engrammic
# Edit engrammic.env with your LLM key
docker compose up -d
# MCP available at http://localhost:8000/mcp/
```

## Directory Structure (after install)

```
engrammic/
  docker-compose.yml    # Self-contained, pulls images
  engrammic.env         # User config (5 lines)
  .generated.env        # Auto-generated passwords (gitignored)
  data/                 # Persistent volumes
    memgraph/
    qdrant/
    postgres/
    redis/
```

## engrammic.env (user-facing)

```bash
# Engrammic Configuration
# Provide at least one LLM provider

GEMINI_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# Optional: embedding provider (defaults to Gemini if not set)
# JINA_API_KEY=

# Optional: future licensing
# LICENSE_KEY=
```

## .generated.env (auto-created by install script)

```bash
# Auto-generated - do not edit
POSTGRES_PASSWORD=<random>
MEMGRAPH_PASSWORD=<random>
REDIS_PASSWORD=<random>
INSTALL_ID=<uuid>
```

## docker-compose.yml

- Pulls pre-built image: `ghcr.io/engrammic/context-service:latest`
- All infra services (Memgraph, Qdrant, Redis, Postgres) included
- Volumes mount to ./data/ for persistence
- Internal networking, only port 8000 exposed
- Health checks on all services

## Install Script (get.engrammic.ai)

```bash
#!/bin/bash
set -e

VERSION="${ENGRAMMIC_VERSION:-latest}"
INSTALL_DIR="${ENGRAMMIC_DIR:-./engrammic}"

echo "Installing Engrammic..."

# Create directory
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Download compose and env template
curl -sSL "https://raw.githubusercontent.com/engrammic/deploy/main/docker-compose.yml" -o docker-compose.yml
curl -sSL "https://raw.githubusercontent.com/engrammic/deploy/main/engrammic.env.example" -o engrammic.env

# Generate passwords
cat > .generated.env <<EOF
POSTGRES_PASSWORD=$(openssl rand -hex 16)
MEMGRAPH_PASSWORD=$(openssl rand -hex 16)
REDIS_PASSWORD=$(openssl rand -hex 16)
INSTALL_ID=$(uuidgen || cat /proc/sys/kernel/random/uuid)
EOF

# Create data dirs
mkdir -p data/{memgraph,qdrant,postgres,redis}

echo ""
echo "Engrammic installed to $INSTALL_DIR"
echo ""
echo "Next steps:"
echo "  1. Edit engrammic.env and add your LLM API key"
echo "  2. Run: docker compose up -d"
echo "  3. Connect MCP at http://localhost:8000/mcp/"
echo ""
```

## Code Changes Needed

### 1. Config fallbacks (settings.py)

Make all infra config optional with compose-friendly defaults:

```python
# If MEMGRAPH_URI not set, construct from host/port or use default
memgraph_uri: str = Field(default="bolt://memgraph:7687")
qdrant_url: str = Field(default="http://qdrant:6333")
redis_url: str = Field(default="redis://redis:6379")
postgres_host: str = Field(default="postgres")
```

### 2. LLM provider auto-detection

```python
def get_llm_provider():
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    raise ConfigError("No LLM provider configured")
```

### 3. Embedding fallback

If JINA_API_KEY not set, fall back to Gemini embeddings.

## CI/CD

- GitHub Actions builds and pushes to GHCR on release tags
- `latest` tag for stable, `edge` for main branch
- Multi-arch: linux/amd64, linux/arm64

## Future: DRM/Licensing

### Phase 1 (pilots): Telemetry only
- Phone-home on startup with INSTALL_ID
- Track: version, uptime, node count, API calls
- No enforcement, just visibility

### Phase 2 (post-seed): License keys
- LICENSE_KEY in engrammic.env
- Validates against licensing server on startup
- Grace period for offline/network issues
- Enforcement: feature gates or hard stop after expiry

### Phase 3 (GA): Usage-based
- Metered billing based on telemetry
- Tiered limits (nodes, API calls, silos)
- Self-serve license portal

## Open Questions

1. Where to host get.engrammic.ai? (Cloudflare Pages? S3?)
2. Private GHCR or public?
3. Telemetry opt-out for air-gapped deployments?
4. Support channel for partners? (Slack? Discord? Email?)
