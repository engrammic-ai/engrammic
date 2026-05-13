# GCP Deployment - Next Steps

**Status**: Scaffold complete, ready for first deploy  
**Created**: 2026-05-13  
**Budget**: $25k GCP credits (~$400/mo = 62 months runway)

## What's Done

- [x] Pulumi scaffold in `infra/` (uses uv toolchain)
- [x] VPC, subnets, Cloud NAT, firewall rules
- [x] GCE instance config for stateful services
- [x] Cloud Run v2 for API (commented out until image ready)
- [x] Secret Manager, IAM, GCS backup bucket
- [x] Architecture brainstorm: `context/brainstorm/2026-05-13-gcp-deployment-architecture.md`

## Next Session Tasks

### 1. GCP Project Setup
```bash
# Auth (if not already done)
gcloud auth login
gcloud auth application-default login
gcloud config set project engrammic

# Enable required APIs
gcloud services enable \
  compute.googleapis.com \
  secretmanager.googleapis.com \
  run.googleapis.com \
  vpcaccess.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com
```

### 2. Initialize Pulumi
```bash
cd infra
pulumi login  # uses Pulumi Cloud free tier
pulumi stack init dev
pulumi config set gcp:project engrammic
pulumi config set gcp:region us-central1
```

### 3. Preview and Deploy
```bash
pulumi preview  # verify resources
pulumi up       # deploy (will prompt for confirmation)
```

### 4. Post-Deploy: Add Secrets
```bash
# Add secret values (Pulumi creates empty secrets)
echo -n "your-password" | gcloud secrets versions add engrammic-dev-postgres-password --data-file=-
echo -n "your-api-key" | gcloud secrets versions add engrammic-dev-anthropic-api-key --data-file=-
# ... repeat for other secrets
```

### 5. Deploy Docker Compose to GCE
```bash
# SSH into instance
gcloud compute ssh engrammic-dev-stateful --tunnel-through-iap

# On the instance:
# 1. Clone repo or copy docker-compose.prod.yml
# 2. Create .env with secret values
# 3. docker-compose up -d
```

### 6. Enable Cloud Run (when ready)
1. Build and push container image to Artifact Registry
2. Uncomment `ContextServiceRun` in `infra/__main__.py`
3. Update image URL and env vars
4. `pulumi up`

## Architecture Reminder

```
Cloud Run (context-service API)
       |
       | VPC Connector
       v
GCE VM (e2-standard-8, 32GB)
  - Memgraph (4GB)
  - Qdrant (2GB)
  - Redis (512MB)
  - Postgres (1GB)
  - Dagster (3GB)
```

## Cost Estimate

| Component | Monthly |
|-----------|---------|
| GCE e2-standard-8 | ~$280 |
| Persistent disks (270GB SSD) | ~$45 |
| Cloud Run (min=1) | ~$30-50 |
| Networking + misc | ~$25 |
| **Total** | **~$400/mo** |

## Open Decisions

- [ ] Cloud SQL vs self-hosted Postgres? (saves ops, costs +$115/mo)
- [ ] Memorystore vs self-hosted Redis? (saves ops, costs +$127/mo)
- [ ] Domain setup for Cloud Run (api.engrammic.com)

## Files

- `infra/` - Pulumi project
- `infra/__main__.py` - entrypoint
- `infra/components/` - modular components
- `context/brainstorm/2026-05-13-gcp-deployment-architecture.md` - full analysis
