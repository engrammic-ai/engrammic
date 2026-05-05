#!/usr/bin/env bash
# One-time server setup for Hetzner/VPS
# Run as root on fresh Ubuntu 22.04/24.04

set -euo pipefail

echo "==> Installing Docker"
curl -fsSL https://get.docker.com | sh

echo "==> Installing Docker Compose plugin"
apt-get update && apt-get install -y docker-compose-plugin

echo "==> Creating deploy user"
useradd -m -s /bin/bash deploy
usermod -aG docker deploy

echo "==> Setting up firewall"
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> Creating app directory"
mkdir -p /opt/context-service
chown deploy:deploy /opt/context-service

echo "==> Done! Now run deploy.sh from your local machine"
echo "    SSH key setup: ssh-copy-id deploy@<server-ip>"
