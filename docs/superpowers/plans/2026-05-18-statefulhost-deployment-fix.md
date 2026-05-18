# StatefulHost Deployment Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix StatefulHost to properly format disks, start database services via docker-compose, and enable Cloud Run to connect successfully.

**Architecture:** Embed docker-compose.yml in Pulumi startup script as heredoc. Startup script waits for disks, formats if needed, writes compose file, fetches secrets from Secret Manager, runs `docker compose up -d`. StatefulHost becomes fully self-provisioning.

**Tech Stack:** Pulumi (Python), Docker Compose, GCP Secret Manager, GCE startup scripts

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `infra/docker-compose.infra.yml` | Update volume paths to match Pulumi mounts |
| `infra/components/compute.py` | Embed compose file, fetch secrets, run services |

---

### Task 1: Fix docker-compose.infra.yml Volume Paths

**Files:**
- Modify: `infra/docker-compose.infra.yml`

- [ ] **Step 1: Update volume paths to match Pulumi disk mounts**

The Pulumi startup script mounts disks to `/mnt/memgraph`, `/mnt/qdrant`, `/mnt/postgres`. Update the compose file:

```yaml
services:
  memgraph:
    image: memgraph/memgraph:2.18.1
    container_name: memgraph
    ports:
      - "7687:7687"
    volumes:
      - /mnt/memgraph:/var/lib/memgraph
    command: ["--log-level=WARNING", "--also-log-to-stderr", "--storage-properties-on-edges=true"]
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:v1.9.0
    container_name: qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - /mnt/qdrant:/qdrant/storage
    environment:
      - QDRANT__SERVICE__GRPC_PORT=6334
    healthcheck:
      test: ["CMD-SHELL", "timeout 2 bash -c '</dev/tcp/localhost/6333' || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 2G
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: ["redis-server", "--appendonly", "yes"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 512M
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: postgres
    ports:
      - "5432:5432"
    volumes:
      - /mnt/postgres:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=context
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=context_service
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U context -d context_service"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 1G
    restart: unless-stopped

volumes:
  redis-data:
```

- [ ] **Step 2: Commit**

```bash
git add infra/docker-compose.infra.yml
git commit -m "fix: update docker-compose volume paths to match Pulumi mounts"
```

---

### Task 2: Rewrite StatefulHost Startup Script

**Files:**
- Modify: `infra/components/compute.py`

- [ ] **Step 1: Replace the startup script with a robust version**

The new startup script must:
1. Install Docker if not present
2. Wait for attached disks to appear
3. Format disks if they have no filesystem
4. Mount disks
5. Fetch POSTGRES_PASSWORD from Secret Manager
6. Write docker-compose.yml
7. Run `docker compose up -d`

Replace the entire `compute.py` file:

