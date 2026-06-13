"""GCE instance for stateful services (Memgraph, Qdrant, Redis, optionally Postgres)."""

import pulumi
from pulumi_gcp import compute

DOCKER_COMPOSE_TEMPLATE = """
services:
  memgraph:
    image: memgraph/memgraph:3.10.1
    container_name: memgraph
    ports:
      - "7687:7687"
    volumes:
      - /mnt/memgraph:/var/lib/memgraph
    command: ["--log-level=WARNING", "--also-log-to-stderr", "--storage-properties-on-edges=true"]
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:v1.18.0
    container_name: qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - /mnt/qdrant:/qdrant/storage
    environment:
      - QDRANT__SERVICE__GRPC_PORT=6334
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: ["redis-server", "--appendonly", "yes"]
    restart: unless-stopped
{postgres_service}{dagster_services}
volumes:
  redis-data:
"""

DAGSTER_SERVICES = """
  dagster-code-server:
    image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest
    container_name: engrammic-dagster-code
    command: ["dagster", "api", "grpc", "-h", "0.0.0.0", "-p", "4000", "-m", "context_service.pipelines.definitions"]
    ports:
      - "4000:4000"
    environment:
      - DAGSTER_HOME=/app
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=${POSTGRES_HOST}
      - POSTGRES_USER=context
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DATABASE=engrammic
      - VERTEX_PROJECT_ID=engrammic
      - VERTEX_LOCATION=europe-north1
      - EMBEDDING_PROVIDER=vertex
      - LLM_PROVIDER=vertex_gemini
      - DEFAULT_LLM_MODEL=gemini-3.1-flash-lite
      - CUSTODIAN__ENABLED=true
    depends_on:
      - memgraph
      - qdrant
      - redis
    restart: unless-stopped

  dagster-webserver:
    image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest
    container_name: engrammic-dagster-web
    command: ["dagster-webserver", "-h", "0.0.0.0", "-p", "3000", "-w", "workspace.yaml"]
    ports:
      - "3000:3000"
    environment:
      - DAGSTER_HOME=/app
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=${POSTGRES_HOST}
      - POSTGRES_USER=context
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DATABASE=engrammic
      - VERTEX_PROJECT_ID=engrammic
      - VERTEX_LOCATION=europe-north1
      - EMBEDDING_PROVIDER=vertex
      - LLM_PROVIDER=vertex_gemini
      - DEFAULT_LLM_MODEL=gemini-3.1-flash-lite
      - CUSTODIAN__ENABLED=true
    depends_on:
      - dagster-code-server
    restart: unless-stopped

  dagster-daemon:
    image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest
    container_name: engrammic-dagster-daemon
    command: ["dagster-daemon", "run"]
    environment:
      - DAGSTER_HOME=/app
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=${POSTGRES_HOST}
      - POSTGRES_USER=context
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DATABASE=engrammic
      - VERTEX_PROJECT_ID=engrammic
      - VERTEX_LOCATION=europe-north1
      - EMBEDDING_PROVIDER=vertex
      - LLM_PROVIDER=vertex_gemini
      - DEFAULT_LLM_MODEL=gemini-3.1-flash-lite
      - CUSTODIAN__ENABLED=true
    depends_on:
      - dagster-code-server
    restart: unless-stopped
"""

POSTGRES_SERVICE = """
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
      - POSTGRES_DB=engrammic
    restart: unless-stopped
"""


