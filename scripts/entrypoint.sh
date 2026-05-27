#!/bin/sh
set -e

# Copy gcloud credentials to writable location if mounted read-only
GCLOUD_SRC="/mnt/gcloud/application_default_credentials.json"
GCLOUD_DST="/tmp/gcloud-adc.json"

if [ -r "$GCLOUD_SRC" ]; then
    cp "$GCLOUD_SRC" "$GCLOUD_DST"
    chmod 600 "$GCLOUD_DST"
    export GOOGLE_APPLICATION_CREDENTIALS="$GCLOUD_DST"
elif [ -f "$GCLOUD_SRC" ]; then
    echo "Warning: gcloud credentials exist but are not readable" >&2
fi

# Fetch secrets from GCP Secret Manager if env vars missing
if [ -f /app/scripts/fetch_secrets.py ]; then
    eval "$(python /app/scripts/fetch_secrets.py 2>/dev/null)" || true
fi

exec "$@"
