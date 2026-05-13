"""GCE instance for stateful services (Memgraph, Qdrant, Redis, Postgres, Dagster)."""

import pulumi
from pulumi_gcp import compute


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
        instance_type = config.get("instance_type") or "e2-standard-8"
        use_spot = config.get_bool("use_spot") or False
        disk_size_memgraph = int(config.get("disk_size_memgraph") or "100")
        disk_size_qdrant = int(config.get("disk_size_qdrant") or "100")
        disk_size_postgres = int(config.get("disk_size_postgres") or "50")
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

        self.postgres_disk = compute.Disk(
            f"{name}-postgres-disk",
            name=f"engrammic-{env}-postgres",
            size=disk_size_postgres,
            type="pd-ssd",
            zone=zone,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Startup script
        startup_script = """#!/bin/bash
set -e

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

# Mount persistent disks
mkdir -p /mnt/memgraph /mnt/qdrant /mnt/postgres
mount -o discard,defaults /dev/disk/by-id/google-engrammic-{env}-memgraph /mnt/memgraph || true
mount -o discard,defaults /dev/disk/by-id/google-engrammic-{env}-qdrant /mnt/qdrant || true
mount -o discard,defaults /dev/disk/by-id/google-engrammic-{env}-postgres /mnt/postgres || true

# Add to fstab for persistence
grep -q memgraph /etc/fstab || echo '/dev/disk/by-id/google-engrammic-{env}-memgraph /mnt/memgraph ext4 discard,defaults 0 2' >> /etc/fstab
grep -q qdrant /etc/fstab || echo '/dev/disk/by-id/google-engrammic-{env}-qdrant /mnt/qdrant ext4 discard,defaults 0 2' >> /etc/fstab
grep -q postgres /etc/fstab || echo '/dev/disk/by-id/google-engrammic-{env}-postgres /mnt/postgres ext4 discard,defaults 0 2' >> /etc/fstab

echo "Stateful host ready"
""".replace("{env}", env)

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
            attached_disks=[
                compute.InstanceAttachedDiskArgs(source=self.memgraph_disk.self_link),
                compute.InstanceAttachedDiskArgs(source=self.qdrant_disk.self_link),
                compute.InstanceAttachedDiskArgs(source=self.postgres_disk.self_link),
            ],
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

        self.register_outputs({
            "instance_id": self.instance.id,
            "instance_name": self.instance.name,
            "internal_ip": self.instance.network_interfaces[0].network_ip,
        })
