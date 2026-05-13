# GCP Deployment Architecture Brainstorm

**Date**: 2026-05-13  
**Mode**: Architecture  
**Budget**: $25k GCP credits

## Summary

Memgraph has no managed GCP option, which anchors the architecture: you need a GCE VM regardless. Given this constraint, the most cost-effective path is a single GCE VM running Docker Compose for all stateful services, with Cloud Run for the stateless API layer. Estimated burn: $400-800/mo, giving 31-62 months runway.

## Key Insights

1. **Binding constraint**: Memgraph requires a VM. Once you have that, running everything else on it is near-zero marginal ops cost.

2. **IaC tool choice**: OpenTofu or Pulumi (Python). Terraform works but OpenTofu is OSS-friendly. Pulumi fits the Python-focused team. GCP Deployment Manager is deprecated (March 2026).

3. **Cost optimization**: Self-host Redis/Postgres initially (saves ~$200/mo vs managed). Cloud Run for API (pay-per-request). Spot VMs only for truly stateless workloads.

4. **Dagger is not IaC**: It's CI/CD focused. Don't use it for infrastructure provisioning.

## Recommended Architecture

```
Internet
    |
    | HTTPS (443)
    v
+------------------+
| Cloud HTTPS LB   |  (managed SSL, Cloud Armor optional)
+--------+---------+
         |
         v
+------------------+          +--------------------------------+
| Cloud Run        |          |  GCE: e2-standard-8 (32GB)     |
|                  |          |  Private IP only               |
|  context-service |   VPC    |                                |
|  (FastAPI+MCP)   +----------+  Docker Compose:               |
|  min=1 max=10    |  Direct  |  - Memgraph  (4GB)             |
|  2vCPU 4GiB      |  Conn.   |  - Qdrant    (2GB)             |
+------------------+          |  - Redis     (512MB)           |
                              |  - Postgres  (1GB)             |
+------------------+          |  - Dagster   (3GB)             |
| Cloud NAT        |          |  - OTEL collector              |
| (outbound only)  +----------+                                |
+------------------+          |  Persistent Disks:             |
                              |  - memgraph-pd  100GB SSD      |
+------------------+          |  - qdrant-pd    100GB SSD      |
| Secret Manager   |          |  - postgres-pd   50GB SSD      |
+------------------+          +--------------------------------+
                                          |
+------------------+                      | nightly snapshots
| Cloud Storage    |<---------------------+
| engrammic-backups|
+------------------+
```

## Cost Estimate

| Component | Spec | Monthly |
|-----------|------|---------|
| GCE e2-standard-8 | 8 vCPU, 32GB | ~$280 |
| Persistent disks | 270GB SSD | ~$45 |
| Cloud Run | min=1, low traffic | ~$30-50 |
| Cloud NAT + networking | | ~$20 |
| Cloud Storage | backups | ~$5 |
| **Total (self-hosted DBs)** | | **~$380-400/mo** |

**With managed services (optional):**
- Cloud SQL Postgres: +$115/mo
- Memorystore Redis: +$127/mo

At $400/mo = **62 months runway** on $25k  
At $800/mo = **31 months runway** on $25k

## IaC Tool Decision

| Criteria | OpenTofu | Pulumi (Python) | Terraform |
|----------|----------|-----------------|-----------|
| License | MPL 2.0 (OSS) | Apache 2.0 | BSL 1.1 |
| GCP support | Excellent | Good (wraps TF) | Excellent |
| Learning curve | Medium (HCL) | Low (Python) | Medium (HCL) |
| Team fit | Good | Best | Good |

**Recommendation**: **Pulumi (Python)** for the Python-focused solo founder. Falls back to OpenTofu if you hire DevOps with TF experience.

## Hybrid Migration Path

### Phase 1: Now (this week)
- GCE VM + Docker Compose via gcloud script
- Existing `deploy/` scripts adapt directly
- Gets partners running immediately
- No new tooling

### Phase 2: Post-seed (before 10th customer)
- Introduce Pulumi/OpenTofu
- Codify: GCE instance, VPC, IAM, Secret Manager, GCS
- Add Cloud Run for context-service API
- Migrate compose stack under IaC control

### Phase 3: Scale (Series A)
- Evaluate GKE Autopilot if horizontal scaling needed
- Memgraph HA if data criticality warrants
- Multi-region for compliance customers

## Security Model

1. **No public IPs** on compute (Cloud Run + private GCE)
2. **IAP tunnel** for SSH access only
3. **Secret Manager** for all credentials
4. **Workload Identity** for Vertex AI (no service account keys)
5. **Cloud Armor** on LB before public launch

## Backup Strategy

| Store | Method | Frequency | Retention |
|-------|--------|-----------|-----------|
| Postgres | pg_dump to GCS | Daily | 30 days |
| Memgraph | DUMP DATABASE to GCS | Daily | 30 days |
| Qdrant | Snapshot API to GCS | Weekly | 90 days |
| Redis | AOF on disk | Continuous | N/A (cache) |

## CI/CD

```
GitHub push -> GitHub Actions -> build image -> Artifact Registry -> deploy
```

- Use GitHub OIDC + Workload Identity Federation (no long-lived keys)
- `gcloud run deploy` for Cloud Run
- SSH + docker compose for GCE (or rsync existing scripts)

## Next Steps

1. [ ] Create GCP project, enable APIs
2. [ ] Set up VPC + Cloud NAT + firewall rules
3. [ ] Create GCE instance with Docker + Compose
4. [ ] Migrate existing compose file (env var substitution)
5. [ ] Set up Secret Manager, migrate credentials
6. [ ] Configure GitHub Actions OIDC
7. [ ] Add Cloud Run for context-service
8. [ ] Set up backup jobs to GCS

## Open Questions

- Cloud SQL vs self-hosted Postgres? (ops vs cost tradeoff)
- SigNoz placement: keep external or move to GCP VM?
- Cloud Run vs GCE for context-service? (latency testing needed)

## References

- [OpenTofu vs Terraform Licensing](https://oneuptime.com/blog/post/2026-03-20-opentofu-mpl-terraform-bsl-licensing/)
- [GCP Deployment Manager Deprecation](https://cloud.google.com/deployment-manager/docs/deprecations)
- [Crossplane GCP Provider](https://github.com/crossplane-contrib/provider-upjet-gcp)
