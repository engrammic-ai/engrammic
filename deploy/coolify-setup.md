# Coolify Deployment Setup

## 1. Provision Server

Hetzner CX32 (8GB RAM, 4 vCPU) - Ubuntu 24.04

```bash
# Point DNS first (Coolify needs it for SSL)
api.deltaprime.ai    -> <server-ip>
coolify.deltaprime.ai -> <server-ip>  # optional, for dashboard
```

## 2. Install Coolify

SSH as root:

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

Takes ~5 min. Opens on port 8000 initially.

## 3. Initial Setup

1. Visit `http://<server-ip>:8000`
2. Create admin account
3. Add your server as a "localhost" destination
4. Set up wildcard domain or individual domains

## 4. Deploy Services

### Option A: Docker Compose (recommended)

In Coolify UI:
1. New Resource -> Docker Compose
2. Connect GitHub repo (delta-prime/context-service)
3. Set compose file path: `docker-compose.yml`
4. Add environment variables from `.env.example`
5. Deploy

### Option B: Individual Services

Deploy each as separate Coolify service for independent scaling:

| Service | Source | Notes |
|---------|--------|-------|
| context-service | GitHub repo | Build from Dockerfile |
| Postgres | One-click | Coolify managed |
| Redis | One-click | Coolify managed |
| Memgraph | Docker image `memgraph/memgraph-mage` | Manual config |
| Qdrant | Docker image `qdrant/qdrant` | Manual config |

## 5. Environment Variables

Set in Coolify UI under the service:

```
ENVIRONMENT=production
MEMGRAPH_HOST=<memgraph-service-name>
QDRANT_HOST=<qdrant-service-name>
REDIS_HOST=<redis-service-name>
POSTGRES_HOST=<postgres-service-name>
POSTGRES_USER=context
POSTGRES_PASSWORD=<generated>
ANTHROPIC_API_KEY=<your-key>
JINA_API_KEY=<your-key>
```

## 6. Volumes (Persistent Data)

Coolify auto-creates volumes. For manual Docker services (Memgraph, Qdrant), add:

```yaml
volumes:
  - memgraph-data:/var/lib/memgraph
  - qdrant-data:/qdrant/storage
```

## 7. Backups

Coolify UI -> Settings -> Backups
- Enable S3 backups (Cloudflare R2 is cheap: ~$0.015/GB)
- Schedule: daily for Postgres, weekly for volumes

## 8. Monitoring

Built-in at `https://coolify.deltaprime.ai`:
- Service status
- Container logs
- Resource usage
- Deploy history

## 9. Git Push Deploys

Once connected to GitHub:
1. Push to `main` -> auto-deploy
2. Or set specific branch for production

## Troubleshooting

```bash
# SSH into server
ssh root@<server-ip>

# Coolify logs
docker logs coolify -f

# Service logs
docker logs <service-name> -f

# Restart Coolify
docker restart coolify
```
