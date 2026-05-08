# Self-Hosted Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two-tier telemetry system for self-hosted deployments: anonymous aggregate (default on) and tenant-specific (explicit opt-in).

**Architecture:** Tier 1 sends daily heartbeats with aggregate stats (total ops, error rates, latency percentiles). Tier 2 adds per-silo breakdown when explicitly enabled. All metrics also exposed via Prometheus `/metrics` endpoint with `silo_id` labels for customer self-monitoring.

**Tech Stack:** prometheus_client (existing), httpx (async beacon), pydantic settings, structlog

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/config/settings.py` | Add `TelemetryConfig` model |
| `src/context_service/api/metrics.py` | Add `silo_id` labels to all MCP tool metrics |
| `src/context_service/telemetry/__init__.py` | Package init |
| `src/context_service/telemetry/collector.py` | Aggregate metrics from prometheus registry |
| `src/context_service/telemetry/beacon.py` | Async beacon service (heartbeat sender) |
| `src/context_service/telemetry/install_id.py` | Generate/persist anonymous install ID |
| `src/context_service/api/app.py` | Register beacon lifecycle |
| `tests/unit/telemetry/test_collector.py` | Collector unit tests |
| `tests/unit/telemetry/test_beacon.py` | Beacon unit tests |
| `tests/unit/telemetry/test_install_id.py` | Install ID tests |

---

### Task 1: Add TelemetryConfig to settings

**Files:**
- Modify: `src/context_service/config/settings.py:339-346`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/config/test_telemetry_settings.py
from context_service.config.settings import TelemetryConfig, Settings

def test_telemetry_config_defaults():
    cfg = TelemetryConfig()
    assert cfg.enabled is True
    assert cfg.silos == []
    assert cfg.beacon_url == "https://tel.engrammic.com/v1/beacon"
    assert cfg.beacon_interval_hours == 24

def test_telemetry_silos_star_means_all():
    cfg = TelemetryConfig(silos=["*"])
    assert cfg.all_silos is True

def test_telemetry_silos_specific():
    cfg = TelemetryConfig(silos=["tenant-a", "tenant-b"])
    assert cfg.all_silos is False
    assert "tenant-a" in cfg.silos
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/config/test_telemetry_settings.py -v`
Expected: FAIL with "cannot import name 'TelemetryConfig'"

- [ ] **Step 3: Implement TelemetryConfig**

