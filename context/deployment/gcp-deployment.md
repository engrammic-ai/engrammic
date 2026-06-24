# GCP Deployment Guide

## Architecture

```
Cloud Build (europe-north1)
    |
    v
Artifact Registry (engrammic-api, engrammic-dagster)
    |
    v
GCE Instance (europe-north1-a)
  - Memgraph (7687)
  - Qdrant (6333/6334)
  - Redis (6379)
  - Postgres (5432)
  - API container (8000)
  - Dagster (3000)
```

## Prerequisites

1. GCP project `engrammic` with billing enabled
2. `gcloud` CLI authenticated (`gcloud auth login`)
3. Pulumi CLI installed (`~/.pulumi/bin/pulumi`)
4. Docker (for local testing only)

## Initial Setup

### 1. Enable APIs
```bash
gcloud services enable \
  compute.googleapis.com \
  secretmanager.googleapis.com \
  run.googleapis.com \
  vpcaccess.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com
```

### 2. Deploy Infrastructure
```bash
cd infra
~/.pulumi/bin/pulumi stack select dev
~/.pulumi/bin/pulumi up
```

Creates:
- VPC + subnets + NAT + firewall
- GCE instance (e2-standard-2 spot)
- 3 persistent disks (memgraph, qdrant, postgres)
- Service accounts (cloudbuild, stateful-host, cloudrun)
- Secret Manager secrets (empty)
- GCS backup bucket

### 3. Format and Mount Disks (first time only)
```bash
just ssh
# On instance:
sudo mkfs.ext4 -F /dev/sdb  # memgraph
sudo mkfs.ext4 -F /dev/sdc  # qdrant
sudo mkfs.ext4 -F /dev/sdd  # postgres

sudo mkdir -p /mnt/disks/{memgraph,qdrant,postgres}
sudo mount /dev/sdb /mnt/disks/memgraph
sudo mount /dev/sdc /mnt/disks/qdrant
sudo mount /dev/sdd /mnt/disks/postgres
sudo chmod 777 /mnt/disks/*

# Persist mounts
echo '/dev/sdb /mnt/disks/memgraph ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
echo '/dev/sdc /mnt/disks/qdrant ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
echo '/dev/sdd /mnt/disks/postgres ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
```

## Building Images

```bash
just build              # Build engrammic-api via Cloud Build
just build-dagster      # Build engrammic-dagster via Cloud Build
just images             # List images in registry
```

Images are pushed to: `europe-north1-docker.pkg.dev/engrammic/engrammic/`

## Deploying to GCE

### Start Infra Services
```bash
# Copy compose file
cat infra/docker-compose.infra.yml | gcloud compute ssh engrammic-dev-stateful \
  --zone=europe-north1-a --tunnel-through-iap --command="cat > ~/docker-compose.yml"

# Start services
just ssh
docker compose up -d
```

### Check Status
```bash
just docker-status      # Show running containers
just disk-usage         # Check disk space
just mem                # Check memory
```

## SSH and Tunnels

```bash
just ssh                # SSH to instance
just tunnel-memgraph    # Forward 7687 to localhost
just tunnel-qdrant      # Forward 6333/6334 to localhost
just tunnel-postgres    # Forward 5432 to localhost
just tunnel-redis       # Forward 6379 to localhost
just tunnel-dagster     # Forward 3000 to localhost
just tunnel-all         # Forward all ports
```

## Instance Control

```bash
just start              # Start instance
just stop               # Stop instance (saves cost)
just restart            # Restart instance
just status             # Check instance status
```

## Pulumi Commands

```bash
just preview            # Preview changes
just up                 # Apply changes
just outputs            # Show outputs
just destroy            # Tear down (caution!)
```

## Service Accounts

| SA | Purpose |
|----|---------|
| `cloudbuild-dev@engrammic.iam.gserviceaccount.com` | Cloud Build - push images |
| `stateful-host-dev@engrammic.iam.gserviceaccount.com` | GCE - pull images, secrets |
| `context-service-run-dev@engrammic.iam.gserviceaccount.com` | Cloud Run (future) |

## Cost Estimate (Dev)

| Component | Monthly |
|-----------|---------|
| GCE e2-standard-2 spot | ~$20 |
| Persistent disks (50GB SSD) | ~$9 |
| Cloud Build | ~$5 |
| Networking | ~$5 |
| **Total** | **~$40/mo** |

## Troubleshooting

### Cloud Build fails with permission error
Check SA has `roles/storage.objectAdmin` and `roles/artifactregistry.writer`.

### Can't SSH to instance
Ensure IAP firewall rule exists and you have `roles/iap.tunnelResourceAccessor`.

### Containers won't start
Check disk mounts: `df -h | grep mnt`
Check docker logs: `docker logs <container>`
