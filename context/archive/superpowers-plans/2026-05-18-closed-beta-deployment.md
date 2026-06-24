# Closed Beta Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Engrammic for design partner closed beta on GCP with Cloud SQL, beacon telemetry service, and GitHub Actions CI/CD.

**Architecture:** Cloud Run for API and Beacon services, Cloud SQL for managed Postgres, StatefulHost GCE for Memgraph/Qdrant/Redis only. GitHub Actions workflow triggers on `beta` branch push, builds images, runs Pulumi, executes migrations.

**Tech Stack:** Python 3.13, FastAPI, Pulumi (GCP), asyncpg, GitHub Actions, Cloud SQL, Cloud Run v2

**Spec:** `docs/superpowers/specs/2026-05-18-closed-beta-deployment-design.md`

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `docker/Dockerfile.api` | API service container (moved from root) |
| `docker/Dockerfile.beacon` | Beacon telemetry service container |
| `src/beacon_service/__init__.py` | Package init |
| `src/beacon_service/main.py` | FastAPI app with `/v1/beacon` endpoint |
| `src/beacon_service/config.py` | Environment config for beacon |
| `alembic/versions/0006_add_beacon_tables.py` | beacon_secrets and beacon_events tables |
| `infra/Pulumi.beta.yaml` | Beta stack configuration |
| `infra/components/cloudsql.py` | Cloud SQL Postgres component |
| `infra/components/beacon.py` | Beacon Cloud Run service component |
| `infra/components/__init__.py` | Update exports |
| `infra/components/compute.py` | Remove Postgres disk (configurable) |
| `infra/__main__.py` | Add Cloud SQL + beacon service |
| `.github/workflows/deploy-beta.yml` | CI/CD workflow |

---

### Task 1: Docker Directory Setup

**Files:**
- Create: `docker/Dockerfile.api`
- Move: `Dockerfile` -> `docker/Dockerfile.api`

- [ ] **Step 1: Create docker directory and move Dockerfile**

```bash
mkdir -p docker
git mv Dockerfile docker/Dockerfile.api
```

- [ ] **Step 2: Update Dockerfile.api build context paths**

The existing Dockerfile uses `context-service/` paths (built from monorepo root). Update to build from repo root with correct context:

In `docker/Dockerfile.api`, change:
- `COPY context-service/pyproject.toml` -> `COPY pyproject.toml`
- `COPY context-service/uv.lock` -> `COPY uv.lock`
- `COPY context-service/README.md` -> `COPY README.md`
- `COPY context-service/config/` -> `COPY config/`
- `COPY context-service/src/` -> `COPY src/`
- `COPY context-service/alembic.ini` -> `COPY alembic.ini`
- `COPY context-service/alembic/` -> `COPY alembic/`
- `COPY context-service/scripts/entrypoint.sh` -> `COPY scripts/entrypoint.sh`

- [ ] **Step 3: Verify build works locally**

```bash
docker build -f docker/Dockerfile.api -t engrammic-api:test .
```

Expected: Build completes successfully.

- [ ] **Step 4: Commit**

```bash
git add docker/Dockerfile.api
git commit -m "refactor: move Dockerfile to docker/Dockerfile.api"
```

---

### Task 2: Beacon Service - Core Implementation

**Files:**
- Create: `src/beacon_service/__init__.py`
- Create: `src/beacon_service/config.py`
- Create: `src/beacon_service/main.py`

- [ ] **Step 1: Create beacon_service package init**

```python
# src/beacon_service/__init__.py
"""Beacon telemetry service for self-hosted Engrammic instances."""
```

- [ ] **Step 2: Create beacon config module**

```python
# src/beacon_service/config.py
"""Configuration for beacon service."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BeaconConfig:
    """Beacon service configuration from environment."""

    database_url: str
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> BeaconConfig:
        """Load configuration from environment variables."""
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is required")

        return cls(
            database_url=database_url,
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
```

- [ ] **Step 3: Create beacon main.py with FastAPI app**

