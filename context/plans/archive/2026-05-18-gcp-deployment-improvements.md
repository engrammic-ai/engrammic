# GCP Deployment Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden deployment infrastructure with distroless images, vulnerability scanning, production CI/CD, and StatefulHost health monitoring.

**Architecture:** Keep hybrid approach (Cloud Run for API, GCE StatefulHost for DBs). Add security hardening at build time (distroless, scanning) and reliability at runtime (health checks, auto-restart).

**Tech Stack:** Docker (distroless), Cloud Build, GitHub Actions, Pulumi (GCP compute health checks)

---

## File Structure

| File | Change | Purpose |
|------|--------|---------|
| `docker/Dockerfile.api` | Modify | Switch to distroless runtime |
| `cloudbuild.api.yaml` | Modify | Add vulnerability scanning step |
| `.github/workflows/deploy-prod.yml` | Create | Production deployment with manual approval |
| `infra/components/compute.py` | Modify | Add health checks to StatefulHost |

---

## Task 1: Switch Dockerfile.api to Distroless Runtime

**Files:**
- Modify: `docker/Dockerfile.api:19-55`

**Issue:** Distroless has no shell, but current entrypoint uses `/entrypoint.sh` for local gcloud credential handling. Cloud Run doesn't need this (uses service account auth). Solution: Use conditional entrypoint or Python-based init.

- [ ] **Step 1: Update runtime stage to distroless**

Replace lines 19-55 in `docker/Dockerfile.api`:

```dockerfile
# Stage 2: Runtime (distroless for minimal attack surface)
FROM gcr.io/distroless/python3-debian12:nonroot

WORKDIR /app

# Copy virtual environment from builder (primitives installed from PyPI)
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY pyproject.toml uv.lock README.md ./
COPY config/ /app/config/
COPY src/ /app/src/
COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/

# Set environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Distroless nonroot user is UID 65532
# No shell available - healthcheck must use different approach
EXPOSE 8000

# No HEALTHCHECK in distroless (no shell) - Cloud Run uses HTTP probes instead
# CMD uses exec form (no shell interpretation)
CMD ["python", "-m", "uvicorn", "context_service.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Build and test locally**

Run:
```bash
docker build -f docker/Dockerfile.api -t engrammic-api:distroless-test .
docker run --rm -p 8000:8000 engrammic-api:distroless-test
# In another terminal:
curl http://localhost:8000/health
```

Expected: Health endpoint returns 200 OK

- [ ] **Step 3: Verify image size reduction**

Run:
```bash
docker images engrammic-api:distroless-test --format "{{.Size}}"
```

Expected: ~50-80MB (down from ~150MB with python:slim)

- [ ] **Step 4: Commit**

```bash
git add docker/Dockerfile.api
git commit -m "feat(docker): switch API to distroless runtime for reduced attack surface"
```

---

## Task 2: Add Vulnerability Scanning to Cloud Build

**Files:**
- Modify: `cloudbuild.api.yaml`

- [ ] **Step 1: Update cloudbuild.api.yaml with scanning step**

Replace entire file:

```yaml
steps:
  # Build the image
  - id: 'build'
    name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - '${_IMAGE}:${SHORT_SHA}'
      - '-t'
      - '${_IMAGE}:latest'
      - '-f'
      - 'docker/Dockerfile.api'
      - '.'

  # Push to Artifact Registry (required before scanning)
  - id: 'push'
    name: 'gcr.io/cloud-builders/docker'
    args:
      - 'push'
      - '${_IMAGE}:${SHORT_SHA}'

  # Scan for vulnerabilities
  - id: 'scan'
    name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        gcloud artifacts docker images scan ${_IMAGE}:${SHORT_SHA} \
          --format='value(response.scan)' > /workspace/scan_id.txt
        gcloud artifacts docker images list-vulnerabilities \
          $(cat /workspace/scan_id.txt) \
          --format='table(vulnerability.effectiveSeverity,vulnerability.cvssScore,vulnerability.packageIssue.affectedPackage,vulnerability.packageIssue.fixedPackage)'
        # Fail on CRITICAL vulnerabilities
        CRITICAL_COUNT=$(gcloud artifacts docker images list-vulnerabilities \
          $(cat /workspace/scan_id.txt) \
          --format='value(vulnerability.effectiveSeverity)' | grep -c CRITICAL || true)
        if [ "$CRITICAL_COUNT" -gt 0 ]; then
          echo "CRITICAL vulnerabilities found - blocking deployment"
          exit 1
        fi

  # Tag as latest after scan passes
  - id: 'tag-latest'
    name: 'gcr.io/cloud-builders/docker'
    args:
      - 'push'
      - '${_IMAGE}:latest'

images:
  - '${_IMAGE}:${SHORT_SHA}'
  - '${_IMAGE}:latest'

substitutions:
  _IMAGE: 'europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-api'

options:
  logging: CLOUD_LOGGING_ONLY

serviceAccount: 'projects/engrammic/serviceAccounts/cloudbuild-dev@engrammic.iam.gserviceaccount.com'
```

- [ ] **Step 2: Test locally with gcloud**

Run:
```bash
gcloud builds submit --config=cloudbuild.api.yaml --substitutions=SHORT_SHA=$(git rev-parse --short HEAD)
```

Expected: Build completes, scan output shows vulnerability table, no CRITICAL blocks

- [ ] **Step 3: Commit**

```bash
git add cloudbuild.api.yaml
git commit -m "feat(ci): add vulnerability scanning to Cloud Build pipeline"
```

---

## Task 3: Create Production Deployment Workflow

**Files:**
- Create: `.github/workflows/deploy-prod.yml`

- [ ] **Step 1: Create production workflow with manual approval**

```yaml
name: Deploy Production