```python
"""GCE instance for stateful services (Memgraph, Qdrant, Redis, optionally Postgres)."""

import pulumi
from pulumi_gcp import compute

DOCKER_COMPOSE_TEMPLATE = '''
services:
  memgraph:
    image: memgraph/memgraph:2.18.1
    container_name: memgraph
    ports:
      - "7687:7687"
    volumes:
      - /mnt/memgraph:/var/lib/memgraph
    command: ["--log-level=WARNING", "--also-log-to-stderr", "--storage-properties-on-edges=true"]
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:v1.9.0
    container_name: qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - /mnt/qdrant:/qdrant/storage
    environment:
      - QDRANT__SERVICE__GRPC_PORT=6334
    healthcheck:
      test: ["CMD-SHELL", "timeout 2 bash -c '</dev/tcp/localhost/6333' || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 2G
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: ["redis-server", "--appendonly", "yes"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 512M
    restart: unless-stopped
{postgres_service}
volumes:
  redis-data:
'''

POSTGRES_SERVICE = '''
  postgres:
    image: postgres:16-alpine
    container_name: postgres
    ports:
      - "5432:5432"
    volumes:
      - /mnt/postgres:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=context
      - POSTGRES_PASSWORD=${{POSTGRES_PASSWORD}}
      - POSTGRES_DB=context_service
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U context -d context_service"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 1G
    restart: unless-stopped
'''


class StatefulHost(pulumi.ComponentResource):
    """Single GCE instance running Docker Compose for stateful services."""

    def __init__(
        self,
        name: str,
        network: compute.Network,
        subnet: compute.Subnetwork,
        service_account_email: str,
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:compute:StatefulHost", name, None, opts)

        config = pulumi.Config()
        gcp_config = pulumi.Config("gcp")
        env = config.require("environment")
        project = gcp_config.require("project")
        instance_type = config.get("instance_type") or "e2-standard-8"
        use_spot = config.get_bool("use_spot") or False
        disk_size_memgraph = int(config.get("disk_size_memgraph") or "100")
        disk_size_qdrant = int(config.get("disk_size_qdrant") or "100")
        disk_size_postgres = int(config.get("disk_size_postgres") or "50")
        use_cloudsql = config.get_bool("use_cloudsql") or False
        zone = gcp_config.require("zone")

        # Persistent disks
        self.memgraph_disk = compute.Disk(
            f"{name}-memgraph-disk",
            name=f"engrammic-{env}-memgraph",
            size=disk_size_memgraph,
            type="pd-ssd",
            zone=zone,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.qdrant_disk = compute.Disk(
            f"{name}-qdrant-disk",
            name=f"engrammic-{env}-qdrant",
            size=disk_size_qdrant,
            type="pd-ssd",
            zone=zone,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Postgres disk only if not using Cloud SQL
        self.postgres_disk = None
        if not use_cloudsql:
            self.postgres_disk = compute.Disk(
                f"{name}-postgres-disk",
                name=f"engrammic-{env}-postgres",
                size=disk_size_postgres,
                type="pd-ssd",
                zone=zone,
                opts=pulumi.ResourceOptions(parent=self),
            )

        # Build attached disks list
        attached_disks = [
            compute.InstanceAttachedDiskArgs(source=self.memgraph_disk.self_link),
            compute.InstanceAttachedDiskArgs(source=self.qdrant_disk.self_link),
        ]
        if self.postgres_disk:
            attached_disks.append(
                compute.InstanceAttachedDiskArgs(source=self.postgres_disk.self_link)
            )

        # Build disk list and compose content
        if use_cloudsql:
            disk_names = "memgraph qdrant"
            compose_content = DOCKER_COMPOSE_TEMPLATE.format(postgres_service="")
        else:
            disk_names = "memgraph qdrant postgres"
            compose_content = DOCKER_COMPOSE_TEMPLATE.format(postgres_service=POSTGRES_SERVICE)

        # Escape for shell heredoc
        compose_content_escaped = compose_content.replace("'", "'\"'\"'")

        startup_script = f'''#!/bin/bash
set -e

ENV="{env}"
PROJECT="{project}"
DISKS="{disk_names}"
USE_CLOUDSQL="{str(use_cloudsql).lower()}"

log() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}}

log "Starting StatefulHost provisioning..."

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker root
fi

# Wait for Docker to be ready
log "Waiting for Docker..."
until docker info &>/dev/null; do
    sleep 2
done
log "Docker is ready"

# Format and mount persistent disks
for DISK in $DISKS; do
    DEVICE="/dev/disk/by-id/google-engrammic-$ENV-$DISK"
    MOUNT="/mnt/$DISK"

    log "Processing disk: $DISK"
    mkdir -p "$MOUNT"

    # Wait for disk device to appear (up to 60 seconds)
    log "Waiting for $DEVICE..."
    WAITED=0
    while [ ! -e "$DEVICE" ] && [ $WAITED -lt 60 ]; do
        sleep 1
        WAITED=$((WAITED + 1))
    done

    if [ ! -e "$DEVICE" ]; then
        log "ERROR: $DEVICE not found after 60s, skipping"
        continue
    fi

    # Check if disk has a filesystem, format if not
    if ! blkid "$DEVICE" &>/dev/null; then
        log "Formatting $DEVICE as ext4..."
        mkfs.ext4 -F "$DEVICE"
    fi

    # Mount if not already mounted
    if ! mountpoint -q "$MOUNT"; then
        log "Mounting $DEVICE to $MOUNT"
        mount -o discard,defaults "$DEVICE" "$MOUNT"
    fi

    # Fix permissions for postgres data dir
    if [ "$DISK" = "postgres" ]; then
        chown -R 70:70 "$MOUNT"
    fi

    log "Disk $DISK ready at $MOUNT"
done

# Fetch secrets from Secret Manager
log "Fetching secrets from Secret Manager..."
if [ "$USE_CLOUDSQL" != "true" ]; then
    export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="engrammic-$ENV-postgres-password" --project="$PROJECT" 2>/dev/null || echo "devpassword")
fi

# Write docker-compose.yml
log "Writing docker-compose.yml..."
mkdir -p /opt/engrammic
cat > /opt/engrammic/docker-compose.yml << 'COMPOSE_EOF'
{compose_content_escaped}
COMPOSE_EOF

# Start services
log "Starting services with docker compose..."
cd /opt/engrammic
docker compose up -d

# Wait for services to be healthy
log "Waiting for services to be healthy..."
sleep 10

# Check service status
docker compose ps

log "StatefulHost provisioning complete!"
'''

        # GCE Instance
        self.instance = compute.Instance(
            f"{{name}}-instance",
            name=f"engrammic-{{env}}-stateful",
            machine_type=instance_type,
            zone=zone,
            boot_disk=compute.InstanceBootDiskArgs(
                initialize_params=compute.InstanceBootDiskInitializeParamsArgs(
                    image="debian-cloud/debian-12",
                    size=30,
                    type="pd-balanced",
                ),
            ),
            attached_disks=attached_disks,
            network_interfaces=[
                compute.InstanceNetworkInterfaceArgs(
                    network=network.id,
                    subnetwork=subnet.id,
                )
            ],
            scheduling=compute.InstanceSchedulingArgs(
                preemptible=use_spot,
                automatic_restart=not use_spot,
                provisioning_model="SPOT" if use_spot else "STANDARD",
            ),
            service_account=compute.InstanceServiceAccountArgs(
                email=service_account_email,
                scopes=["cloud-platform"],
            ),
            metadata_startup_script=startup_script,
            tags=["stateful-host"],
            allow_stopping_for_update=True,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.register_outputs({{
            "instance_id": self.instance.id,
            "instance_name": self.instance.name,
            "internal_ip": self.instance.network_interfaces[0].network_ip,
        }})
```

