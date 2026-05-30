#!/bin/bash
# Startup script for engrammic-dev-box: a lightweight personal dev VM reachable
# over Tailscale SSH. Runs on every boot (idempotent), so a spot preemption +
# restart re-establishes Tailscale automatically.
#
# Provisioned standalone via gcloud (see create-dev-box.sh), NOT through Pulumi.
set -euo pipefail

PROJECT="engrammic"
TS_SECRET="engrammic-dev-tailscale-authkey"
TS_HOSTNAME="engrammic-dev-box"
DEV_USER="dev"

log() { echo "[dev-box-startup] $*"; }

# --- Base packages -----------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg git build-essential

# Memgraph (memgraph-mage image) requires an elevated vm.max_map_count or it
# crashes on boot. Mirrors the StatefulHost provisioning (infra/components/compute.py).
sysctl -w vm.max_map_count=524288
grep -q '^vm.max_map_count' /etc/sysctl.conf || echo 'vm.max_map_count=524288' >> /etc/sysctl.conf

# --- gh CLI ------------------------------------------------------------------
if ! command -v gh &>/dev/null; then
    log "Installing GitHub CLI..."
    mkdir -p -m 755 /etc/apt/keyrings
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list
    apt-get update -y
    apt-get install -y --no-install-recommends gh
fi

# --- Docker ------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
fi

# --- just --------------------------------------------------------------------
if ! command -v just &>/dev/null; then
    log "Installing just..."
    curl --proto '=https' --tlsv1.2 -fsSL https://just.systems/install.sh \
        | bash -s -- --to /usr/local/bin
fi

# --- dev user ----------------------------------------------------------------
if ! id "$DEV_USER" &>/dev/null; then
    log "Creating user '$DEV_USER'..."
    useradd -m -s /bin/bash "$DEV_USER"
    echo "$DEV_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-dev
    chmod 0440 /etc/sudoers.d/90-dev
fi
usermod -aG docker "$DEV_USER" || true

# --- uv (installed for the dev user) ----------------------------------------
if [ ! -x "/home/$DEV_USER/.local/bin/uv" ]; then
    log "Installing uv for $DEV_USER..."
    sudo -u "$DEV_USER" sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

# --- Tailscale ---------------------------------------------------------------
if ! command -v tailscale &>/dev/null; then
    log "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
fi

log "Fetching Tailscale auth key from Secret Manager..."
AUTHKEY="$(gcloud secrets versions access latest --secret="$TS_SECRET" --project="$PROJECT")"

log "Bringing up Tailscale with SSH..."
tailscale up --ssh --hostname="$TS_HOSTNAME" --authkey="$AUTHKEY" --accept-routes

log "dev-box ready. Reach it with: tailscale ssh ${DEV_USER}@${TS_HOSTNAME}"