```python
# src/beacon_service/main.py
"""Beacon telemetry receiver service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import structlog
from fastapi import FastAPI, Header, HTTPException, Request

from beacon_service.config import BeaconConfig

log = structlog.get_logger()

SECRET_TO_SILO: dict[str, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection pool lifecycle."""
    config = BeaconConfig.from_env()
    app.state.pool = await asyncpg.create_pool(config.database_url)

    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch("SELECT secret, silo_id FROM beacon_secrets")
        for row in rows:
            SECRET_TO_SILO[row["secret"]] = str(row["silo_id"])

    log.info("beacon_started", secrets_loaded=len(SECRET_TO_SILO))
    yield
    await app.state.pool.close()


app = FastAPI(title="Engrammic Beacon", lifespan=lifespan)


@app.post("/v1/beacon")
async def receive_beacon(
    request: Request,
    x_beacon_secret: str = Header(..., alias="X-Beacon-Secret"),
) -> dict[str, str]:
    """Receive and store telemetry beacon from self-hosted instances."""
    silo_id = SECRET_TO_SILO.get(x_beacon_secret)
    if not silo_id:
        raise HTTPException(status_code=401, detail="Invalid beacon secret")

    payload: dict[str, Any] = await request.json()
    event_type = payload.get("event_type", "unknown")

    async with request.app.state.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO beacon_events (silo_id, event_type, payload)
            VALUES ($1, $2, $3)
            """,
            silo_id,
            event_type,
            payload,
        )

    log.info("beacon_received", silo_id=silo_id, event_type=event_type)
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}
```

- [ ] **Step 4: Commit**

```bash
git add src/beacon_service/
git commit -m "feat: add beacon telemetry service"
```

---

### Task 3: Beacon Dockerfile

**Files:**
- Create: `docker/Dockerfile.beacon`

- [ ] **Step 1: Create Dockerfile.beacon**