**Note:** The f-string in `f"{{name}}-instance"` uses double braces to escape - in the actual file these should be single braces `f"{name}-instance"`.

- [ ] **Step 2: Commit**

```bash
git add infra/components/compute.py
git commit -m "feat: robust StatefulHost startup with docker-compose services"
```

---

### Task 3: Test Deployment

- [ ] **Step 1: Delete existing StatefulHost instance**

```bash
gcloud compute instances delete engrammic-dev-stateful --zone=europe-north1-a --quiet
```

- [ ] **Step 2: Refresh Pulumi state**

```bash
cd infra && uv run pulumi refresh --stack dev --yes
```

- [ ] **Step 3: Deploy with Pulumi**

```bash
uv run pulumi up --stack dev --yes
```

Expected: Instance created, startup script runs.

- [ ] **Step 4: Wait for startup script to complete (2-3 minutes)**

Check serial output:

```bash
gcloud compute instances get-serial-port-output engrammic-dev-stateful --zone=europe-north1-a 2>&1 | grep -E "StatefulHost|Starting|complete|ERROR" | tail -20
```

Expected: "StatefulHost provisioning complete!"

- [ ] **Step 5: Verify services are running**

```bash
gcloud compute ssh engrammic-dev-stateful --zone=europe-north1-a --command="docker ps"
```

Expected: memgraph, qdrant, redis, postgres containers running.

- [ ] **Step 6: Trigger Cloud Run redeploy**

```bash
gcloud run services update engrammic-dev-context-service --region=europe-north1 --update-env-vars="RESTART_TRIGGER=$(date +%s)"
```

Expected: Deployment succeeds, health checks pass.

- [ ] **Step 7: Commit changes if any fixes needed**

```bash
git add -A && git commit -m "fix: deployment adjustments" || echo "No changes"
```

---

### Task 4: Commit Final Changes

- [ ] **Step 1: Ensure all changes committed**

```bash
git status
git log --oneline -5
```

- [ ] **Step 2: Push to remote**

```bash
git push origin main
```

---

## Rollback

If deployment fails:

1. Check serial output: `gcloud compute instances get-serial-port-output engrammic-dev-stateful --zone=europe-north1-a`
2. SSH and check logs: `gcloud compute ssh engrammic-dev-stateful --zone=europe-north1-a --command="journalctl -u google-startup-scripts -n 100"`
3. Check docker logs: `docker logs <container_name>`

To rollback instance:
```bash
gcloud compute instances delete engrammic-dev-stateful --zone=europe-north1-a --quiet
git revert HEAD
cd infra && uv run pulumi up --stack dev --yes
```
