"""Benchmark environment: GPU VM with local models + dev-box for benchmarking.

Provides fully self-hosted inference stack:
- TEI for embeddings (bge-m3 or nomic-embed)
- TEI for reranking (bge-reranker-base)
- vLLM for LLM (DeepSeek/Qwen 7B-32B)

Optimized for BEAM/LongMemEval benchmark runs with minimal network latency.
"""

import pulumi
from pulumi_gcp import compute

# GPU configurations by tier
GPU_CONFIGS = {
    "t4": {
        "machine_type": "n1-standard-8",
        "accelerator": "nvidia-tesla-t4",
        "vram_gb": 16,
        "max_llm_params": "7B",
    },
    "l4": {
        "machine_type": "g2-standard-8",
        "accelerator": "nvidia-l4",
        "vram_gb": 24,
        "max_llm_params": "14B",
    },
    "a100-40": {
        "machine_type": "a2-highgpu-1g",
        "accelerator": "nvidia-tesla-a100",
        "vram_gb": 40,
        "max_llm_params": "70B",
    },
}

# LLM models - local (vLLM) or API (Vertex AI)
LLM_MODELS = {
    # Vertex AI (no local GPU needed)
    "gemini-3.5-flash": {
        "model_id": "gemini-3.5-flash",
        "provider": "vertex_ai",
        "vram_required": 0,
        "context_length": 1048576,
    },
    # Local vLLM models (require GPU)
    "deepseek-7b": {
        "model_id": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        "provider": "vllm",
        "vram_required": 12,
        "context_length": 32768,
    },
    "qwen-7b": {
        "model_id": "Qwen/Qwen2.5-7B-Instruct",
        "provider": "vllm",
        "vram_required": 12,
        "context_length": 131072,
    },
    "qwen-14b": {
        "model_id": "Qwen/Qwen2.5-14B-Instruct",
        "provider": "vllm",
        "vram_required": 22,
        "context_length": 131072,
    },
    "qwen-32b": {
        "model_id": "Qwen/Qwen2.5-32B-Instruct",
        "provider": "vllm",
        "vram_required": 50,
        "context_length": 131072,
    },
}

# Embedding models for TEI
EMBEDDING_MODELS = {
    "bge-m3": {
        "model_id": "BAAI/bge-m3",
        "dimensions": 1024,
        "vram_required": 2,
    },
    "nomic": {
        "model_id": "nomic-ai/nomic-embed-text-v1.5",
        "dimensions": 768,
        "vram_required": 1,
    },
}

# Reranker models for TEI
RERANKER_MODELS = {
    "bge-reranker-base": {
        "model_id": "BAAI/bge-reranker-base",
        "vram_required": 1,
    },
    "bge-reranker-v2-m3": {
        "model_id": "BAAI/bge-reranker-v2-m3",
        "vram_required": 2,
    },
}


DEV_BOX_COMPOSE = """
services:
  app:
    image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-api:latest
    container_name: engrammic-app
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=benchmark
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
      - POSTGRES_USER=context
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DATABASE=engrammic
      - MODELS__TIER=benchmark
      - TEI_URL=http://${GPU_HOST}:8080
      - RERANKER_URL=http://${GPU_HOST}:8081
      - VERTEX_PROJECT=engrammic
      - VERTEX_LOCATION=global
      - DEFAULT_LLM_MODEL=gemini-3.5-flash
      - OTEL_ENABLED=false
      - HF_HOME=/app/.cache/huggingface
      - FASTEMBED_CACHE_PATH=/app/.cache/fastembed
    volumes:
      - hf-cache:/app/.cache/huggingface
      - fastembed-cache:/app/.cache/fastembed
    depends_on:
      - memgraph
      - qdrant
      - redis
      - postgres
    restart: unless-stopped

  memgraph:
    image: memgraph/memgraph-mage:latest
    container_name: engrammic-memgraph
    ports:
      - "7687:7687"
    volumes:
      - /mnt/memgraph:/var/lib/memgraph
    command: ["--log-level=WARNING", "--also-log-to-stderr", "--storage-properties-on-edges=true"]
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:v1.18.0
    container_name: engrammic-qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - /mnt/qdrant:/qdrant/storage
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: engrammic-redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: ["redis-server", "--appendonly", "yes"]
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: engrammic-postgres
    ports:
      - "5432:5432"
    volumes:
      - /mnt/postgres:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=context
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=engrammic
    restart: unless-stopped

  dagster-webserver:
    image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest
    container_name: engrammic-dagster-web
    ports:
      - "3002:3000"
    environment:
      - DAGSTER_HOME=/app
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
      - POSTGRES_USER=context
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - MODELS__TIER=benchmark
      - TEI_URL=http://${GPU_HOST}:8080
      - RERANKER_URL=http://${GPU_HOST}:8081
      - VERTEX_PROJECT=engrammic
      - VERTEX_LOCATION=global
      - DEFAULT_LLM_MODEL=gemini-3.5-flash
    command: ["dagster-webserver", "-h", "0.0.0.0", "-p", "3000", "-w", "workspace.yaml"]
    depends_on:
      - postgres
    restart: unless-stopped

volumes:
  redis-data:
  hf-cache:
  fastembed-cache:
"""


