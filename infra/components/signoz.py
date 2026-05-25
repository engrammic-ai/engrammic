"""GCE instance for SigNoz observability stack."""

import pulumi
from pulumi_gcp import compute

SIGNOZ_COMPOSE = '''
services:
  clickhouse:
    image: clickhouse/clickhouse-server:23.8-alpine
    container_name: clickhouse
    mem_limit: 8g
    ports:
      - "8123:8123"
      - "9000:9000"
    volumes:
      - /mnt/clickhouse:/var/lib/clickhouse
    ulimits:
      nofile:
        soft: 262144
        hard: 262144
    restart: unless-stopped

  signoz-otel-collector:
    image: signoz/signoz-otel-collector:0.88.11
    container_name: signoz-otel-collector
    mem_limit: 1g
    ports:
      - "4317:4317"
      - "4318:4318"
    environment:
      - CLICKHOUSE_HOST=clickhouse
    depends_on:
      - clickhouse
    restart: unless-stopped

  signoz-query-service:
    image: signoz/query-service:0.45.1
    container_name: signoz-query
    mem_limit: 2g
    environment:
      - ClickHouseUrl=tcp://clickhouse:9000
      - STORAGE=clickhouse
    depends_on:
      - clickhouse
    restart: unless-stopped

  signoz-frontend:
    image: signoz/frontend:0.45.1
    container_name: signoz-frontend
    mem_limit: 512m
    ports:
      - "3301:3301"
    environment:
      - FRONTEND_API_ENDPOINT=http://signoz-query-service:8080
    depends_on:
      - signoz-query-service
    restart: unless-stopped
'''


class SignozHost(pulumi.ComponentResource):
    """GCE instance running SigNoz observability stack."""

    def __init__(
        self,
        name: str,
        network: compute.Network,
        subnet: compute.Subnetwork,
        service_account_email: str,
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:compute:SignozHost", name, None, opts)

        config = pulumi.Config()
        gcp_config = pulumi.Config("gcp")
        env = config.require("environment")
        zone = gcp_config.require("zone")

        # Persistent disk for ClickHouse
        self.clickhouse_disk = compute.Disk(
            f"{name}-clickhouse-disk",
            name=f"engrammic-{env}-clickhouse",
            size=100,
            type="pd-ssd",
            zone=zone,
            opts=pulumi.ResourceOptions(parent=self),
        )

        startup_script = f'''#!/bin/bash
set -e

# Install Docker
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# Mount ClickHouse disk
DISK_ID="engrammic-{env}-clickhouse"
MOUNT_POINT="/mnt/clickhouse"
DEVICE="/dev/disk/by-id/google-$DISK_ID"

mkdir -p $MOUNT_POINT

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
    exit 1
fi

if ! mountpoint -q $MOUNT_POINT; then
    if ! blkid $DEVICE &>/dev/null; then
        mkfs.ext4 -F $DEVICE
    fi
    mount -o discard,defaults $DEVICE $MOUNT_POINT
    if ! grep -q "$DISK_ID" /etc/fstab; then
        echo "$DEVICE $MOUNT_POINT ext4 discard,defaults,nofail 0 2" >> /etc/fstab
    fi
fi
chown -R 101:101 $MOUNT_POINT  # ClickHouse UID

mkdir -p /opt/signoz

# Write docker-compose
cat > /opt/signoz/docker-compose.yml << 'COMPOSE_EOF'
{SIGNOZ_COMPOSE}
COMPOSE_EOF

# Create systemd service for docker-compose auto-restart
cat > /etc/systemd/system/engrammic-signoz.service << 'SERVICE_EOF'
[Unit]
Description=Engrammic SigNoz Observability Services
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/signoz
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
ExecReload=/usr/bin/docker compose restart

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl enable engrammic-signoz.service
systemctl start engrammic-signoz.service

echo "SigNoz host ready"
'''

        self.instance = compute.Instance(
            f"{name}-instance",
            name=f"engrammic-{env}-signoz",
            machine_type="e2-standard-4",
            zone=zone,
            boot_disk=compute.InstanceBootDiskArgs(
                initialize_params=compute.InstanceBootDiskInitializeParamsArgs(
                    image="debian-cloud/debian-12",
                    size=30,
                    type="pd-balanced",
                ),
            ),
            attached_disks=[
                compute.InstanceAttachedDiskArgs(
                    source=self.clickhouse_disk.self_link,
                    device_name=f"engrammic-{env}-clickhouse",
                ),
            ],
            network_interfaces=[
                compute.InstanceNetworkInterfaceArgs(
                    network=network.id,
                    subnetwork=subnet.id,
                ),
            ],
            service_account=compute.InstanceServiceAccountArgs(
                email=service_account_email,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            ),
            metadata_startup_script=startup_script,
            tags=["signoz", "allow-iap"],
            allow_stopping_for_update=True,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.register_outputs({
            "instance_id": self.instance.id,
            "instance_name": self.instance.name,
            "instance_ip": self.instance.network_interfaces[0].network_ip,
        })
