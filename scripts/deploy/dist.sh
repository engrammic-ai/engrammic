#!/usr/bin/env bash
set -euo pipefail

version="${1:-0.1.0}"

SHORT_SHA=$(git rev-parse --short HEAD)
echo "Building self-hosted images v${version} (${SHORT_SHA}) via Cloud Build..."

gcloud builds submit --config=deploy/cloudbuild/releases.yaml \
    --substitutions=SHORT_SHA=${SHORT_SHA},_VERSION=${version} \
    --project=engrammic .

echo "Done. Test with:"
echo "  just dist-verify ${version}"
