# GCP Deployment Inventory

## VMs

| Name | Purpose | Machine Type | GPU | Zone | Status |
|------|---------|--------------|-----|------|--------|
| engrammic-beta-stateful | Beta app | e2-standard-4 | - | europe-north1-a | RUNNING |
| engrammic-beta-tei | Beta embeddings | n1-standard-4 | T4 | europe-west1-b | RUNNING |
| engrammic-dev-signoz | Observability | e2-standard-4 | - | europe-north1-a | RUNNING |
| engrammic-benchmark-benchmark-devbox | Benchmark dev | n2-standard-16 | - | us-west1-b | RUNNING |
| engrammic-benchmark-benchmark-gpu | Benchmark GPU | n1-standard-8 | T4 | us-west1-b | RUNNING |
| engrammic-dev-box | Dev environment | n1-highmem-8 | - | europe-north1-a | TERMINATED |
| engrammic-dev-box-us | Dev environment (US) | e2-standard-8 | - | us-central1-a | TERMINATED |

## Services

| Service | Type | Region | Status |
|---------|------|--------|--------|
| engrammic-beta | PostgreSQL 16 | europe-north1 | RUNNABLE |
| Artifact Registry | engrammic/engrammic, engrammic/releases | - | - |

## Access

- **Tailscale**: VMs on tailnet, SSH via `ssh engrammic-dev-box`
- **GCP Console**: project `engrammic-beta`
- **GitHub Actions**: WIF via `gha-deployer` SA

## Notes

<!-- Add deployment notes, changes, issues here -->