class BenchmarkGPU(pulumi.ComponentResource):
    """GPU VM with TEI (embeddings + reranker) + vLLM for fully local inference.

    All models run on a single GPU VM for minimal latency.
    VRAM budget: embedding (~2GB) + reranker (~1GB) + LLM (remaining)
    """

    def __init__(
        self,
        name: str,
        network: compute.Network,
        subnet: compute.Subnetwork,
        service_account_email: str,
        gpu_tier: str = "t4",
        embedding_model: str = "bge-m3",
        reranker_model: str = "bge-reranker-base",
        llm_model: str = "qwen-7b",
        use_spot: bool = True,
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:compute:BenchmarkGPU", name, None, opts)

        config = pulumi.Config("benchmark")
        gcp_config = pulumi.Config("gcp")
        env = config.get("environment") or "benchmark"
        zone = config.get("benchmark_gpu_zone") or "europe-west1-b"

        # Validate GPU config
        if gpu_tier not in GPU_CONFIGS:
            raise ValueError(f"Unknown GPU tier: {gpu_tier}. Choose from: {list(GPU_CONFIGS.keys())}")

        gpu_config = GPU_CONFIGS[gpu_tier]
        embed_config = EMBEDDING_MODELS[embedding_model]
        rerank_config = RERANKER_MODELS[reranker_model]
        llm_config = LLM_MODELS[llm_model]

        # Validate VRAM budget
        total_vram = embed_config["vram_required"] + rerank_config["vram_required"] + llm_config["vram_required"]
        if total_vram > gpu_config["vram_gb"]:
            raise ValueError(
                f"Model combination requires {total_vram}GB VRAM but {gpu_tier} only has {gpu_config['vram_gb']}GB. "
                f"Use a larger GPU tier or smaller models."
            )

        startup_script = f"""#!/bin/bash
set -e

echo "=== Benchmark GPU VM Startup ==="
echo "GPU: {gpu_tier}"
echo "Embedding: {embed_config['model_id']}"
echo "Reranker: {rerank_config['model_id']}"
echo "LLM: {llm_config['model_id']}"

# Verify GPU is available (Deep Learning VM has drivers pre-installed)
echo "Checking GPU..."
nvidia-smi || {{ echo "ERROR: nvidia-smi failed"; exit 1; }}

# Install Docker if not present (Deep Learning VMs may not have it)
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    apt-get update -qq
    apt-get install -y -qq docker.io
    systemctl enable docker
    systemctl start docker
fi

# Install nvidia-container-toolkit if not present
if ! docker info 2>/dev/null | grep -q nvidia; then
    echo "Installing nvidia-container-toolkit..."
    distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update -qq
    apt-get install -y -qq nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
fi

# Create cache directories
mkdir -p /opt/tei-cache /opt/reranker-cache
chmod 777 /opt/tei-cache /opt/reranker-cache

# Docker network for inter-container communication
docker network create benchmark-net 2>/dev/null || true

# ===== TEI Embeddings (port 8080) =====
echo "Starting TEI embeddings..."
docker run -d --name tei-embed \\
  --network benchmark-net \\
  --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all \\
  -p 8080:80 \\
  -v /opt/tei-cache:/data \\
  -e HF_HUB_ENABLE_HF_TRANSFER=1 \\
  -e CUDA_VISIBLE_DEVICES=0 \\
  --restart unless-stopped \\
  ghcr.io/huggingface/text-embeddings-inference:turing-1.7 \\
  --model-id {embed_config['model_id']} \\
  --pooling cls \\
  --max-client-batch-size 64

# ===== TEI Reranker (port 8081) =====
echo "Starting TEI reranker..."
docker run -d --name tei-rerank \\
  --network benchmark-net \\
  --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all \\
  -p 8081:80 \\
  -v /opt/reranker-cache:/data \\
  -e HF_HUB_ENABLE_HF_TRANSFER=1 \\
  -e CUDA_VISIBLE_DEVICES=0 \\
  --restart unless-stopped \\
  ghcr.io/huggingface/text-embeddings-inference:turing-1.7 \\
  --model-id {rerank_config['model_id']}

# ===== LLM =====
# Using Gemini API instead of local vLLM (set GOOGLE_API_KEY env var)
echo "LLM: Using Gemini 3.5 Flash via API (no local container)"

# Wait for services to be ready
echo "Waiting for services to start..."
sleep 30

# Health check
for port in 8080 8081; do
    for i in {{1..30}}; do
        if curl -s http://localhost:$port/health > /dev/null 2>&1; then
            echo "Port $port ready"
            break
        fi
        sleep 2
    done
done

echo "=== Benchmark GPU VM Ready ==="
echo "TEI Embeddings: http://$(hostname -I | awk '{{print $1}}'):8080"
echo "TEI Reranker: http://$(hostname -I | awk '{{print $1}}'):8081"
echo "vLLM: http://$(hostname -I | awk '{{print $1}}'):8000"
"""

        # Determine scheduling based on spot
        if use_spot:
            scheduling = compute.InstanceSchedulingArgs(
                preemptible=True,
                automatic_restart=False,
                provisioning_model="SPOT",
                on_host_maintenance="TERMINATE",
            )
        else:
            scheduling = compute.InstanceSchedulingArgs(
                automatic_restart=True,
                on_host_maintenance="TERMINATE",
            )

        self.instance = compute.Instance(
            f"{name}-instance",
            name=f"engrammic-{env}-benchmark-gpu",
            machine_type=gpu_config["machine_type"],
            zone=zone,
            boot_disk=compute.InstanceBootDiskArgs(
                initialize_params=compute.InstanceBootDiskInitializeParamsArgs(
                    image="deeplearning-platform-release/common-cu129-ubuntu-2204-nvidia-580-v20260616",
                    size=200,
                    type="pd-ssd",
                ),
            ),
            guest_accelerators=[
                compute.InstanceGuestAcceleratorArgs(
                    type=gpu_config["accelerator"],
                    count=1,
                )
            ],
            scheduling=scheduling,
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
            tags=["benchmark-gpu", "tei-server"],
            allow_stopping_for_update=True,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.internal_ip = self.instance.network_interfaces[0].network_ip

        self.register_outputs(
            {
                "instance_id": self.instance.id,
                "instance_name": self.instance.name,
                "internal_ip": self.internal_ip,
                "gpu_tier": gpu_tier,
                "embedding_model": embed_config["model_id"],
                "reranker_model": rerank_config["model_id"],
                "llm_model": llm_config["model_id"],
            }
        )


class BenchmarkDevBox(pulumi.ComponentResource):
    """Dev-box VM running the full Engrammic stack, configured for local models."""

    def __init__(
        self,
        name: str,
        network: compute.Network,
        subnet: compute.Subnetwork,
        service_account_email: str,
        gpu_host_ip: pulumi.Input[str],
        use_spot: bool = True,
        tailscale_enabled: bool = True,
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:compute:BenchmarkDevBox", name, None, opts)

        config = pulumi.Config("benchmark")
        gcp_config = pulumi.Config("gcp")
        env = config.get("environment") or "benchmark"
        project = gcp_config.require("project")
        zone = config.get("benchmark_devbox_zone") or "europe-north1-a"
        instance_type = config.get("benchmark_devbox_instance_type") or "e2-standard-4"

        # Persistent disks for data
        self.memgraph_disk = compute.Disk(
            f"{name}-memgraph-disk",
            name=f"engrammic-{env}-benchmark-memgraph",
            size=50,
            type="pd-ssd",
            zone=zone,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.qdrant_disk = compute.Disk(
            f"{name}-qdrant-disk",
            name=f"engrammic-{env}-benchmark-qdrant",
            size=50,
            type="pd-ssd",
            zone=zone,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.postgres_disk = compute.Disk(
            f"{name}-postgres-disk",
            name=f"engrammic-{env}-benchmark-postgres",
            size=20,
            type="pd-ssd",
            zone=zone,
            opts=pulumi.ResourceOptions(parent=self),
        )

        attached_disks = [
            compute.InstanceAttachedDiskArgs(
                source=self.memgraph_disk.self_link,
                device_name=f"engrammic-{env}-benchmark-memgraph",
            ),
            compute.InstanceAttachedDiskArgs(
                source=self.qdrant_disk.self_link,
                device_name=f"engrammic-{env}-benchmark-qdrant",
            ),
            compute.InstanceAttachedDiskArgs(
                source=self.postgres_disk.self_link,
                device_name=f"engrammic-{env}-benchmark-postgres",
            ),
        ]

        # Tailscale setup (optional)
        tailscale_setup = ""
        if tailscale_enabled:
            tailscale_setup = f"""
# Install and configure Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Get auth key from Secret Manager
TAILSCALE_KEY=$(gcloud secrets versions access latest --secret="engrammic-dev-tailscale-authkey" --project="{project}" 2>/dev/null || echo "")
if [ -n "$TAILSCALE_KEY" ]; then
    tailscale up --authkey "$TAILSCALE_KEY" --hostname "benchmark-dev-box" --accept-routes
    echo "Tailscale configured"
else
    echo "WARNING: No Tailscale auth key found, skipping Tailscale setup"
fi
"""

        startup_script = pulumi.Output.all(gpu_host_ip).apply(
            lambda args: f"""#!/bin/bash
set -e

GPU_HOST="{args[0]}"
ENV="{env}"
PROJECT="{project}"

echo "=== Benchmark Dev-Box Startup ==="
echo "GPU Host: $GPU_HOST"

# Install Docker
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker $(whoami) || true
fi

# Install Docker Compose
if ! command -v docker-compose &> /dev/null; then
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
fi

# Configure Docker for Artifact Registry
gcloud auth configure-docker europe-north1-docker.pkg.dev --quiet

# Memgraph vm.max_map_count
sysctl -w vm.max_map_count=524288
echo "vm.max_map_count=524288" >> /etc/sysctl.conf

# Format and mount persistent disks
for DISK in memgraph qdrant postgres; do
    DEVICE="/dev/disk/by-id/google-engrammic-$ENV-benchmark-$DISK"
    MOUNT="/mnt/$DISK"

    mkdir -p "$MOUNT"

    echo "Waiting for $DEVICE..."
    for i in $(seq 1 60); do
        if [ -e "$DEVICE" ]; then break; fi
        sleep 1
    done

    if [ ! -e "$DEVICE" ]; then
        echo "ERROR: $DEVICE not found"
        continue
    fi

    if ! blkid "$DEVICE" &>/dev/null; then
        echo "Formatting $DEVICE as ext4..."
        mkfs.ext4 -F "$DEVICE"
    fi

    if ! mountpoint -q "$MOUNT"; then
        mount -o discard,defaults "$DEVICE" "$MOUNT"
    fi

    if ! grep -q "benchmark-$DISK" /etc/fstab; then
        echo "$DEVICE $MOUNT ext4 discard,defaults,nofail 0 2" >> /etc/fstab
    fi

    if [ "$DISK" = "memgraph" ]; then
        chown -R 101:103 "$MOUNT"
    fi
done

# Fetch secrets
export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="engrammic-$ENV-postgres-password" --project="$PROJECT" 2>/dev/null || echo "benchmarkpass")
export GPU_HOST="$GPU_HOST"

mkdir -p /opt/engrammic

# Write environment file
cat > /opt/engrammic/.env << ENV_EOF
POSTGRES_PASSWORD=${{POSTGRES_PASSWORD}}
GPU_HOST=${{GPU_HOST}}
ENV_EOF
chmod 600 /opt/engrammic/.env

# Write docker-compose.yml
cat > /opt/engrammic/docker-compose.yml << 'COMPOSE_EOF'
{DEV_BOX_COMPOSE}
COMPOSE_EOF

{tailscale_setup}

# Create systemd service
cat > /etc/systemd/system/engrammic-benchmark.service << 'SERVICE_EOF'
[Unit]
Description=Engrammic Benchmark Dev-Box
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
systemctl enable engrammic-benchmark.service
systemctl start engrammic-benchmark.service

echo "=== Benchmark Dev-Box Ready ==="
echo "API: http://$(hostname -I | awk '{{print $1}}'):8000"
echo "Dagster: http://$(hostname -I | awk '{{print $1}}'):3002"
"""
        )

        # Scheduling
        if use_spot:
            scheduling = compute.InstanceSchedulingArgs(
                preemptible=True,
                automatic_restart=False,
                provisioning_model="SPOT",
            )
        else:
            scheduling = compute.InstanceSchedulingArgs(
                automatic_restart=True,
            )

        self.instance = compute.Instance(
            f"{name}-instance",
            name=f"engrammic-{env}-benchmark-devbox",
            machine_type=instance_type,
            zone=zone,
            boot_disk=compute.InstanceBootDiskArgs(
                initialize_params=compute.InstanceBootDiskInitializeParamsArgs(
                    image="debian-cloud/debian-12",
                    size=50,
                    type="pd-balanced",
                ),
            ),
            attached_disks=attached_disks,
            scheduling=scheduling,
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
            tags=["benchmark-devbox", "engrammic-api"],
            allow_stopping_for_update=True,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.internal_ip = self.instance.network_interfaces[0].network_ip

        self.register_outputs(
            {
                "instance_id": self.instance.id,
                "instance_name": self.instance.name,
                "internal_ip": self.internal_ip,
            }
        )


class BenchmarkEnvironment(pulumi.ComponentResource):
    """Complete benchmark environment: GPU VM + dev-box + networking.

    Creates a fully self-hosted inference stack for running BEAM/LongMemEval benchmarks
    with minimal latency. All models run locally on GPU.

    Usage in Pulumi.benchmark.yaml:
        config:
          gcp:project: engrammic
          gcp:region: europe-north1
          gcp:zone: europe-north1-a
          benchmark:environment: benchmark
          benchmark:gpu_tier: t4
          benchmark:llm_model: qwen-7b
          benchmark:use_spot: true
    """

    def __init__(
        self,
        name: str,
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:compute:BenchmarkEnvironment", name, None, opts)

        config = pulumi.Config("benchmark")
        gcp_config = pulumi.Config("gcp")

        env = config.get("environment") or "benchmark"
        gpu_tier = config.get("gpu_tier") or "t4"
        embedding_model = config.get("embedding_model") or "bge-m3"
        reranker_model = config.get("reranker_model") or "bge-reranker-base"
        llm_model = config.get("llm_model") or "qwen-7b"
        use_spot = config.get_bool("use_spot") if config.get("use_spot") is not None else True
        tailscale_enabled = config.get_bool("tailscale") if config.get("tailscale") is not None else True

        project = gcp_config.require("project")
        region = gcp_config.get("region") or "europe-north1"

        # Use existing stateful-host SA (has artifact registry + secret manager access)
        sa_email = f"stateful-host-dev@{project}.iam.gserviceaccount.com"

        # Get GPU zone region (GPU and devbox may be in different regions)
        gpu_zone = config.get("benchmark_gpu_zone") or "europe-west1-b"
        gpu_region = "-".join(gpu_zone.split("-")[:2])  # europe-west1-b -> europe-west1
        devbox_zone = config.get("benchmark_devbox_zone") or "europe-north1-a"
        devbox_region = "-".join(devbox_zone.split("-")[:2])

        # Create VPC and subnets (one per region if different)
        self.network = compute.Network(
            f"{name}-network",
            name=f"engrammic-{env}-vpc",
            auto_create_subnetworks=False,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Subnet for GPU VM
        self.gpu_subnet = compute.Subnetwork(
            f"{name}-gpu-subnet",
            name=f"engrammic-{env}-gpu-subnet",
            network=self.network.id,
            region=gpu_region,
            ip_cidr_range="10.0.1.0/24",
            private_ip_google_access=True,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Subnet for devbox (may be same region or different)
        self.devbox_subnet = compute.Subnetwork(
            f"{name}-devbox-subnet",
            name=f"engrammic-{env}-devbox-subnet",
            network=self.network.id,
            region=devbox_region,
            ip_cidr_range="10.0.2.0/24",
            private_ip_google_access=True,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Keep self.subnet for backwards compat
        self.subnet = self.devbox_subnet

        # NAT routers for outbound internet (model downloads)
        # GPU region NAT
        self.gpu_router = compute.Router(
            f"{name}-gpu-router",
            name=f"engrammic-{env}-gpu-router",
            network=self.network.id,
            region=gpu_region,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.gpu_nat = compute.RouterNat(
            f"{name}-gpu-nat",
            name=f"engrammic-{env}-gpu-nat",
            router=self.gpu_router.name,
            region=gpu_region,
            nat_ip_allocate_option="AUTO_ONLY",
            source_subnetwork_ip_ranges_to_nat="ALL_SUBNETWORKS_ALL_IP_RANGES",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Devbox region NAT (if different region)
        if devbox_region != gpu_region:
            self.devbox_router = compute.Router(
                f"{name}-devbox-router",
                name=f"engrammic-{env}-devbox-router",
                network=self.network.id,
                region=devbox_region,
                opts=pulumi.ResourceOptions(parent=self),
            )

            self.devbox_nat = compute.RouterNat(
                f"{name}-devbox-nat",
                name=f"engrammic-{env}-devbox-nat",
                router=self.devbox_router.name,
                region=devbox_region,
                nat_ip_allocate_option="AUTO_ONLY",
                source_subnetwork_ip_ranges_to_nat="ALL_SUBNETWORKS_ALL_IP_RANGES",
                opts=pulumi.ResourceOptions(parent=self),
            )

        # Keep backwards compat
        self.router = self.gpu_router
        self.nat = self.gpu_nat

        # Firewall rules
        self.firewall_internal = compute.Firewall(
            f"{name}-firewall-internal",
            name=f"engrammic-{env}-internal",
            network=self.network.id,
            allows=[
                compute.FirewallAllowArgs(protocol="tcp", ports=["0-65535"]),
                compute.FirewallAllowArgs(protocol="udp", ports=["0-65535"]),
                compute.FirewallAllowArgs(protocol="icmp"),
            ],
            source_ranges=["10.0.0.0/16"],
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.firewall_iap = compute.Firewall(
            f"{name}-firewall-iap",
            name=f"engrammic-{env}-iap-ssh",
            network=self.network.id,
            allows=[compute.FirewallAllowArgs(protocol="tcp", ports=["22"])],
            source_ranges=["35.235.240.0/20"],
            opts=pulumi.ResourceOptions(parent=self),
        )

        # GPU VM (uses GPU subnet in GPU region)
        self.gpu = BenchmarkGPU(
            f"{name}-gpu",
            network=self.network,
            subnet=self.gpu_subnet,
            service_account_email=sa_email,
            gpu_tier=gpu_tier,
            embedding_model=embedding_model,
            reranker_model=reranker_model,
            llm_model=llm_model,
            use_spot=use_spot,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Dev-box VM (uses devbox subnet in devbox region)
        self.devbox = BenchmarkDevBox(
            f"{name}-devbox",
            network=self.network,
            subnet=self.devbox_subnet,
            service_account_email=sa_email,
            gpu_host_ip=self.gpu.internal_ip,
            use_spot=use_spot,
            tailscale_enabled=tailscale_enabled,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.gpu]),
        )

        self.register_outputs(
            {
                "gpu_instance_ip": self.gpu.internal_ip,
                "devbox_instance_ip": self.devbox.internal_ip,
                "tei_embeddings_url": pulumi.Output.concat("http://", self.gpu.internal_ip, ":8080"),
                "tei_reranker_url": pulumi.Output.concat("http://", self.gpu.internal_ip, ":8081"),
                "llm_provider": "vertex_ai/gemini-3.5-flash",  # Via Vertex AI (SA auth)
                "engrammic_url": pulumi.Output.concat("http://", self.devbox.internal_ip, ":8000"),
            }
        )