```dockerfile
# docker/Dockerfile.beacon
# Minimal beacon service image

FROM python:3.13-slim AS builder

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Beacon only needs asyncpg, fastapi, structlog
RUN uv pip install --system asyncpg fastapi uvicorn structlog

FROM python:3.13-slim

WORKDIR /app

RUN groupadd -g 1000 engrammic && useradd -u 1000 -g engrammic -m engrammic

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY src/beacon_service/ /app/beacon_service/

ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

USER engrammic

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["python", "-m", "uvicorn", "beacon_service.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 2: Verify build**

```bash
docker build -f docker/Dockerfile.beacon -t engrammic-beacon:test .
```

Expected: Build completes successfully.

- [ ] **Step 3: Commit**

```bash
git add docker/Dockerfile.beacon
git commit -m "feat: add Dockerfile for beacon service"
```

---

### Task 4: Alembic Migration for Beacon Tables

**Files:**
- Create: `alembic/versions/0006_add_beacon_tables.py`

- [ ] **Step 1: Create migration file**

```python
# alembic/versions/0006_add_beacon_tables.py
"""add beacon tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # beacon_secrets: maps shared secrets to silos
    op.create_table(
        "beacon_secrets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column("secret", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("silo_id"),
        sa.UniqueConstraint("secret"),
    )
    op.create_index("idx_beacon_secrets_secret", "beacon_secrets", ["secret"])

    # beacon_events: stores received telemetry
    op.create_table(
        "beacon_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_beacon_silo_time", "beacon_events", ["silo_id", "received_at"])


def downgrade() -> None:
    op.drop_index("idx_beacon_silo_time", table_name="beacon_events")
    op.drop_table("beacon_events")
    op.drop_index("idx_beacon_secrets_secret", table_name="beacon_secrets")
    op.drop_table("beacon_secrets")
```

- [ ] **Step 2: Verify migration syntax**

```bash
uv run python -c "from alembic.versions import 0006_add_beacon_tables; print('OK')"
```

Expected: `OK` (no syntax errors)

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/0006_add_beacon_tables.py
git commit -m "feat: add beacon_secrets and beacon_events tables migration"
```

---

### Task 5: Pulumi Cloud SQL Component

**Files:**
- Create: `infra/components/cloudsql.py`

- [ ] **Step 1: Create Cloud SQL component**

```python
# infra/components/cloudsql.py
"""Cloud SQL Postgres instance for managed database."""

import pulumi
from pulumi_gcp import sql


class CloudSQLPostgres(pulumi.ComponentResource):
    """Managed Cloud SQL Postgres instance."""

    def __init__(
        self,
        name: str,
        network_id: pulumi.Input[str],
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:cloudsql:CloudSQLPostgres", name, None, opts)

        config = pulumi.Config()
        gcp_config = pulumi.Config("gcp")
        env = config.require("environment")
        region = gcp_config.require("region")

        tier = config.get("cloudsql_tier") or "db-f1-micro"
        disk_size = int(config.get("cloudsql_disk_size") or "20")
        ha_enabled = config.get_bool("cloudsql_ha") or False

        self.instance = sql.DatabaseInstance(
            f"{name}-instance",
            name=f"engrammic-{env}",
            database_version="POSTGRES_16",
            region=region,
            deletion_protection=env == "prod",
            settings=sql.DatabaseInstanceSettingsArgs(
                tier=tier,
                disk_size=disk_size,
                disk_type="PD_SSD",
                disk_autoresize=True,
                availability_type="REGIONAL" if ha_enabled else "ZONAL",
                backup_configuration=sql.DatabaseInstanceSettingsBackupConfigurationArgs(
                    enabled=True,
                    start_time="03:00",
                    point_in_time_recovery_enabled=True,
                    transaction_log_retention_days=7,
                    backup_retention_settings=sql.DatabaseInstanceSettingsBackupConfigurationBackupRetentionSettingsArgs(
                        retained_backups=7,
                    ),
                ),
                ip_configuration=sql.DatabaseInstanceSettingsIpConfigurationArgs(
                    ipv4_enabled=False,
                    private_network=network_id,
                    enable_private_path_for_google_cloud_services=True,
                ),
                maintenance_window=sql.DatabaseInstanceSettingsMaintenanceWindowArgs(
                    day=7,
                    hour=4,
                ),
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.database = sql.Database(
            f"{name}-database",
            name="engrammic",
            instance=self.instance.name,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.user = sql.User(
            f"{name}-user",
            name="context",
            instance=self.instance.name,
            password=config.require_secret("postgres_password"),
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.register_outputs({
            "instance_name": self.instance.name,
            "connection_name": self.instance.connection_name,
            "private_ip": self.instance.private_ip_address,
        })
```

- [ ] **Step 2: Commit**

```bash
git add infra/components/cloudsql.py
git commit -m "feat: add Cloud SQL Postgres Pulumi component"
```

---

### Task 6: Pulumi Beacon Service Component

**Files:**
- Create: `infra/components/beacon.py`

- [ ] **Step 1: Create Beacon Cloud Run component**

```python
# infra/components/beacon.py
"""Cloud Run v2 service for beacon telemetry receiver."""

import pulumi
from pulumi_gcp import cloudrunv2


class BeaconServiceRun(pulumi.ComponentResource):
    """Cloud Run v2 service for the beacon telemetry receiver."""

    def __init__(
        self,
        name: str,
        vpc_connector_id: pulumi.Input[str],
        service_account_email: pulumi.Input[str],
        image: str,
        database_url: pulumi.Input[str],
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:cloudrun:BeaconServiceRun", name, None, opts)

        config = pulumi.Config()
        gcp_config = pulumi.Config("gcp")
        env = config.require("environment")
        region = gcp_config.require("region")

        self.service = cloudrunv2.Service(
            f"{name}-service",
            name=f"engrammic-{env}-beacon",
            location=region,
            template=cloudrunv2.ServiceTemplateArgs(
                service_account=service_account_email,
                scaling=cloudrunv2.ServiceTemplateScalingArgs(
                    min_instance_count=0,
                    max_instance_count=2,
                ),
                vpc_access=cloudrunv2.ServiceTemplateVpcAccessArgs(
                    connector=vpc_connector_id,
                    egress="ALL_TRAFFIC",
                ),
                containers=[
                    cloudrunv2.ServiceTemplateContainerArgs(
                        image=image,
                        resources=cloudrunv2.ServiceTemplateContainerResourcesArgs(
                            limits={"cpu": "1", "memory": "512Mi"},
                        ),
                        envs=[
                            cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="DATABASE_URL",
                                value=database_url,
                            ),
                        ],
                        startup_probe=cloudrunv2.ServiceTemplateContainerStartupProbeArgs(
                            http_get=cloudrunv2.ServiceTemplateContainerStartupProbeHttpGetArgs(
                                path="/health",
                            ),
                            initial_delay_seconds=5,
                            period_seconds=10,
                            timeout_seconds=5,
                            failure_threshold=3,
                        ),
                        liveness_probe=cloudrunv2.ServiceTemplateContainerLivenessProbeArgs(
                            http_get=cloudrunv2.ServiceTemplateContainerLivenessProbeHttpGetArgs(
                                path="/health",
                            ),
                            period_seconds=30,
                        ),
                    )
                ],
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.register_outputs({
            "service_url": self.service.uri,
            "service_name": self.service.name,
        })
```

- [ ] **Step 2: Commit**

```bash
git add infra/components/beacon.py
git commit -m "feat: add beacon Cloud Run Pulumi component"
```

---

### Task 7: Update Pulumi Components Init

**Files:**
- Modify: `infra/components/__init__.py`

- [ ] **Step 1: Read current __init__.py**

```bash
cat infra/components/__init__.py
```

- [ ] **Step 2: Add new exports**

Update `infra/components/__init__.py`:

```python
# infra/components/__init__.py
"""Pulumi component resources for Engrammic infrastructure."""

from components.beacon import BeaconServiceRun
from components.cloudrun import ContextServiceRun
from components.cloudsql import CloudSQLPostgres
from components.compute import StatefulHost
from components.iam import IAMStack
from components.network import NetworkStack
from components.secrets import SecretsStack
from components.storage import StorageStack

__all__ = [
    "BeaconServiceRun",
    "CloudSQLPostgres",
    "ContextServiceRun",
    "IAMStack",
    "NetworkStack",
    "SecretsStack",
    "StatefulHost",
    "StorageStack",
]
```

- [ ] **Step 3: Commit**

```bash
git add infra/components/__init__.py
git commit -m "feat: export Cloud SQL and beacon components"
```

---

### Task 8: Update StatefulHost to Make Postgres Disk Optional

**Files:**
- Modify: `infra/components/compute.py`

- [ ] **Step 1: Make Postgres disk conditional on config**

In `infra/components/compute.py`, update `__init__` to check if Cloud SQL is used:

After `disk_size_qdrant = ...` line, add:
```python
use_cloudsql = config.get_bool("use_cloudsql") or False
```

Wrap the postgres_disk creation in a conditional:
```python
if not use_cloudsql:
    self.postgres_disk = compute.Disk(
        f"{name}-postgres-disk",
        name=f"engrammic-{env}-postgres",
        size=disk_size_postgres,
        type="pd-ssd",
        zone=zone,
        opts=pulumi.ResourceOptions(parent=self),
    )
```

Update `attached_disks` to conditionally include postgres:
```python
attached_disks = [
    compute.InstanceAttachedDiskArgs(source=self.memgraph_disk.self_link),
    compute.InstanceAttachedDiskArgs(source=self.qdrant_disk.self_link),
]
if not use_cloudsql:
    attached_disks.append(compute.InstanceAttachedDiskArgs(source=self.postgres_disk.self_link))
```

Update startup script to conditionally mount postgres disk (only if `not use_cloudsql`).

- [ ] **Step 2: Commit**

```bash
git add infra/components/compute.py
git commit -m "feat: make Postgres disk optional when using Cloud SQL"
```

---

### Task 9: Pulumi Beta Stack Config

**Files:**
- Create: `infra/Pulumi.beta.yaml`

- [ ] **Step 1: Create beta stack configuration**

```yaml
# infra/Pulumi.beta.yaml
config:
  gcp:project: engrammic
  gcp:region: europe-north1
  gcp:zone: europe-north1-a
  engrammic-infra:environment: beta
  # StatefulHost (Memgraph, Qdrant, Redis only)
  engrammic-infra:instance_type: e2-standard-2
  engrammic-infra:use_spot: "false"
  engrammic-infra:disk_size_memgraph: "50"
  engrammic-infra:disk_size_qdrant: "50"
  engrammic-infra:use_cloudsql: "true"
  # Cloud SQL Postgres
  engrammic-infra:cloudsql_tier: db-f1-micro
  engrammic-infra:cloudsql_disk_size: "20"
  engrammic-infra:cloudsql_ha: "false"
  # Cloud Run
  engrammic-infra:min_cloudrun_instances: "1"
```

- [ ] **Step 2: Commit**

```bash
git add infra/Pulumi.beta.yaml
git commit -m "feat: add Pulumi beta stack configuration"
```

---

### Task 10: Update Pulumi Main to Support Cloud SQL and Beacon

**Files:**
- Modify: `infra/__main__.py`

- [ ] **Step 1: Update __main__.py with conditional Cloud SQL and beacon**

```python
"""Engrammic infrastructure entrypoint."""

import pulumi
from components import (
    BeaconServiceRun,
    CloudSQLPostgres,
    ContextServiceRun,
    IAMStack,
    NetworkStack,
    SecretsStack,
    StatefulHost,
    StorageStack,
)

config = pulumi.Config()
use_cloudsql = config.get_bool("use_cloudsql") or False

# IAM first - service accounts needed by other resources
iam = IAMStack("engrammic-iam")

# Network - VPC, subnets, NAT
network = NetworkStack("engrammic-network")

# Storage - backup buckets (IAM binding needs stateful host SA)
storage = StorageStack("engrammic-storage", stateful_host_email=iam.stateful_host.email)

# Secrets - Secret Manager resources
secrets = SecretsStack("engrammic-secrets")

# Stateful host - GCE instance for Memgraph, Qdrant, Redis (+ Postgres if not using Cloud SQL)
stateful_host = StatefulHost(
    "engrammic-stateful",
    network=network.vpc,
    subnet=network.private_subnet,
    service_account_email=iam.stateful_host.email,
)

# Cloud SQL (if enabled)
cloudsql = None
postgres_host = stateful_host.instance.network_interfaces[0].network_ip
if use_cloudsql:
    cloudsql = CloudSQLPostgres(
        "engrammic-cloudsql",
        network_id=network.vpc.id,
    )
    postgres_host = cloudsql.instance.private_ip_address

# Cloud Run API deployment
context_service = ContextServiceRun(
    "engrammic-context-service",
    vpc_id=network.vpc.id,
    connector_subnet_id=network.vpc_connector.name,
    service_account_email=iam.context_service_run.email,
    image="europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-api:latest",
    env_vars={
        "ENVIRONMENT": config.require("environment"),
        "MEMGRAPH_HOST": stateful_host.instance.network_interfaces[0].network_ip,
        "QDRANT_HOST": stateful_host.instance.network_interfaces[0].network_ip,
        "REDIS_HOST": stateful_host.instance.network_interfaces[0].network_ip,
        "POSTGRES_HOST": postgres_host,
        "POSTGRES_USER": "context",
        "POSTGRES_DATABASE": "engrammic",
        "VERTEX_PROJECT_ID": "engrammic",
        "VERTEX_LOCATION": "europe-north1",
    },
    secrets={
        "POSTGRES_PASSWORD": secrets.secrets["postgres-password"].id,
        "MEMGRAPH_PASSWORD": secrets.secrets["memgraph-password"].id,
        "WORKOS_API_KEY": secrets.secrets["workos-api-key"].id,
        "ANTHROPIC_API_KEY": secrets.secrets["anthropic-api-key"].id,
        "OPENAI_API_KEY": secrets.secrets["openai-api-key"].id,
        "GOOGLE_API_KEY": secrets.secrets["google-api-key"].id,
    },
)

# Beacon service (if Cloud SQL enabled - beta/prod only)
beacon_service = None
if use_cloudsql:
    database_url = pulumi.Output.all(
        postgres_host,
        config.require_secret("postgres_password"),
    ).apply(lambda args: f"postgresql://context:{args[1]}@{args[0]}:5432/engrammic")

    beacon_service = BeaconServiceRun(
        "engrammic-beacon",
        vpc_connector_id=context_service.connector.id,
        service_account_email=iam.context_service_run.email,
        image="europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-beacon:latest",
        database_url=database_url,
    )

# Exports
pulumi.export("vpc_id", network.vpc.id)
pulumi.export("stateful_host_ip", stateful_host.instance.network_interfaces[0].network_ip)
pulumi.export("backup_bucket_name", storage.backup_bucket.name)
pulumi.export(
    "service_account_emails",
    {
        "compute": iam.stateful_host.email,
        "cloudrun": iam.context_service_run.email,
    },
)
pulumi.export("api_url", context_service.service.uri)

if cloudsql:
    pulumi.export("cloudsql_connection_name", cloudsql.instance.connection_name)
    pulumi.export("cloudsql_private_ip", cloudsql.instance.private_ip_address)

if beacon_service:
    pulumi.export("beacon_url", beacon_service.service.uri)
```

- [ ] **Step 2: Verify Pulumi preview**

```bash
cd infra && uv run pulumi preview --stack dev
```

Expected: No errors, preview shows existing resources (dev doesn't use Cloud SQL).

- [ ] **Step 3: Commit**

```bash
git add infra/__main__.py
git commit -m "feat: add Cloud SQL and beacon service to Pulumi main"
```

---

### Task 11: GitHub Actions Deploy Workflow

**Files:**
- Create: `.github/workflows/deploy-beta.yml`

- [ ] **Step 1: Create deploy-beta.yml**

```yaml
# .github/workflows/deploy-beta.yml
name: Deploy Beta

on:
  push:
    branches: [beta]

env:
  REGION: europe-north1
  REGISTRY: europe-north1-docker.pkg.dev/engrammic/engrammic

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
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

      - name: Configure Docker
        run: gcloud auth configure-docker ${{ env.REGION }}-docker.pkg.dev

      - name: Build and push API image
        run: |
          docker build -f docker/Dockerfile.api -t ${{ env.REGISTRY }}/engrammic-api:${{ github.sha }} .
          docker push ${{ env.REGISTRY }}/engrammic-api:${{ github.sha }}
          docker tag ${{ env.REGISTRY }}/engrammic-api:${{ github.sha }} ${{ env.REGISTRY }}/engrammic-api:latest
          docker push ${{ env.REGISTRY }}/engrammic-api:latest

      - name: Build and push Beacon image
        run: |
          docker build -f docker/Dockerfile.beacon -t ${{ env.REGISTRY }}/engrammic-beacon:${{ github.sha }} .
          docker push ${{ env.REGISTRY }}/engrammic-beacon:${{ github.sha }}
          docker tag ${{ env.REGISTRY }}/engrammic-beacon:${{ github.sha }} ${{ env.REGISTRY }}/engrammic-beacon:latest
          docker push ${{ env.REGISTRY }}/engrammic-beacon:latest

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Setup Pulumi
        uses: pulumi/actions@v5

      - name: Deploy infrastructure
        run: |
          cd infra
          uv sync
          uv run pulumi up --stack beta --yes
        env:
          PULUMI_ACCESS_TOKEN: ${{ secrets.PULUMI_ACCESS_TOKEN }}

      - name: Run database migrations
        run: |
          wget -q https://dl.google.com/cloudsql/cloud_sql_proxy.linux.amd64 -O cloud_sql_proxy
          chmod +x cloud_sql_proxy
          ./cloud_sql_proxy -instances=engrammic:europe-north1:engrammic-beta=tcp:5432 &
          sleep 5
          uv sync
          uv run alembic upgrade head
        env:
          DATABASE_URL: postgresql://context:${{ secrets.POSTGRES_PASSWORD }}@localhost:5432/engrammic
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy-beta.yml
git commit -m "feat: add GitHub Actions deploy-beta workflow"
```

---

### Task 12: Final Integration Verification

- [ ] **Step 1: Run linting**

```bash
just check
```

Expected: All checks pass.

- [ ] **Step 2: Verify Pulumi beta preview**

```bash
cd infra && uv run pulumi preview --stack beta
```

Expected: Preview shows Cloud SQL, beacon service, updated StatefulHost.

- [ ] **Step 3: Create beta branch**

```bash
git checkout -b beta
git push -u origin beta
```

Expected: Branch created and pushed.

- [ ] **Step 4: Final commit (if any remaining changes)**

```bash
git status
# If clean, proceed. If changes, commit them.
```

---

## Post-Deployment Setup (Manual)

After first successful workflow run:

1. **Configure GitHub Actions secrets:**
   - `GCP_WORKLOAD_IDENTITY_PROVIDER`
   - `GCP_SERVICE_ACCOUNT`
   - `PULUMI_ACCESS_TOKEN`
   - `POSTGRES_PASSWORD`

2. **Configure Pulumi secret:**
   ```bash
   cd infra
   uv run pulumi config set --secret postgres_password <password> --stack beta
   ```

3. **Configure DNS:**
   - `beta.engrammic.ai` -> Cloud Run API
   - `tel.engrammic.ai` -> Cloud Run Beacon

4. **Provision first partner beacon secret:**
   ```sql
   INSERT INTO beacon_secrets (silo_id, secret)
   VALUES ('partner-silo-id', 'generated-64-char-secret');
   ```
