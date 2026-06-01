#!/usr/bin/env bash
set -euo pipefail

env="${1:-beta}"
project=engrammic

echo "Pulling secrets for ${env} from GCP Secret Manager..."

> ".env.${env}"

for secret in $(gcloud secrets list --project=$project --filter="name:engrammic-${env}" --format="value(name)"); do
    key=$(basename "$secret" | sed "s/engrammic-${env}-//" | tr '-' '_' | tr '[:lower:]' '[:upper:]')
    value=$(gcloud secrets versions access latest --secret="$secret" --project=$project 2>/dev/null || echo "")
    if [ -n "$value" ]; then
        echo "$key=$value" >> ".env.${env}"
    fi
done

echo "Wrote .env.${env}"