class StatefulHost(pulumi.ComponentResource):
    """Single GCE instance running Docker Compose for stateful services."""

    def __init__(
        self,
        name: str,
        network: compute.Network,
        subnet: compute.Subnetwork,
        service_account_email: str,
        postgres_host: pulumi.Input[str] | None = None,
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

        self._postgres_host = postgres_host

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

        # Build attached disks list with device_name to control /dev/disk/by-id/ names
        attached_disks = [
            compute.InstanceAttachedDiskArgs(
                source=self.memgraph_disk.self_link,
                device_name=f"engrammic-{env}-memgraph",
            ),
            compute.InstanceAttachedDiskArgs(
                source=self.qdrant_disk.self_link,
                device_name=f"engrammic-{env}-qdrant",
            ),
        ]
        if self.postgres_disk:
            attached_disks.append(
                compute.InstanceAttachedDiskArgs(
                    source=self.postgres_disk.self_link,
                    device_name=f"engrammic-{env}-postgres",
                )
            )

        # Build disk list for startup script
        disk_config = "memgraph qdrant" if use_cloudsql else "memgraph qdrant postgres"

        # Build compose content
        postgres_service = "" if use_cloudsql else POSTGRES_SERVICE
        dagster_services = DAGSTER_SERVICES
        compose_content = DOCKER_COMPOSE_TEMPLATE.format(
            postgres_service=postgres_service,
            dagster_services=dagster_services,
        )

        # Startup script - formats disks if needed, mounts with nofail
        startup_script = (
            """#!/bin/bash
set -e

ENV="{env}"
DISKS="{disks}"
PROJECT="{project}"
USE_CLOUDSQL="{use_cloudsql}"

# Install Docker
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker $(whoami)
fi

# Install Docker Compose
if ! command -v docker-compose &> /dev/null; then
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
fi

# Configure Docker to authenticate with Artifact Registry
gcloud auth configure-docker europe-north1-docker.pkg.dev --quiet

# Memgraph requires higher vm.max_map_count (minimum 524288)
sysctl -w vm.max_map_count=524288
echo "vm.max_map_count=524288" >> /etc/sysctl.conf

# Format and mount persistent disks
for DISK in $DISKS; do
    DEVICE="/dev/disk/by-id/google-engrammic-$ENV-$DISK"
    MOUNT="/mnt/$DISK"

    mkdir -p "$MOUNT"

    # Wait for disk device to appear (up to 60 seconds)
    echo "Waiting for $DEVICE..."
    for i in $(seq 1 60); do
        if [ -e "$DEVICE" ]; then
            break
        fi
        sleep 1
    done

    if [ ! -e "$DEVICE" ]; then
        echo "ERROR: $DEVICE not found after 60s"
        continue
    fi

    # Check if disk has a filesystem, format if not
    if ! blkid "$DEVICE" &>/dev/null; then
        echo "Formatting $DEVICE as ext4..."
        mkfs.ext4 -F "$DEVICE"
    fi

    # Mount if not already mounted
    if ! mountpoint -q "$MOUNT"; then
        mount -o discard,defaults "$DEVICE" "$MOUNT"
    fi

    # Add to fstab with nofail option (won't block boot if mount fails)
    if ! grep -q "$DISK" /etc/fstab; then
        echo "$DEVICE $MOUNT ext4 discard,defaults,nofail 0 2" >> /etc/fstab
    fi

    # Fix permissions for service data directories
    # Memgraph 3.10+ runs as uid=101(memgraph) gid=103(memgraph)
    if [ "$DISK" = "memgraph" ]; then
        chown -R 101:103 "$MOUNT"
    fi
done

# Fetch secrets from Secret Manager
echo "Fetching Postgres password from Secret Manager..."
export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="engrammic-$ENV-postgres-password" --project="$PROJECT" 2>/dev/null || echo "devpassword")

# Set POSTGRES_HOST based on Cloud SQL config
if [ "$USE_CLOUDSQL" = "true" ]; then
    # Read Cloud SQL IP from instance metadata (set by Pulumi)
    export POSTGRES_HOST=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/postgres-host" -H "Metadata-Flavor: Google")
else
    export POSTGRES_HOST=postgres
fi

mkdir -p /opt/engrammic

# Write .env file for docker-compose
cat > /opt/engrammic/.env << ENV_EOF
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_HOST=${POSTGRES_HOST}
ENV_EOF
chmod 600 /opt/engrammic/.env

# Write docker-compose.yml
echo "Writing docker-compose.yml..."
cat > /opt/engrammic/docker-compose.yml << 'COMPOSE_EOF'
{compose_content}
COMPOSE_EOF

# Create systemd service for docker-compose auto-restart
cat > /etc/systemd/system/engrammic-stateful.service << 'SERVICE_EOF'
[Unit]
Description=Engrammic Stateful Services
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/engrammic
ExecStart=/usr/local/bin/docker-compose up -d
ExecStop=/usr/local/bin/docker-compose down
ExecReload=/usr/local/bin/docker-compose restart

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl enable engrammic-stateful.service
systemctl start engrammic-stateful.service

echo "Stateful host ready"
""".replace("{env}", env)
            .replace("{disks}", disk_config)
            .replace("{project}", project)
            .replace("{use_cloudsql}", str(use_cloudsql).lower())
            .replace("{compose_content}", compose_content)
        )

        # GCE Instance
        self.instance = compute.Instance(
            f"{name}-instance",
            name=f"engrammic-{env}-stateful",
            machine_type=instance_type,
            zone=zone,
            boot_disk=compute.InstanceBootDiskArgs(
                initialize_params=compute.InstanceBootDiskInitializeParamsArgs(
                    image="debian-cloud/debian-12",
                    size=100,
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
            metadata={
                "postgres-host": self._postgres_host or "postgres",
            },
            allow_stopping_for_update=True,
            opts=pulumi.ResourceOptions(
                parent=self,
                ignore_changes=["boot_disk"],  # Prevent false-positive disk size updates
            ),
        )

        # Health check for monitoring - can be used for alerting/dashboards
        # Note: Auto-restart is handled by:
        # - VM level: GCE automatic_restart=True (already set for non-spot)
        # - Container level: docker restart: unless-stopped
        self.health_check = compute.HealthCheck(
            f"{name}-health-check",
            name=f"engrammic-{env}-stateful-health",
            check_interval_sec=30,
            timeout_sec=10,
            healthy_threshold=2,
            unhealthy_threshold=3,
            tcp_health_check=compute.HealthCheckTcpHealthCheckArgs(
                port=7687,  # Memgraph bolt port
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.register_outputs(
            {
                "instance_id": self.instance.id,
                "instance_name": self.instance.name,
                "internal_ip": self.instance.network_interfaces[0].network_ip,
                "health_check_id": self.health_check.id,
            }
        )


class TEIHost(pulumi.ComponentResource):
    """GCE instance with T4 GPU for TEI (Text Embeddings Inference)."""

    def __init__(
        self,
        name: str,
        network: compute.Network,
        subnet: compute.Subnetwork,
        service_account_email: str,
        model_id: str = "BAAI/bge-m3",
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:compute:TEIHost", name, None, opts)

        config = pulumi.Config()
        env = config.require("environment")
        zone = config.get("tei_zone") or "europe-west1-b"

        startup_script = f"""#!/bin/bash

# Install GPU drivers (COS has built-in support)
cos-extensions install gpu

# Wait for driver installation (gpu driver takes a moment)
for i in {{1..30}}; do
    if [ -c /dev/nvidia0 ]; then
        echo "GPU device ready"
        break
    fi
    sleep 2
done

# Mount nvidia driver libraries
mount --bind /var/lib/nvidia /var/lib/nvidia
mount -o remount,exec /var/lib/nvidia

# Create cache directory on persistent disk
mkdir -p /mnt/stateful_partition/tei-cache
chmod 777 /mnt/stateful_partition/tei-cache

# Run TEI with GPU (device passthrough for COS)
docker run -d --name tei \\
  --device /dev/nvidia0:/dev/nvidia0 \\
  --device /dev/nvidiactl:/dev/nvidiactl \\
  --device /dev/nvidia-uvm:/dev/nvidia-uvm \\
  --device /dev/nvidia-uvm-tools:/dev/nvidia-uvm-tools \\
  -v /var/lib/nvidia/lib64:/usr/local/nvidia/lib64 \\
  -e LD_LIBRARY_PATH=/usr/local/nvidia/lib64 \\
  -p 8080:80 \\
  -v /mnt/stateful_partition/tei-cache:/data \\
  -e HF_HUB_ENABLE_HF_TRANSFER=1 \\
  --restart unless-stopped \\
  ghcr.io/huggingface/text-embeddings-inference:turing-1.7 \\
  --model-id {model_id} \\
  --pooling cls \\
  --max-client-batch-size 32

echo "TEI host ready"
"""

        self.instance = compute.Instance(
            f"{name}-instance",
            name=f"engrammic-{env}-tei",
            machine_type="n1-standard-4",
            zone=zone,
            boot_disk=compute.InstanceBootDiskArgs(
                initialize_params=compute.InstanceBootDiskInitializeParamsArgs(
                    image="cos-cloud/cos-stable",
                    size=50,
                    type="pd-balanced",
                ),
            ),
            guest_accelerators=[
                compute.InstanceGuestAcceleratorArgs(
                    type="nvidia-tesla-t4",
                    count=1,
                )
            ],
            scheduling=compute.InstanceSchedulingArgs(
                on_host_maintenance="TERMINATE",
                automatic_restart=True,
            ),
            network_interfaces=[
                compute.InstanceNetworkInterfaceArgs(
                    network=network.id,
                    subnetwork=subnet.id,
                )
            ],
            service_account=compute.InstanceServiceAccountArgs(
                email=service_account_email,
                scopes=["cloud-platform"],
            ),
            metadata_startup_script=startup_script,
            tags=["tei-server"],
            allow_stopping_for_update=True,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.register_outputs(
            {
                "instance_id": self.instance.id,
                "instance_name": self.instance.name,
                "internal_ip": self.instance.network_interfaces[0].network_ip,
            }
        )
