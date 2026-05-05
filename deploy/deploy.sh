#!/usr/bin/env bash
# Deploy to production server
# Usage: ./deploy/deploy.sh <server-ip> [domain]

set -euo pipefail

SERVER="${1:?Usage: deploy.sh <server-ip> [domain]}"
DOMAIN="${2:-localhost}"
REMOTE_DIR="/opt/context-service"
SSH_USER="deploy"

echo "==> Deploying to $SERVER (domain: $DOMAIN)"

# Files to sync
rsync -avz --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude '.mypy_cache' \
    --exclude '.ruff_cache' \
    --exclude 'venv' \
    --exclude '.venv' \
    --exclude '*.pyc' \
    --exclude '.env.local' \
    --exclude 'secrets/*' \
    -e ssh \
    . "$SSH_USER@$SERVER:$REMOTE_DIR/"

echo "==> Building and starting services"
ssh "$SSH_USER@$SERVER" "cd $REMOTE_DIR && \
    DOMAIN=$DOMAIN docker compose \
        -f docker-compose.yml \
        -f docker-compose.prod.yml \
        -f deploy/docker-compose.deploy.yml \
        up -d --build --remove-orphans"

echo "==> Deployment complete!"
echo "    Health: https://$DOMAIN/health"
