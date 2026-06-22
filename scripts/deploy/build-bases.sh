#!/usr/bin/env bash
set -euo pipefail

echo "Building base images via Cloud Build..."

gcloud builds submit --config=deploy/cloudbuild/bases.yaml \
    --project=engrammic .

echo "Done. Base images pushed to europe-north1-docker.pkg.dev/engrammic/releases/"
