# Beacon Telemetry Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Cloud Trace with a simpler telemetry pipeline: context-service sends heartbeats to beacon-service, Metabase dashboards query Postgres.

**Architecture:** Hosted context-service authenticates to beacon-service via X-Beacon-Secret header. Beacon stores events in beacon_events table. Metabase (Cloud Run) queries same Postgres for dashboards.

**Tech Stack:** FastAPI, Pulumi, Cloud Run, Metabase, asyncpg

**Spec:** docs/superpowers/specs/2026-05-23-beacon-telemetry-pipeline.md

---

## File Structure

**Modify:**
- `src/context_service/config/settings.py` - Add beacon_secret field to TelemetryConfig
- `src/context_service/telemetry/collector.py` - Add latency_p50_ms, latency_p95_ms, tool_counts fields
- `src/context_service/telemetry/beacon.py` - Send X-Beacon-Secret header
- `src/context_service/telemetry/tracing.py` - Remove Cloud Trace exporter
- `infra/__main__.py` - Deploy Metabase, generate beacon secret
- `infra/components/__init__.py` - Export MetabaseRun
- `pyproject.toml` - Remove opentelemetry-exporter-gcp-trace
- `.env.example` - Update telemetry config

**Create:**
- `infra/components/metabase.py` - Metabase Cloud Run component
- `alembic/versions/0012_create_metabase_database.py` - Metabase app DB migration

**Test:**
- `tests/unit/telemetry/test_collector.py` - Test new payload fields
- `tests/unit/telemetry/test_beacon.py` - Test secret header

---

### Task 1: Add beacon_secret to TelemetryConfig

**Files:**
- Modify: `src/context_service/config/settings.py:535-566`
- Test: `tests/unit/config/test_telemetry_settings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/config/test_telemetry_settings.py
def test_telemetry_config_beacon_secret() -> None:
    """Beacon secret can be configured via env."""
    import os
    os.environ["TELEMETRY__BEACON_SECRET"] = "test-secret-123"
    
    from context_service.config.settings import Settings
    settings = Settings()
    
    assert settings.telemetry.beacon_secret == "test-secret-123"
    
    del os.environ["TELEMETRY__BEACON_SECRET"]


def test_telemetry_config_default_interval_is_one_hour() -> None:
    """Default beacon interval is 1 hour."""
    from context_service.config.settings import TelemetryConfig
    config = TelemetryConfig()
    assert config.beacon_interval_hours == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/config/test_telemetry_settings.py -v -k "beacon_secret or default_interval"`
Expected: FAIL (beacon_secret not defined, default is 24 not 1)

- [ ] **Step 3: Add beacon_secret field and update default interval**

In `src/context_service/config/settings.py`, update TelemetryConfig:

```python
class TelemetryConfig(BaseModel):
    """Self-hosted telemetry configuration."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Tier 1: anonymous aggregate telemetry (default on)",
    )
    silos: list[str] = Field(
        default_factory=list,
        description="Tier 2: silo IDs to include in telemetry. Empty = tier 1 only. ['*'] = all silos.",
    )
    beacon_url: str = Field(
        default="https://tel.engrammic.ai/v1/beacon",
        description="Endpoint for telemetry heartbeats",
    )
    beacon_secret: str = Field(
        default="",
        description="Secret for authenticating to beacon service (X-Beacon-Secret header)",
    )
    beacon_interval_hours: int = Field(
        default=1,
        ge=1,
        le=168,
        description="Hours between beacon heartbeats",
    )

    @property
    def all_silos(self) -> bool:
        return self.silos == ["*"]

    @property
    def tier2_enabled(self) -> bool:
        return len(self.silos) > 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/config/test_telemetry_settings.py -v -k "beacon_secret or default_interval"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/config/settings.py tests/unit/config/test_telemetry_settings.py
git commit -m "feat(telemetry): add beacon_secret config, reduce default interval to 1h"
```

---

### Task 2: Add new fields to TelemetryPayload