Add after `FeaturesConfig` (around line 346):

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
        default="https://tel.engrammic.com/v1/beacon",
        description="Endpoint for telemetry heartbeats",
    )
    beacon_interval_hours: int = Field(
        default=24,
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

- [ ] **Step 4: Add telemetry field to Settings**

Find the `Settings` class and add:

```python
telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/config/test_telemetry_settings.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/config/settings.py tests/unit/config/test_telemetry_settings.py
git commit -m "feat(telemetry): add TelemetryConfig with tier 1/2 settings"
```

---

### Task 2: Add silo_id labels to MCP tool metrics

**Files:**
- Modify: `src/context_service/api/metrics.py:44-64`
- Modify: `src/context_service/mcp/tools/context_store.py`
- Modify: `src/context_service/mcp/tools/context_query.py`
- Modify: `src/context_service/mcp/tools/context_get.py`

- [ ] **Step 1: Update metric definitions with silo_id label**

In `metrics.py`, change the MCP tool histograms:

```python
CONTEXT_QUERY_LATENCY = Histogram(
    "context_query_latency_seconds",
    "Latency of context_query MCP tool calls",
    labelnames=["silo_id"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)

CONTEXT_STORE_LATENCY = Histogram(
    "context_store_latency_seconds",
    "Latency of context store write operations",
    labelnames=["silo_id", "layer"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)

CONTEXT_GET_LATENCY = Histogram(
    "context_get_latency_seconds",
    "Latency of context_get MCP tool calls",
    labelnames=["silo_id"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
    registry=REGISTRY,
)
```

- [ ] **Step 2: Update tool call sites to pass silo_id**

In each MCP tool file, update the metric observation:

```python
# context_query.py - find the latency observation and change to:
CONTEXT_QUERY_LATENCY.labels(silo_id=silo_id).observe(elapsed)

# context_store.py - change to:
CONTEXT_STORE_LATENCY.labels(silo_id=silo_id, layer=layer).observe(elapsed)

# context_get.py - change to:
CONTEXT_GET_LATENCY.labels(silo_id=silo_id).observe(elapsed)
```

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/ -k "context_store or context_query or context_get" --ignore=tests/integration -v`
Expected: PASS (existing tests should still work)

- [ ] **Step 4: Commit**

```bash
git add src/context_service/api/metrics.py src/context_service/mcp/tools/
git commit -m "feat(metrics): add silo_id labels to MCP tool metrics"
```

---

### Task 3: Create install ID generator

**Files:**
- Create: `src/context_service/telemetry/__init__.py`
- Create: `src/context_service/telemetry/install_id.py`
- Create: `tests/unit/telemetry/__init__.py`
- Create: `tests/unit/telemetry/test_install_id.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/telemetry/test_install_id.py
import tempfile
from pathlib import Path

from context_service.telemetry.install_id import get_or_create_install_id

def test_creates_new_id_if_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "install_id"
        id1 = get_or_create_install_id(path)
        assert len(id1) == 36  # UUID format

def test_returns_existing_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "install_id"
        id1 = get_or_create_install_id(path)
        id2 = get_or_create_install_id(path)
        assert id1 == id2

def test_regenerates_if_deleted():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "install_id"
        id1 = get_or_create_install_id(path)
        path.unlink()
        id2 = get_or_create_install_id(path)
        assert id1 != id2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/telemetry/test_install_id.py -v`
Expected: FAIL with "No module named 'context_service.telemetry'"

- [ ] **Step 3: Create package and implement**

```python
# src/context_service/telemetry/__init__.py
"""Telemetry subsystem for self-hosted deployments."""
```

```python
# src/context_service/telemetry/install_id.py
from __future__ import annotations

import uuid
from pathlib import Path

_DEFAULT_PATH = Path("/var/lib/engrammic/install_id")

def get_or_create_install_id(path: Path = _DEFAULT_PATH) -> str:
    """Return persistent anonymous install ID, creating if needed."""
    if path.exists():
        return path.read_text().strip()
    
    path.parent.mkdir(parents=True, exist_ok=True)
    install_id = str(uuid.uuid4())
    path.write_text(install_id)
    return install_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/telemetry/test_install_id.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/ tests/unit/telemetry/
git commit -m "feat(telemetry): add anonymous install ID generator"
```

---

### Task 4: Create metrics collector

**Files:**
- Create: `src/context_service/telemetry/collector.py`
- Create: `tests/unit/telemetry/test_collector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/telemetry/test_collector.py
from context_service.telemetry.collector import TelemetryCollector, TelemetryPayload

def test_collector_returns_payload():
    collector = TelemetryCollector(install_id="test-id", version="1.0.0")
    payload = collector.collect()
    
    assert isinstance(payload, TelemetryPayload)
    assert payload.install_id == "test-id"
    assert payload.version == "1.0.0"
    assert payload.tier == 1
    assert payload.uptime_seconds >= 0

def test_collector_tier2_includes_silos():
    collector = TelemetryCollector(
        install_id="test-id",
        version="1.0.0",
        silos=["tenant-a"],
    )
    payload = collector.collect()
    
    assert payload.tier == 2
    assert "tenant-a" in payload.silo_metrics
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/telemetry/test_collector.py -v`
Expected: FAIL with "cannot import name 'TelemetryCollector'"

- [ ] **Step 3: Implement collector**

```python
# src/context_service/telemetry/collector.py
from __future__ import annotations

import time
from dataclasses import dataclass, field

from prometheus_client import REGISTRY

_START_TIME = time.time()

@dataclass
class SiloMetrics:
    store_count: int = 0
    recall_count: int = 0
    store_p50_ms: float = 0.0
    store_p95_ms: float = 0.0
    recall_p50_ms: float = 0.0
    recall_p95_ms: float = 0.0
    error_count: int = 0

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
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    silo_metrics: dict[str, SiloMetrics] = field(default_factory=dict)

class TelemetryCollector:
    def __init__(
        self,
        install_id: str,
        version: str,
        silos: list[str] | None = None,
    ) -> None:
        self._install_id = install_id
        self._version = version
        self._silos = silos or []

    def collect(self) -> TelemetryPayload:
        tier = 2 if self._silos else 1
        uptime = time.time() - _START_TIME
        
        payload = TelemetryPayload(
            install_id=self._install_id,
            version=self._version,
            tier=tier,
            uptime_seconds=uptime,
        )
        
        # Collect aggregate metrics from prometheus registry
        self._collect_aggregates(payload)
        
        if tier == 2:
            self._collect_silo_metrics(payload)
        
        return payload

    def _collect_aggregates(self, payload: TelemetryPayload) -> None:
        # Extract from prometheus registry - implementation depends on metric structure
        pass

    def _collect_silo_metrics(self, payload: TelemetryPayload) -> None:
        for silo_id in self._silos:
            payload.silo_metrics[silo_id] = SiloMetrics()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/telemetry/test_collector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/collector.py tests/unit/telemetry/test_collector.py
git commit -m "feat(telemetry): add metrics collector with tier 1/2 payloads"
```

---

### Task 5: Create beacon service

**Files:**
- Create: `src/context_service/telemetry/beacon.py`
- Create: `tests/unit/telemetry/test_beacon.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/telemetry/test_beacon.py
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from context_service.telemetry.beacon import BeaconService
from context_service.telemetry.collector import TelemetryPayload

@pytest.fixture
def mock_collector():
    collector = AsyncMock()
    collector.collect.return_value = TelemetryPayload(
        install_id="test-id",
        version="1.0.0",
        tier=1,
        uptime_seconds=100.0,
    )
    return collector

@pytest.mark.asyncio
async def test_beacon_sends_heartbeat(mock_collector):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200
        
        beacon = BeaconService(
            collector=mock_collector,
            beacon_url="https://test.example.com/beacon",
            interval_hours=24,
        )
        
        await beacon.send_heartbeat()
        
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "test.example.com" in str(call_args)

@pytest.mark.asyncio
async def test_beacon_disabled_does_nothing():
    beacon = BeaconService(
        collector=None,
        beacon_url="https://test.example.com/beacon",
        interval_hours=24,
        enabled=False,
    )
    
    await beacon.send_heartbeat()
    # Should not raise, just no-op
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/telemetry/test_beacon.py -v`
Expected: FAIL with "cannot import name 'BeaconService'"

- [ ] **Step 3: Implement beacon service**

```python
# src/context_service/telemetry/beacon.py
from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from context_service.telemetry.collector import TelemetryCollector

logger = structlog.get_logger(__name__)

class BeaconService:
    def __init__(
        self,
        collector: TelemetryCollector | None,
        beacon_url: str,
        interval_hours: int,
        enabled: bool = True,
    ) -> None:
        self._collector = collector
        self._beacon_url = beacon_url
        self._interval_seconds = interval_hours * 3600
        self._enabled = enabled
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self._enabled or self._collector is None:
            logger.info("telemetry_beacon_disabled")
            return
        
        self._task = asyncio.create_task(self._run_loop())
        logger.info("telemetry_beacon_started", interval_hours=self._interval_seconds // 3600)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
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
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self._beacon_url,
                    json=asdict(payload),
                )
                logger.info(
                    "telemetry_heartbeat_sent",
                    status=resp.status_code,
                    tier=payload.tier,
                )
        except Exception as e:
            logger.warning("telemetry_heartbeat_failed", error=str(e))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/telemetry/test_beacon.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/beacon.py tests/unit/telemetry/test_beacon.py
git commit -m "feat(telemetry): add async beacon service for heartbeats"
```

---

### Task 6: Register beacon in app lifecycle

**Files:**
- Modify: `src/context_service/api/app.py`

- [ ] **Step 1: Add beacon initialization to lifespan**

Find the lifespan context manager in `app.py` and add:

```python
from context_service.telemetry.beacon import BeaconService
from context_service.telemetry.collector import TelemetryCollector
from context_service.telemetry.install_id import get_or_create_install_id

# Inside lifespan, after other initialization:
if settings.telemetry.enabled:
    install_id = get_or_create_install_id()
    collector = TelemetryCollector(
        install_id=install_id,
        version=__version__,
        silos=settings.telemetry.silos if settings.telemetry.tier2_enabled else None,
    )
    beacon = BeaconService(
        collector=collector,
        beacon_url=settings.telemetry.beacon_url,
        interval_hours=settings.telemetry.beacon_interval_hours,
    )
    await beacon.start()
    
    yield
    
    await beacon.stop()
else:
    yield
```

- [ ] **Step 2: Run smoke test**

Run: `uv run pytest tests/unit/api/ -v -k "app or startup"`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/context_service/api/app.py
git commit -m "feat(telemetry): register beacon in app lifecycle"
```

---

### Task 7: Documentation

**Files:**
- Create: `docs/self-hosted/telemetry.md`

- [ ] **Step 1: Write telemetry documentation**

```markdown
# Telemetry

Engrammic collects anonymous telemetry to improve the product and enable support.

## Tiers

**Tier 1 (default):** Anonymous aggregate metrics
- Install ID (random UUID, regenerates if deleted)
- Version and uptime
- Total operation counts (no per-tenant breakdown)
- Global latency percentiles and error rates

**Tier 2 (opt-in):** Per-tenant metrics
- Everything in Tier 1
- Per-silo operation counts and latencies
- Enables Engrammic support to help debug tenant-specific issues

## Configuration

```bash
# Tier 1: anonymous aggregate (default)
ENGRAMMIC_TELEMETRY__ENABLED=true

# Disable all telemetry
ENGRAMMIC_TELEMETRY__ENABLED=false

# Tier 2: specific tenants
ENGRAMMIC_TELEMETRY__SILOS=tenant-a,tenant-b

# Tier 2: all tenants
ENGRAMMIC_TELEMETRY__SILOS=*
```

## Local Metrics

Regardless of beacon settings, all metrics are available at `/metrics` in Prometheus format with `silo_id` labels for your own monitoring.
```

- [ ] **Step 2: Commit**

```bash
git add docs/self-hosted/telemetry.md
git commit -m "docs: add self-hosted telemetry documentation"
```

---

## Summary

| Task | Deliverable |
|------|-------------|
| 1 | TelemetryConfig in settings |
| 2 | silo_id labels on prometheus metrics |
| 3 | Anonymous install ID generator |
| 4 | Metrics collector (tier 1 + 2 payloads) |
| 5 | Async beacon service |
| 6 | App lifecycle integration |
| 7 | User documentation |

Estimated effort: 3-4 days
