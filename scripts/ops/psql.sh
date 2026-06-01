#!/usr/bin/env bash
set -euo pipefail

env="${1:-beta}"
project=engrammic
zone=europe-north1-a

PGPASSWORD=$(gcloud secrets versions access latest --secret=engrammic-${env}-postgres-password --project=$project)
CLOUDSQL_IP=$(gcloud sql instances describe engrammic-${env} --project=$project --format='value(ipAddresses[0].ipAddress)')

gcloud compute ssh engrammic-${env}-stateful --zone=$zone --project=$project --tunnel-through-iap \
    --command="docker run -it --rm -e PGPASSWORD='${PGPASSWORD}' postgres:16-alpine psql 'postgresql://context@${CLOUDSQL_IP}/engrammic'"
