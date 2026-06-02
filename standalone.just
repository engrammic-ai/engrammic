# Standalone deployment with local models
# Imported by main justfile

standalone := "docker/docker-compose.standalone.yml"
standalone_lite := "docker/docker-compose.standalone-lite.yml"
podman_standalone := "docker/podman-compose.standalone.yml"

# =============================================================================
# Docker Standalone
# =============================================================================

# Start standalone stack (standard tier, 32GB+ RAM)
[group('standalone')]
up-standalone *args:
    docker compose -f {{standalone}} up -d {{args}}

# Start standalone stack (lite tier, 8GB+ RAM)
[group('standalone')]
up-standalone-lite *args:
    docker compose -f {{standalone_lite}} up -d {{args}}

# Stop standalone stack (stops whichever is running)
[group('standalone')]
down-standalone:
    -docker compose -f {{standalone}} down 2>/dev/null
    -docker compose -f {{standalone_lite}} down 2>/dev/null

# View standalone logs
[group('standalone')]
logs-standalone service="":
    docker compose -f {{standalone}} logs -f {{service}}

# =============================================================================
# Podman Standalone
# =============================================================================

# Start Podman standalone (tier: standard or lite)
[group('standalone')]
up-podman tier="standard" *args:
    #!/usr/bin/env bash
    if [ "{{tier}}" = "lite" ]; then
        MODEL_TIER=standalone_lite \
        OLLAMA_MODEL=phi4-mini \
        TEI_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
        EMBEDDING_DIMENSIONS=384 \
        podman-compose -f {{podman_standalone}} up -d {{args}}
    else
        MODEL_TIER=standalone_standard \
        OLLAMA_MODEL=deepseek-r1:7b \
        TEI_MODEL=nomic-ai/nomic-embed-text-v1.5 \
        EMBEDDING_DIMENSIONS=768 \
        podman-compose -f {{podman_standalone}} up -d {{args}}
    fi

# Stop Podman standalone
[group('standalone')]
down-podman:
    podman-compose -f {{podman_standalone}} down

# =============================================================================
# Model Management
# =============================================================================

# Pre-pull models for offline use (tier: standard or lite)
[group('standalone')]
pull-models tier="standard":
    #!/usr/bin/env bash
    if [ "{{tier}}" = "lite" ]; then
        echo "Pulling phi4-mini for lite tier..."
        docker run --rm -v ollama-models:/root/.ollama ollama/ollama pull phi4-mini
    else
        echo "Pulling deepseek-r1:7b for standard tier..."
        docker run --rm -v ollama-models:/root/.ollama ollama/ollama pull deepseek-r1:7b
    fi
    echo "TEI models are pulled on first container start."