**Files:**
- Modify: `src/context_service/telemetry/collector.py`
- Test: `tests/unit/telemetry/test_collector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/telemetry/test_collector.py
def test_telemetry_payload_has_percentile_fields() -> None:
    """TelemetryPayload includes p50/p95 latency and tool_counts."""
    from context_service.telemetry.collector import TelemetryPayload
    
    payload = TelemetryPayload(
        install_id="test",
        version="0.1.0",
        tier=1,
        uptime_seconds=100.0,
        latency_p50_ms=50.0,
        latency_p95_ms=150.0,
        tool_counts={"remember": 10, "recall": 25},
    )
    
    assert payload.latency_p50_ms == 50.0
    assert payload.latency_p95_ms == 150.0
    assert payload.tool_counts == {"remember": 10, "recall": 25}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/telemetry/test_collector.py::test_telemetry_payload_has_percentile_fields -v`
Expected: FAIL (fields not defined)

- [ ] **Step 3: Add new fields to TelemetryPayload**

In `src/context_service/telemetry/collector.py`:

```python
@dataclass
class TelemetryPayload:
    install_id: str
    version: str
    tier: int
    uptime_seconds: float
    total_silos: int = 0
    total_nodes: int = 0
    total_store_ops: int = 0
    total_recall_ops: int = 0
    error_rate: float = 0.0
    latency_mean_ms: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    tool_counts: dict[str, int] = field(default_factory=dict)
    silo_metrics: dict[str, SiloMetrics] = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/telemetry/test_collector.py::test_telemetry_payload_has_percentile_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/collector.py tests/unit/telemetry/test_collector.py
git commit -m "feat(telemetry): add latency percentiles and tool_counts to payload"
```

---

### Task 3: Collect tool counts in TelemetryCollector

**Files:**
- Modify: `src/context_service/telemetry/collector.py`
- Test: `tests/unit/telemetry/test_collector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/telemetry/test_collector.py
from unittest.mock import MagicMock


def _make_sample(name: str, labels: dict, value: float) -> MagicMock:
    """Create a mock Prometheus sample with correct attribute structure."""
    sample = MagicMock()
    sample.name = name
    sample.labels = labels
    sample.value = value
    return sample


def test_collector_extracts_tool_counts() -> None:
    """Collector extracts MCP tool call counts from registry."""
    from context_service.telemetry.collector import TelemetryCollector
    
    # Mock registry with tool counter samples
    mock_registry = MagicMock()
    mock_metric = MagicMock()
    mock_metric.samples = [
        _make_sample("mcp_tool_calls_total", {"tool": "remember"}, 10),
        _make_sample("mcp_tool_calls_total", {"tool": "recall"}, 25),
        _make_sample("mcp_tool_calls_total", {"tool": "learn"}, 5),
    ]
    mock_registry.collect.return_value = [mock_metric]
    
    collector = TelemetryCollector(
        install_id="test",
        version="0.1.0",
        registry=mock_registry,
    )
    
    payload = collector.collect()
    
    assert payload.tool_counts == {"remember": 10, "recall": 25, "learn": 5}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/telemetry/test_collector.py::test_collector_extracts_tool_counts -v`
Expected: FAIL (tool_counts empty)

- [ ] **Step 3: Update _collect_aggregates to extract tool counts**

In `src/context_service/telemetry/collector.py`, update `_collect_aggregates`:

```python
def _collect_aggregates(self, payload: TelemetryPayload) -> None:
    """Collect aggregate metrics from prometheus registry."""
    store_sum = 0
    recall_sum = 0
    latency_sum = 0.0
    latency_count = 0
    silos_seen: set[str] = set()
    tool_counts: dict[str, int] = {}

    for metric in self._registry.collect():
        for sample in metric.samples:
            name = sample.name
            labels = sample.labels
            value = sample.value

            if "silo_id" in labels:
                silos_seen.add(labels["silo_id"])

            if name == "context_store_latency_seconds_count":
                store_sum += int(value)
            elif name == "context_query_latency_seconds_count":
                recall_sum += int(value)
            elif name == "context_store_latency_seconds_sum":
                latency_sum += value
                latency_count += int(
                    self._get_sample_value(
                        metric, "context_store_latency_seconds_count", labels
                    )
                )
            elif name == "mcp_tool_calls_total":
                tool_name = labels.get("tool", "unknown")
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + int(value)

    payload.total_store_ops = store_sum
    payload.total_recall_ops = recall_sum
    payload.total_silos = len(silos_seen)
    payload.tool_counts = tool_counts

    if latency_count > 0:
        payload.latency_mean_ms = (latency_sum / latency_count) * 1000
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/telemetry/test_collector.py::test_collector_extracts_tool_counts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/collector.py tests/unit/telemetry/test_collector.py
git commit -m "feat(telemetry): collect MCP tool call counts"
```