on:
  workflow_dispatch:
    inputs:
      confirm_deploy:
        description: 'Type "deploy" to confirm production deployment'
        required: true
        type: string

env:
  REGION: europe-north1
  PROJECT_ID: engrammic

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Validate deployment confirmation
        if: ${{ github.event.inputs.confirm_deploy != 'deploy' }}
        run: |
          echo "Deployment not confirmed. You must type 'deploy' to proceed."
          exit 1

  build-and-deploy:
    needs: validate
    runs-on: ubuntu-latest
    environment: production
    permissions:
      contents: read
      id-token: write

    steps:
      - uses: actions/checkout@v4

      - name: Authenticate to GCP
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}

      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v2

      - name: Build and scan API image
        run: |
          gcloud builds submit \
            --config=cloudbuild.api.yaml \
            --substitutions=SHORT_SHA=${{ github.sha }}

      - name: Build Beacon image
        run: |
          gcloud builds submit \
            --tag ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/engrammic/engrammic-beacon:${{ github.sha }} \
            --dockerfile docker/Dockerfile.beacon \
            --timeout 300s
          gcloud artifacts docker tags add \
            ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/engrammic/engrammic-beacon:${{ github.sha }} \
            ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/engrammic/engrammic-beacon:latest

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Setup Pulumi
        uses: pulumi/actions@v5

      - name: Deploy infrastructure
        run: |
          cd infra
          uv sync
          uv run pulumi up --stack prod --yes
        env:
          PULUMI_ACCESS_TOKEN: ${{ secrets.PULUMI_ACCESS_TOKEN }}

      - name: Run database migrations
        run: |
          wget -q https://dl.google.com/cloudsql/cloud_sql_proxy.linux.amd64 -O cloud_sql_proxy
          chmod +x cloud_sql_proxy
          ./cloud_sql_proxy -instances=${{ env.PROJECT_ID }}:${{ env.REGION }}:engrammic-prod=tcp:5432 &
          sleep 5
          uv sync
          uv run alembic upgrade head
        env:
          DATABASE_URL: postgresql://context:${{ secrets.POSTGRES_PASSWORD_PROD }}@localhost:5432/engrammic

      - name: Notify deployment complete
        run: |
          echo "Production deployment complete"
          echo "API: https://context.engrammic.io/"
          echo "Commit: ${{ github.sha }}"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy-prod.yml
git commit -m "feat(ci): add production deployment workflow with manual approval"
```

---

## Task 4: Add Health Checks to StatefulHost

**Files:**
- Modify: `infra/components/compute.py:232-264`

- [ ] **Step 1: Add health check resource to StatefulHost class**

Add after line 229 (before the Instance definition) in `infra/components/compute.py`:

```python
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
```

- [ ] **Step 2: Add instance group for health check target**

Add after the health check definition:

```python
        # Unmanaged instance group for health check binding
        self.instance_group = compute.InstanceGroup(
            f"{name}-instance-group",
            name=f"engrammic-{env}-stateful-group",
            zone=zone,
            instances=[self.instance.self_link],
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.instance]),
        )
```

- [ ] **Step 3: Add auto-healing policy via startup script improvement**

Update the startup script (around line 224) to add a systemd service for auto-restart:

```python
        # Add to startup_script before "echo Stateful host ready"
        # Insert this block:
        '''
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
'''
```

- [ ] **Step 4: Update register_outputs to export health check**

Update the `register_outputs` call at line 266:

```python
        self.register_outputs({
            "instance_id": self.instance.id,
            "instance_name": self.instance.name,
            "internal_ip": self.instance.network_interfaces[0].network_ip,
            "health_check_id": self.health_check.id,
            "instance_group_id": self.instance_group.id,
        })
```

- [ ] **Step 5: Run pulumi preview**

Run:
```bash
cd infra && uv run pulumi preview --stack dev
```

Expected: Shows health check and instance group will be created

- [ ] **Step 6: Commit**

```bash
git add infra/components/compute.py
git commit -m "feat(infra): add health checks and auto-restart to StatefulHost"
```

---

## Verification

1. **Local Dockerfile test:**
   ```bash
   docker build -f docker/Dockerfile.api -t test:distroless .
   docker run --rm -p 8000:8000 test:distroless
   curl localhost:8000/health
   ```

2. **Cloud Build scan test:**
   ```bash
   gcloud builds submit --config=cloudbuild.api.yaml --substitutions=SHORT_SHA=test123
   ```

3. **Pulumi preview (don't apply without approval):**
   ```bash
   cd infra && uv run pulumi preview --stack beta
   ```

4. **GitHub Actions:** The prod workflow requires manual trigger with "deploy" confirmation - test by going to Actions > Deploy Production > Run workflow

---

## Notes

- Distroless removes shell access - debugging requires `docker exec` with debug image variant
- Vulnerability scanning adds ~30s to build time
- Production workflow requires GitHub environment "production" to be configured with reviewers
- StatefulHost health check monitors Memgraph port 7687 - add more checks if needed
