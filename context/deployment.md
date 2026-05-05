# Deployment Guide

## Current Setup (Demo/Pilot Phase)

Single VPS with Coolify. Cost: ~$15-20/mo.

### Stack
- Hetzner CX32 (8GB RAM, 4 vCPU)
- Coolify (self-hosted PaaS)
- Auto-HTTPS, git push deploys, web dashboard

### Setup
See `deploy/coolify-setup.md` for full walkthrough.

```bash
# Install Coolify (as root on fresh Ubuntu 24.04)
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash

# Then configure via web UI at http://<server-ip>:8000
```

### Daily Operations
- Dashboard: `https://coolify.deltaprime.ai`
- Deploy: push to `main` (auto) or click "Deploy" in UI
- Logs: Coolify UI or `docker logs <service>`

### Resource Requirements
| Service   | Memory | CPU  |
|-----------|--------|------|
| App       | 512MB  | 0.5  |
| Memgraph  | 2GB    | 1.0  |
| Qdrant    | 1GB    | 0.5  |
| Redis     | 256MB  | 0.1  |
| Postgres  | 256MB  | 0.25 |
| **Total** | ~4GB   | ~2.5 |

---

## Scaling Path

### Phase 1: Vertical (current)
Single box, bump to CX42 (16GB) or CX52 (32GB) as needed. Good up to ~10 concurrent users.

### Phase 2: Managed Services
When operational burden exceeds cost savings:
- App -> Cloud Run or Fly.io
- Memgraph -> Memgraph Cloud ($99/mo starter)
- Qdrant -> Qdrant Cloud (free tier, then $25/mo)
- Redis -> Upstash (serverless, pay-per-request)
- Postgres -> Neon or Supabase (free tier available)

### Phase 3: Kubernetes (10+ customers, need HA)

#### Why K8s
- Horizontal scaling per service
- Rolling deployments with zero downtime
- Auto-healing, resource quotas
- Multi-region possible

#### Managed K8s Options
| Provider       | Min Cost/mo | Notes                          |
|----------------|-------------|--------------------------------|
| Hetzner K8s    | ~$30        | Cheapest, EU only              |
| DigitalOcean   | ~$48        | Simple, good docs              |
| GKE Autopilot  | ~$70        | Best DX, auto node management  |
| EKS            | ~$75+       | AWS ecosystem lock-in          |

#### K8s Architecture (future)
```
                    ┌─────────────┐
                    │   Ingress   │
                    │  (Traefik)  │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────▼────┐      ┌─────▼─────┐     ┌─────▼─────┐
    │   App   │      │    App    │     │    App    │
    │ (HPA)   │      │  (HPA)    │     │  (HPA)    │
    └────┬────┘      └─────┬─────┘     └─────┬─────┘
         │                 │                 │
         └─────────────────┼─────────────────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │                      │                      │
┌───▼───┐            ┌─────▼─────┐          ┌─────▼─────┐
│Memgraph│           │  Qdrant   │          │  Postgres │
│(StatefulSet)       │(StatefulSet)         │ (managed) │
└───────┘            └───────────┘          └───────────┘
```

#### Helm Charts Needed
- Custom chart for context-service app
- Bitnami Redis
- Qdrant official helm chart
- Memgraph (custom, no official chart yet)

#### When to Move to K8s
- Multiple paying customers needing SLAs
- Need multi-region or HA
- Team > 3 engineers deploying independently
- Monthly cloud spend > $500 (operational overhead justified)

---

## CI/CD (Future)

When ready, add GitHub Actions:
```yaml
# .github/workflows/deploy.yml
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: ./deploy/deploy.sh ${{ secrets.SERVER_IP }} ${{ secrets.DOMAIN }}
```

---

## Alternatives Explored

| Tool | Cost | DX | Limitations | Best For |
|------|------|-----|-------------|----------|
| **Coolify** | Free + VPS (~$15/mo) | Excellent (web UI, git push) | 4-8hr setup; needs maintenance | Full-stack with DBs; Heroku DX on own infra |
| **Dokku** | Free + VPS | Good (CLI, Heroku-like) | No web UI; no monitoring | Minimalists; single-app |
| **Kamal** | Free + VPS | Good for Docker devs | No monitoring; manual DB backups | Multi-server; escaping cloud lock-in |
| **CapRover** | Free + VPS | Good (web UI) | Less polish than Coolify | Multi-app servers |

### Recommendation

**Current approach (manual Docker Compose + Caddy)** is right for pilot phase - minimal moving parts, full control.

**Next step when needed:** Coolify for web UI monitoring (useful for non-technical cofounders) and easier deploys. One-click Redis/Postgres, manual compose for Memgraph/Qdrant.

**Skip Kamal** until multi-server orchestration is needed - overkill for single VPS.
