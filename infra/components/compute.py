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
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=context_service
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
        compose_content = DOCKER_COMPOSE_TEMPLATE.format(postgres_service=postgres_service)

        # Startup script - formats disks if needed, mounts with nofail
        startup_script = """#!/bin/bash
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

# Memgraph requires higher vm.max_map_count
sysctl -w vm.max_map_count=262144
echo "vm.max_map_count=262144" >> /etc/sysctl.conf

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
    if [ "$DISK" = "memgraph" ]; then
        chown -R 100:101 "$MOUNT"
    fi
done

# Fetch secrets from Secret Manager (only if not using Cloud SQL)
if [ "$USE_CLOUDSQL" != "true" ]; then
    echo "Fetching Postgres password from Secret Manager..."
    export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="engrammic-$ENV-postgres-password" --project="$PROJECT" 2>/dev/null || echo "devpassword")
fi

# Write docker-compose.yml
echo "Writing docker-compose.yml..."
mkdir -p /opt/engrammic
cat > /opt/engrammic/docker-compose.yml << 'COMPOSE_EOF'
{compose_content}
COMPOSE_EOF

# Start services
echo "Starting services with docker compose..."
cd /opt/engrammic
docker compose up -d

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

echo "Stateful host ready"
""".replace("{env}", env).replace("{disks}", disk_config).replace("{project}", project).replace("{use_cloudsql}", str(use_cloudsql).lower()).replace("{compose_content}", compose_content)

        # GCE Instance
        self.instance = compute.Instance(
            f"{name}-instance",
            name=f"engrammic-{env}-stateful",
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

        # Health check for the instance
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

        # Unmanaged instance group for health check binding
        self.instance_group = compute.InstanceGroup(
            f"{name}-instance-group",
            name=f"engrammic-{env}-stateful-group",
            zone=zone,
            instances=[self.instance.self_link],
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.instance]),
        )

        self.register_outputs({
            "instance_id": self.instance.id,
            "instance_name": self.instance.name,
            "internal_ip": self.instance.network_interfaces[0].network_ip,
            "health_check_id": self.health_check.id,
            "instance_group_id": self.instance_group.id,
        })
