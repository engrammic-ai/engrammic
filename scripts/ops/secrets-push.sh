#!/usr/bin/env bash
set -euo pipefail

env="${1:-beta}"
project=engrammic

echo "Pushing secrets for ${env} to GCP Secret Manager..."

if [ ! -f ".env.${env}" ]; then
    echo "Error: .env.${env} not found"
    exit 1
fi

grep -E "^[A-Z_]+=.+" ".env.${env}" | while IFS= read -r line; do
    key=$(echo "$line" | cut -d= -f1 | tr '[:upper:]' '[:lower:]' | tr '_' '-')
    value=$(echo "$line" | cut -d= -f2-)
    secret_name="engrammic-${env}-$key"
    echo "  -> $secret_name"
    if gcloud secrets describe "$secret_name" --project=$project &>/dev/null; then
        echo -n "$value" | gcloud secrets versions add "$secret_name" --project=$project --data-file=-
    else
        echo -n "$value" | gcloud secrets create "$secret_name" --project=$project --data-file=- --replication-policy=automatic
    fi
done

echo "Done."