---

### Task 4: Send X-Beacon-Secret header in BeaconService

**Files:**
- Modify: `src/context_service/telemetry/beacon.py`
- Test: `tests/unit/telemetry/test_beacon.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/telemetry/test_beacon.py
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_beacon_sends_secret_header() -> None:
    """BeaconService sends X-Beacon-Secret header with heartbeats."""
    from context_service.telemetry.beacon import BeaconService
    from context_service.telemetry.collector import TelemetryPayload
    
    mock_collector = AsyncMock()
    mock_collector.collect.return_value = TelemetryPayload(
        install_id="test",
        version="0.1.0",
        tier=1,
        uptime_seconds=100.0,
    )
    
    service = BeaconService(
        collector=mock_collector,
        beacon_url="https://test.example.com/beacon",
        beacon_secret="my-secret-123",
        interval_hours=1,
        enabled=True,
    )
    
    with patch("context_service.telemetry.beacon.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=AsyncMock(status_code=200))
        mock_client_cls.return_value = mock_client
        
        await service.send_heartbeat()
        
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs.get("headers", {}).get("X-Beacon-Secret") == "my-secret-123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/telemetry/test_beacon.py::test_beacon_sends_secret_header -v`
Expected: FAIL (BeaconService doesn't accept beacon_secret, headers not sent)

- [ ] **Step 3: Update BeaconService to accept and send secret**

In `src/context_service/telemetry/beacon.py`:

```python
class BeaconService:
    def __init__(
        self,
        collector: TelemetryCollector | None,
        beacon_url: str,
        interval_hours: int,
        enabled: bool = True,
        beacon_secret: str = "",
    ) -> None:
        self._collector = collector
        self._beacon_url = beacon_url
        self._beacon_secret = beacon_secret
        self._interval_seconds = interval_hours * 3600
        self._enabled = enabled
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not self._enabled or self._collector is None:
            logger.info("telemetry_beacon_disabled")
            return

        self._task = asyncio.create_task(self._run_loop())
        logger.info("telemetry_beacon_started", interval_hours=self._interval_seconds // 3600)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while True:
            await self.send_heartbeat()
            await asyncio.sleep(self._interval_seconds)

    async def send_heartbeat(self) -> None:
        if not self._enabled or self._collector is None:
            return

        try:
            payload = self._collector.collect()
            headers = {}
            if self._beacon_secret:
                headers["X-Beacon-Secret"] = self._beacon_secret
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self._beacon_url,
                    json=asdict(payload),
                    headers=headers,
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "telemetry_heartbeat_rejected",
                        status=resp.status_code,
                        tier=payload.tier,
                    )
                else:
                    logger.info(
                        "telemetry_heartbeat_sent",
                        status=resp.status_code,
                        tier=payload.tier,
                    )
        except Exception as e:
            logger.warning("telemetry_heartbeat_failed", error=str(e))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/telemetry/test_beacon.py::test_beacon_sends_secret_header -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/beacon.py tests/unit/telemetry/test_beacon.py
git commit -m "feat(telemetry): send X-Beacon-Secret header in heartbeats"
```

---

### Task 5: Create Metabase Pulumi component

**Files:**
- Create: `infra/components/metabase.py`
- Modify: `infra/components/__init__.py`

- [ ] **Step 1: Create MetabaseRun component**

Create `infra/components/metabase.py`:

```python
"""Cloud Run service for Metabase dashboards."""

import pulumi
from pulumi_gcp import cloudrunv2


class MetabaseRun(pulumi.ComponentResource):
    """Cloud Run service for Metabase analytics dashboards."""

    def __init__(
        self,
        name: str,
        vpc_id: pulumi.Input[str],
        subnet_id: pulumi.Input[str],
        service_account_email: pulumi.Input[str],
        database_url: pulumi.Input[str],
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:cloudrun:MetabaseRun", name, None, opts)

        config = pulumi.Config()
        gcp_config = pulumi.Config("gcp")
        env = config.require("environment")
        region = gcp_config.require("region")

        self.service = cloudrunv2.Service(
            f"{name}-service",
            name=f"engrammic-{env}-metabase",
            location=region,
            ingress="INGRESS_TRAFFIC_INTERNAL_ONLY",
            template=cloudrunv2.ServiceTemplateArgs(
                service_account=service_account_email,
                scaling=cloudrunv2.ServiceTemplateScalingArgs(
                    min_instance_count=0,
                    max_instance_count=2,
                ),
                vpc_access=cloudrunv2.ServiceTemplateVpcAccessArgs(
                    network_interfaces=[
                        cloudrunv2.ServiceTemplateVpcAccessNetworkInterfaceArgs(
                            network=vpc_id,
                            subnetwork=subnet_id,
                        )
                    ],
                    egress="ALL_TRAFFIC",
                ),
                containers=[
                    cloudrunv2.ServiceTemplateContainerArgs(
                        image="metabase/metabase:latest",
                        resources=cloudrunv2.ServiceTemplateContainerResourcesArgs(
                            limits={"cpu": "2", "memory": "2Gi"},
                        ),
                        ports=[
                            cloudrunv2.ServiceTemplateContainerPortArgs(
                                container_port=3000,
                            )
                        ],
                        envs=[
                            cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="MB_DB_TYPE",
                                value="postgres",
                            ),
                            cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="MB_DB_CONNECTION_URI",
                                value=database_url,
                            ),
                            cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="MB_JETTY_PORT",
                                value="3000",
                            ),
                        ],
                        startup_probe=cloudrunv2.ServiceTemplateContainerStartupProbeArgs(
                            http_get=cloudrunv2.ServiceTemplateContainerStartupProbeHttpGetArgs(
                                path="/api/health",
                                port=3000,
                            ),
                            initial_delay_seconds=30,
                            period_seconds=10,
                            timeout_seconds=5,
                            failure_threshold=10,
                        ),
                        liveness_probe=cloudrunv2.ServiceTemplateContainerLivenessProbeArgs(
                            http_get=cloudrunv2.ServiceTemplateContainerLivenessProbeHttpGetArgs(
                                path="/api/health",
                                port=3000,
                            ),
                            period_seconds=30,
                        ),
                    )
                ],
            ),
            opts=pulumi.ResourceOptions(
                parent=self,
                ignore_changes=["template"],
            ),
        )

        self.register_outputs({
            "service_url": self.service.uri,
            "service_name": self.service.name,
        })
```

- [ ] **Step 2: Export from components/__init__.py**

Add to `infra/components/__init__.py`:

```python
from .metabase import MetabaseRun
```

And add `MetabaseRun` to the `__all__` list.

- [ ] **Step 3: Verify Pulumi types**

Run: `cd infra && uv run python -c "from components import MetabaseRun; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add infra/components/metabase.py infra/components/__init__.py
git commit -m "feat(infra): add Metabase Cloud Run component"
```

---

### Task 6: Create Metabase database migration

**Files:**
- Create: `alembic/versions/0012_create_metabase_database.py`

- [ ] **Step 1: Create the migration**

Create `alembic/versions/0012_create_metabase_database.py`:

```python
"""create metabase database

Revision ID: 0007
Revises: 0006_add_beacon_tables
Create Date: 2026-05-23

Note: This migration creates a separate database for Metabase app state.
The main engrammic database user needs CREATEDB privilege, or this must
be run by a superuser. In production, the metabase database may be
created via Pulumi/Terraform instead.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0012"
down_revision: str = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create metabase database if it doesn't exist
    # Note: This requires connecting to postgres database, not engrammic
    # In Cloud SQL, we handle this via Pulumi/gcloud instead
    connection = op.get_bind()
    
    # Check if we can create databases (won't work in most managed envs)
    try:
        # Use raw connection to check for database
        result = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'metabase'")
        )
        if result.fetchone() is None:
            # Can't create database from within a transaction
            # Log instruction for manual creation
            print("NOTE: Create metabase database manually:")
            print("  CREATE DATABASE metabase OWNER context;")
    except Exception:
        print("NOTE: Create metabase database manually:")
        print("  CREATE DATABASE metabase OWNER context;")


def downgrade() -> None:
    # Don't drop the database - too dangerous
    print("NOTE: Drop metabase database manually if needed:")
    print("  DROP DATABASE metabase;")
```

- [ ] **Step 2: Verify migration syntax**

Run: `uv run python -c "import alembic.versions; print('syntax ok')"`

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/0012_create_metabase_database.py
git commit -m "feat(db): add metabase database migration placeholder"
```

---

### Task 7: Seed hosted beacon secret migration

**Files:**
- Create: `alembic/versions/0013_seed_hosted_beacon_secret.py`

- [ ] **Step 1: Create the migration**

Create `alembic/versions/0013_seed_hosted_beacon_secret.py`:

```python
"""seed hosted beacon secret

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-23

Seeds the beacon secret for the hosted Engrammic service.
The secret value comes from HOSTED_BEACON_SECRET env var (set by Pulumi).
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0013"
down_revision: str = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOSTED_SILO_ID = "engrammic-hosted"


def upgrade() -> None:
    secret = os.environ.get("HOSTED_BEACON_SECRET")
    if not secret:
        print("NOTE: HOSTED_BEACON_SECRET not set, skipping beacon secret seed")
        return

    connection = op.get_bind()
    
    # Upsert: insert or update if exists
    connection.execute(
        text("""
            INSERT INTO beacon_secrets (silo_id, secret)
            VALUES (:silo_id, :secret)
            ON CONFLICT (silo_id) DO UPDATE SET secret = :secret
        """),
        {"silo_id": HOSTED_SILO_ID, "secret": secret},
    )
    print(f"Seeded beacon secret for {HOSTED_SILO_ID}")


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        text("DELETE FROM beacon_secrets WHERE silo_id = :silo_id"),
        {"silo_id": HOSTED_SILO_ID},
    )
```

- [ ] **Step 2: Commit**

```bash
git add alembic/versions/0013_seed_hosted_beacon_secret.py
git commit -m "feat(db): seed hosted service beacon secret"
```

---

### Task 8: Update Pulumi main to deploy Metabase and wire secrets

**Files:**
- Modify: `infra/__main__.py`

- [ ] **Step 1: Import MetabaseRun**

Add to imports at top of `infra/__main__.py`:

```python
from components import (
    BeaconServiceRun,
    CloudSQLPostgres,
    ContextServiceRun,
    IAMStack,
    InternalDNS,
    MetabaseRun,  # Add this
    MigrationJob,
    NetworkStack,
    SecretsStack,
    StatefulHost,
    StorageStack,
)
```

- [ ] **Step 2: Add Metabase deployment after beacon_service**

Add after the beacon_service block (around line 163):

```python
    # Metabase for internal dashboards
    metabase_database_url = pulumi.Output.all(
        postgres_host,
        config.require_secret("postgres_password"),
    ).apply(lambda args: f"postgres://context:{quote(args[1], safe='')}@{args[0]}:5432/metabase")

    metabase_service = MetabaseRun(
        "engrammic-metabase",
        vpc_id=network.vpc.id,
        subnet_id=network.private_subnet.name,
        service_account_email=iam.context_service_run.email,
        database_url=metabase_database_url,
    )
```

- [ ] **Step 3: Add beacon_secret to context-service env vars**

Generate and pass beacon secret. Add before context_service definition:

```python
# Generate beacon secret for hosted service
import secrets as py_secrets
beacon_secret = config.get_secret("beacon_secret") or py_secrets.token_urlsafe(32)
```

Then add to context_service env_vars dict:

```python
"TELEMETRY__BEACON_SECRET": beacon_secret,
"TELEMETRY__BEACON_URL": beacon_service.service.uri.apply(lambda uri: f"{uri}/v1/beacon") if beacon_service else "",
```

- [ ] **Step 4: Export metabase URL**

Add to exports section:

```python
if metabase_service:
    pulumi.export("metabase_url", metabase_service.service.uri)
```

- [ ] **Step 5: Verify Pulumi config**

Run: `cd infra && uv run pulumi preview --stack dev 2>&1 | head -20`
Expected: No syntax errors

- [ ] **Step 6: Commit**

```bash
git add infra/__main__.py
git commit -m "feat(infra): deploy Metabase and wire beacon secret"
```

---

### Task 9: Remove Cloud Trace dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/context_service/telemetry/tracing.py`

- [ ] **Step 1: Check if Cloud Trace exporter exists in deps**

Run: `grep -n "cloud-trace\|gcp-trace" pyproject.toml`

- [ ] **Step 2: Remove Cloud Trace from dependencies if present**

If found, remove the `opentelemetry-exporter-gcp-trace` line from pyproject.toml dependencies.

- [ ] **Step 3: Remove Cloud Trace exporter from tracing.py**

In `src/context_service/telemetry/tracing.py`, update `_create_exporter`:

```python
def _create_exporter(endpoint: str | None) -> OTLPSpanExporter | None:
    """Create OTLP span exporter if endpoint is configured."""
    if endpoint:
        return OTLPSpanExporter(endpoint=endpoint, insecure=True)
    return None
```

Remove the Cloud Trace import and GCP environment detection for tracing (keep `_is_gcp_environment` if used elsewhere, or remove if not).

- [ ] **Step 4: Update setup_tracing to simplify**

```python
def setup_tracing(service_name: str = "context-service") -> None:
    """Initialize OpenTelemetry tracing if OTLP endpoint is configured."""
    import structlog

    logger = structlog.get_logger(__name__)

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    
    if not endpoint:
        logger.info("otel_disabled", reason="no OTEL_EXPORTER_OTLP_ENDPOINT")
        return

    exporter = _create_exporter(endpoint)
    if not exporter:
        logger.info("otel_disabled", reason="no exporter configured")
        return

    from context_service.telemetry.metrics import setup_metrics

    setup_metrics(service_name)

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": __version__,
        }
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument()
    RedisInstrumentor().instrument()

    logger.info("otel_tracing_enabled", exporter="otlp", endpoint=endpoint, service=service_name)
```

- [ ] **Step 5: Run tests to verify no breakage**

Run: `uv run pytest tests/unit/telemetry/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/context_service/telemetry/tracing.py
git commit -m "chore(telemetry): remove Cloud Trace, simplify to OTLP-only"
```

---

### Task 10: Update .env.example with new config

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Update telemetry section**

Find and update the telemetry section in `.env.example`:

```bash
# Telemetry (beacon heartbeats to Engrammic)
TELEMETRY__ENABLED=true
TELEMETRY__SILOS=                       # comma-separated silo IDs, or "*" for all
TELEMETRY__BEACON_URL=https://tel.engrammic.ai/v1/beacon
TELEMETRY__BEACON_SECRET=               # secret for authenticating to beacon service
TELEMETRY__BEACON_INTERVAL_HOURS=1      # heartbeat interval (default: 1 hour)

# OTEL (optional, for local tracing with Jaeger/Tempo)
# Leave empty to disable OTEL tracing
OTEL_EXPORTER_OTLP_ENDPOINT=
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: update .env.example with beacon telemetry config"
```

---

## Done Criteria

- [ ] TelemetryConfig has beacon_secret field
- [ ] TelemetryPayload has latency_p50_ms, latency_p95_ms, tool_counts fields
- [ ] BeaconService sends X-Beacon-Secret header
- [ ] MetabaseRun Pulumi component exists and is deployed
- [ ] Metabase database migration exists
- [ ] Cloud Trace dependencies removed
- [ ] .env.example updated
- [ ] All tests pass: `uv run pytest tests/unit/telemetry/ -v`
- [ ] Pulumi preview succeeds: `cd infra && uv run pulumi preview --stack beta`
