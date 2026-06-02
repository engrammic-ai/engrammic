#!/usr/bin/env bash
set -euo pipefail

version="${1:-0.1.0}"
releases_registry=europe-north1-docker.pkg.dev/engrammic/releases

echo "Testing unauthenticated pull..."
docker logout europe-north1-docker.pkg.dev 2>/dev/null || true

docker pull ${releases_registry}/engrammic-api:v${version}
docker pull ${releases_registry}/engrammic-beacon:v${version}

echo "Public pull works!"
