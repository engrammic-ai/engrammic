#!/usr/bin/env bash
set -euo pipefail

env="${1:-beta}"
project=engrammic
zone=europe-north1-a
registry=europe-north1-docker.pkg.dev/engrammic/engrammic

PGPASSWORD=$(gcloud secrets versions access latest --secret=engrammic-${env}-postgres-password --project=$project)
CLOUDSQL_IP=$(gcloud sql instances describe engrammic-${env} --project=$project --format='value(ipAddresses[0].ipAddress)')

gcloud compute ssh engrammic-${env}-stateful --zone=$zone --project=$project --tunnel-through-iap \
    --command="docker run --rm postgres:16-alpine psql 'postgresql://context:${PGPASSWORD}@${CLOUDSQL_IP}/engrammic' -c 'SELECT version();'"

echo "Connection OK. Running migrations..."

gcloud compute ssh engrammic-${env}-stateful --zone=$zone --project=$project --tunnel-through-iap \
    --command="docker run --rm -e DATABASE_URL='postgresql+asyncpg://context:${PGPASSWORD}@${CLOUDSQL_IP}/engrammic' ${registry}/engrammic-api:latest alembic upgrade head"
