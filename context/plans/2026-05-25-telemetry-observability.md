# Telemetry and Observability Implementation Plan

> **Status:** SHIPPED (2026-05-25). Branch `feat/telemetry-observability` ready to merge. Deploy with `pulumi up --stack beta`.

**Goal:** Add full observability stack with self-hosted SigNoz and comprehensive metrics instrumentation for closed beta.

**Architecture:** Dedicated GCE VM (`signoz-host`) runs SigNoz + ClickHouse, isolated from core data stores. Context-service sends OTEL metrics via VPC-internal endpoint. Phased instrumentation adds cache visibility, recall latency breakdown, and epistemic health metrics.

**Tech Stack:** Pulumi (GCP), Docker Compose, SigNoz, ClickHouse, OpenTelemetry Python SDK

**Linear:** ENG-32

**Branch:** `feat/telemetry-observability`

---

## File Structure

### Phase 0 (Infrastructure)
- Create: `infra/components/signoz.py` - SignozHost Pulumi component
- Create: `infra/signoz/docker-compose.yml` - SigNoz stack compose file
- Modify: `infra/components/__init__.py` - export SignozHost
- Modify: `infra/__main__.py` - instantiate SignozHost, wire DNS
- Modify: `infra/components/dns.py` - add signoz DNS record
- Modify: `infra/components/cloudrun.py` - add OTEL env vars
- Modify: `justfile` - add signoz-tunnel command

### Phase 1 (Wire Existing Metrics)
- Modify: `src/context_service/telemetry/metrics.py` - add silo_id to existing functions
- Modify: `src/context_service/mcp/tools/believe.py` - call record_belief_confidence
- Modify: `src/context_service/mcp/tools/commit.py` - call record_belief_confidence
- Modify: `src/context_service/engine/chain_applicability.py` - complete record_chain_evidence_modified

### Phase 2 (Recall and Cache)
- Modify: `src/context_service/telemetry/metrics.py` - add cache/recall metrics
- Modify: `src/context_service/mcp/tools/recall.py` - add latency/depth/source metrics
- Modify: `src/context_service/cache/result_cache.py` - add hit/miss/eviction counters
- Modify: `src/context_service/cache/node_cache.py` - add hit/miss/eviction counters
- Modify: `src/context_service/cache/alias_cache.py` - add hit/miss/eviction counters

### Phase 3 (Epistemic Health)
- Modify: `src/context_service/telemetry/metrics.py` - add error/supersession/confidence metrics
- Modify: `src/context_service/mcp/tools/remember.py` - add confidence histogram
- Modify: `src/context_service/mcp/tools/learn.py` - add confidence/supersession metrics
- Modify: `src/context_service/mcp/tools/believe.py` - add confidence histogram
- Modify: `src/context_service/sage/custodian/dispatch.py` - add supersession_skipped counter

---

## Phase 0: SigNoz Infrastructure

### Task 1: Create SignozHost Pulumi Component

**Files:**
- Create: `infra/components/signoz.py`

- [ ] **Step 1: Create signoz.py with component skeleton**

```python
"""GCE instance for SigNoz observability stack."""

import pulumi
from pulumi_gcp import compute

SIGNOZ_COMPOSE = '''
services:
  clickhouse:
    image: clickhouse/clickhouse-server:23.8-alpine
    container_name: clickhouse
    mem_limit: 8g
    ports:
      - "8123:8123"
      - "9000:9000"
    volumes:
      - /mnt/clickhouse:/var/lib/clickhouse
    ulimits:
      nofile:
        soft: 262144
        hard: 262144
    restart: unless-stopped

  signoz-otel-collector:
    image: signoz/signoz-otel-collector:0.88.11
    container_name: signoz-otel-collector
    mem_limit: 1g
    ports:
      - "4317:4317"
      - "4318:4318"
    environment:
      - CLICKHOUSE_HOST=clickhouse
    depends_on:
      - clickhouse
    restart: unless-stopped

  signoz-query-service:
    image: signoz/query-service:0.45.1
    container_name: signoz-query
    mem_limit: 2g
    environment:
      - ClickHouseUrl=tcp://clickhouse:9000
      - STORAGE=clickhouse
    depends_on:
      - clickhouse
    restart: unless-stopped

  signoz-frontend:
    image: signoz/frontend:0.45.1
    container_name: signoz-frontend
    mem_limit: 512m
    ports:
      - "3301:3301"
    environment:
      - FRONTEND_API_ENDPOINT=http://signoz-query-service:8080
    depends_on:
      - signoz-query-service
    restart: unless-stopped
'''


class SignozHost(pulumi.ComponentResource):
    """GCE instance running SigNoz observability stack."""

    def __init__(
        self,
        name: str,
        network: compute.Network,
        subnet: compute.Subnetwork,
        service_account_email: str,
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:compute:SignozHost", name, None, opts)

        config = pulumi.Config()
        gcp_config = pulumi.Config("gcp")
        env = config.require("environment")
        zone = gcp_config.require("zone")

        # Persistent disk for ClickHouse
        self.clickhouse_disk = compute.Disk(
            f"{name}-clickhouse-disk",
            name=f"engrammic-{env}-clickhouse",
            size=100,
            type="pd-ssd",
            zone=zone,
            opts=pulumi.ResourceOptions(parent=self),
        )

        startup_script = f'''#!/bin/bash
set -e

# Install Docker
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# Mount ClickHouse disk
DISK_ID="engrammic-{env}-clickhouse"
MOUNT_POINT="/mnt/clickhouse"
DEVICE="/dev/disk/by-id/google-$DISK_ID"

mkdir -p $MOUNT_POINT
if ! mountpoint -q $MOUNT_POINT; then
    if ! blkid $DEVICE; then
        mkfs.ext4 -F $DEVICE
    fi
    mount $DEVICE $MOUNT_POINT
    echo "$DEVICE $MOUNT_POINT ext4 defaults,nofail 0 2" >> /etc/fstab
fi
chown -R 101:101 $MOUNT_POINT  # ClickHouse UID

# Write docker-compose
cat > /opt/signoz/docker-compose.yml << 'COMPOSE_EOF'
{SIGNOZ_COMPOSE}
COMPOSE_EOF

# Start services
cd /opt/signoz
docker compose up -d
'''

        self.instance = compute.Instance(
            f"{name}-instance",
            name=f"engrammic-{env}-signoz",
            machine_type="e2-standard-4",
            zone=zone,
            boot_disk=compute.InstanceBootDiskArgs(
                initialize_params=compute.InstanceBootDiskInitializeParamsArgs(
                    image="projects/cos-cloud/global/images/family/cos-stable",
                    size=30,
                    type="pd-balanced",
                ),
            ),
            attached_disks=[
                compute.InstanceAttachedDiskArgs(
                    source=self.clickhouse_disk.self_link,
                    device_name=f"engrammic-{env}-clickhouse",
                ),
            ],
            network_interfaces=[
                compute.InstanceNetworkInterfaceArgs(
                    network=network.id,
                    subnetwork=subnet.id,
                ),
            ],
            service_account=compute.InstanceServiceAccountArgs(
                email=service_account_email,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            ),
            metadata_startup_script=startup_script,
            tags=["signoz", "allow-iap"],
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.register_outputs({"instance_ip": self.instance.network_interfaces[0].network_ip})
```

- [ ] **Step 2: Export from components/__init__.py**

Add to `infra/components/__init__.py`:

```python
from .signoz import SignozHost
```

And add `SignozHost` to the `__all__` list.

- [ ] **Step 3: Verify syntax**

Run: `cd infra && python -c "from components import SignozHost; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add infra/components/signoz.py infra/components/__init__.py
git commit -m "feat(infra): add SignozHost Pulumi component"
```

---

### Task 2: Wire SignozHost in Pulumi Main

**Files:**
- Modify: `infra/__main__.py`

- [ ] **Step 1: Add SignozHost import**

Add `SignozHost` to the imports from components.

- [ ] **Step 2: Instantiate SignozHost after StatefulHost**

Add after the `stateful_host` instantiation:

```python
# SigNoz observability host
signoz_host = SignozHost(
    "engrammic-signoz",
    network=network.vpc,
    subnet=network.private_subnet,
    service_account_email=iam.stateful_host.email,  # reuse SA for now
)
signoz_hostname = signoz_host.instance.network_interfaces[0].network_ip
```

- [ ] **Step 3: Verify Pulumi preview**

Run: `cd infra && pulumi preview --stack dev`
Expected: Shows SignozHost resources to create

- [ ] **Step 4: Commit**

```bash
git add infra/__main__.py
git commit -m "feat(infra): wire SignozHost in Pulumi main"
```

---

### Task 3: Add SigNoz DNS Record

**Files:**
- Modify: `infra/components/dns.py`
- Modify: `infra/__main__.py`

- [ ] **Step 1: Update InternalDNS to accept signoz_ip**

Add `signoz_ip` parameter to `InternalDNS.__init__` and create a record:

```python
def __init__(
    self,
    name: str,
    vpc_id: pulumi.Input[str],
    stateful_host_ip: pulumi.Input[str],
    signoz_ip: pulumi.Input[str] | None = None,  # Add this
    opts: pulumi.ResourceOptions | None = None,
):
    # ... existing code ...
    
    # Add after the stateful host record:
    if signoz_ip:
        self.signoz_record = dns.RecordSet(
            f"{name}-signoz",
            name=f"signoz.{self.zone.dns_name}",
            type="A",
            ttl=300,
            managed_zone=self.zone.name,
            rrdatas=[signoz_ip],
            opts=pulumi.ResourceOptions(parent=self),
        )
```

- [ ] **Step 2: Pass signoz_ip in __main__.py**

Update the InternalDNS instantiation:

```python
internal_dns = InternalDNS(
    "engrammic-dns",
    vpc_id=network.vpc.id,
    stateful_host_ip=stateful_host.instance.network_interfaces[0].network_ip,
    signoz_ip=signoz_host.instance.network_interfaces[0].network_ip,
)
```

- [ ] **Step 3: Export signoz hostname**

Add to `__main__.py`:

```python
pulumi.export("signoz_hostname", "signoz.engrammic.internal")
```

- [ ] **Step 4: Commit**

```bash
git add infra/components/dns.py infra/__main__.py
git commit -m "feat(infra): add signoz.engrammic.internal DNS record"
```

---

### Task 4: Add OTEL Env Vars to Context Service

**Files:**
- Modify: `infra/components/cloudrun.py`

- [ ] **Step 1: Find env_vars dict in ContextServiceRun**

Locate the `env_vars` parameter passed to the Cloud Run service.

- [ ] **Step 2: Add OTEL environment variables**

Add to the env_vars:

```python
"OTEL_ENABLED": "true",
"OTEL_EXPORTER_OTLP_ENDPOINT": "http://signoz.engrammic.internal:4317",
"OTEL_SERVICE_NAME": "engrammic",
"OTEL_EXPORTER_OTLP_INSECURE": "true",
```

- [ ] **Step 3: Verify Pulumi preview**

Run: `cd infra && pulumi preview --stack dev`
Expected: Shows env var changes in Cloud Run revision

- [ ] **Step 4: Commit**

```bash
git add infra/components/cloudrun.py
git commit -m "feat(infra): enable OTEL export to SigNoz"
```

---

### Task 5: Add Justfile Tunnel Command

**Files:**
- Modify: `justfile`

- [ ] **Step 1: Add signoz-tunnel recipe**

```just
# Open IAP tunnel to SigNoz UI
signoz-tunnel:
    gcloud compute start-iap-tunnel engrammic-beta-signoz 3301 --local-host-port=localhost:3301 --zone=europe-north1-b
```

- [ ] **Step 2: Test command parses**

Run: `just --list | grep signoz`
Expected: Shows `signoz-tunnel` recipe

- [ ] **Step 3: Commit**

```bash
git add justfile
git commit -m "feat: add just signoz-tunnel for IAP access to SigNoz UI"
```

---

## Phase 1: Wire Existing Metrics

### Task 6: Add silo_id to Existing record_* Functions

**Files:**
- Modify: `src/context_service/telemetry/metrics.py`

- [ ] **Step 1: Update record_mcp_tool signature**

Find `record_mcp_tool` and add `silo_id: str | None = None` parameter:

```python
def record_mcp_tool(
    tool_name: str,
    duration_ms: float,
    success: bool = True,
    silo_id: str | None = None,
) -> None:
    """Record MCP tool invocation metrics."""
    if _mcp_tool_duration is None or _mcp_tool_counter is None:
        return
    attributes = {"tool": tool_name, "success": str(success).lower()}
    if silo_id:
        attributes["silo_id"] = silo_id
    _mcp_tool_duration.record(duration_ms, attributes)
    _mcp_tool_counter.add(1, attributes)
```

- [ ] **Step 2: Update record_embedding signature**

Add `silo_id` parameter similarly.

- [ ] **Step 3: Update record_llm_call signature**

Add `silo_id` parameter similarly.

- [ ] **Step 4: Run type check**

Run: `just check`
Expected: Pass (callers don't need to change due to default)

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/metrics.py
git commit -m "feat(telemetry): add silo_id tag to existing metrics"
```

---

### Task 7: Wire record_belief_confidence in believe.py

**Files:**
- Modify: `src/context_service/mcp/tools/believe.py`

- [ ] **Step 1: Add import**

```python
from context_service.telemetry.metrics import record_belief_confidence
```

- [ ] **Step 2: Call after successful belief creation**

Find where the belief node is created successfully and add:

```python
record_belief_confidence(result.confidence, silo_id=silo_id)
```

- [ ] **Step 3: Run type check**

Run: `just check`
Expected: Pass

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/believe.py
git commit -m "feat(telemetry): wire record_belief_confidence in believe tool"
```

---

### Task 8: Wire record_belief_confidence in commit.py

**Files:**
- Modify: `src/context_service/mcp/tools/commit.py`

- [ ] **Step 1: Add import**

```python
from context_service.telemetry.metrics import record_belief_confidence
```

- [ ] **Step 2: Call after successful commit**

Find where commitments are created and add the metric call.

- [ ] **Step 3: Run type check**

Run: `just check`
Expected: Pass

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/commit.py
git commit -m "feat(telemetry): wire record_belief_confidence in commit tool"
```

---

### Task 9: Complete record_chain_evidence_modified Stub

**Files:**
- Modify: `src/context_service/engine/chain_applicability.py`

- [ ] **Step 1: Find the TODO at line ~408**

Search for the comment about `record_chain_evidence_modified`.

- [ ] **Step 2: Add the metric call**

```python
from context_service.telemetry.metrics import record_chain_evidence_modified

# Where chain evidence is modified:
record_chain_evidence_modified(silo_id=silo_id)
```

- [ ] **Step 3: Run type check**

Run: `just check`
Expected: Pass

- [ ] **Step 4: Commit**

```bash
git add src/context_service/engine/chain_applicability.py
git commit -m "feat(telemetry): complete record_chain_evidence_modified wiring"
```

---

## Phase 2: Recall and Cache Visibility

### Task 10: Add Cache and Recall Metric Instruments

**Files:**
- Modify: `src/context_service/telemetry/metrics.py`

- [ ] **Step 1: Add global instrument variables**

After existing globals:

```python
_cache_hit_counter: metrics.Counter | None = None
_cache_miss_counter: metrics.Counter | None = None
_cache_eviction_counter: metrics.Counter | None = None
_recall_latency: metrics.Histogram | None = None
_recall_depth_counter: metrics.Counter | None = None
_recall_result_count: metrics.Histogram | None = None
```

- [ ] **Step 2: Initialize instruments in setup_metrics**

```python
_cache_hit_counter = _meter.create_counter(
    name="cache.hit",
    description="Cache hits",
    unit="1",
)
_cache_miss_counter = _meter.create_counter(
    name="cache.miss",
    description="Cache misses",
    unit="1",
)
_cache_eviction_counter = _meter.create_counter(
    name="cache.eviction",
    description="Cache evictions",
    unit="1",
)
_recall_latency = _meter.create_histogram(
    name="recall.latency",
    description="Recall operation latency",
    unit="ms",
)
_recall_depth_counter = _meter.create_counter(
    name="recall.depth",
    description="Recall depth distribution",
    unit="1",
)
_recall_result_count = _meter.create_histogram(
    name="recall.result_count",
    description="Number of results returned by recall",
    unit="1",
)
```

- [ ] **Step 3: Add record functions**

```python
def record_cache_hit(cache_type: str, silo_id: str | None = None) -> None:
    if _cache_hit_counter is None:
        return
    attrs = {"cache_type": cache_type}
    if silo_id:
        attrs["silo_id"] = silo_id
    _cache_hit_counter.add(1, attrs)


def record_cache_miss(cache_type: str, silo_id: str | None = None) -> None:
    if _cache_miss_counter is None:
        return
    attrs = {"cache_type": cache_type}
    if silo_id:
        attrs["silo_id"] = silo_id
    _cache_miss_counter.add(1, attrs)


def record_cache_eviction(cache_type: str, silo_id: str | None = None) -> None:
    if _cache_eviction_counter is None:
        return
    attrs = {"cache_type": cache_type}
    if silo_id:
        attrs["silo_id"] = silo_id
    _cache_eviction_counter.add(1, attrs)


def record_recall_latency(
    duration_ms: float,
    depth: int,
    source: str,
    silo_id: str | None = None,
) -> None:
    if _recall_latency is None:
        return
    attrs = {"depth": str(depth), "source": source}
    if silo_id:
        attrs["silo_id"] = silo_id
    _recall_latency.record(duration_ms, attrs)


def record_recall_depth(depth: int, silo_id: str | None = None) -> None:
    if _recall_depth_counter is None:
        return
    attrs = {"depth": str(depth)}
    if silo_id:
        attrs["silo_id"] = silo_id
    _recall_depth_counter.add(1, attrs)


def record_recall_result_count(
    count: int,
    layer: str,
    silo_id: str | None = None,
) -> None:
    if _recall_result_count is None:
        return
    attrs = {"layer": layer}
    if silo_id:
        attrs["silo_id"] = silo_id
    _recall_result_count.record(count, attrs)
```

- [ ] **Step 4: Run type check**

Run: `just check`
Expected: Pass

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/metrics.py
git commit -m "feat(telemetry): add cache and recall metric instruments"
```

---

### Task 11: Instrument result_cache.py

**Files:**
- Modify: `src/context_service/cache/result_cache.py`

- [ ] **Step 1: Add imports**

```python
from context_service.telemetry.metrics import record_cache_hit, record_cache_miss
```

- [ ] **Step 2: Add hit/miss in get method**

In the `get` method, after checking if value exists:

```python
if cached is not None:
    record_cache_hit("result", silo_id=silo_id)
    return cached
record_cache_miss("result", silo_id=silo_id)
return None
```

- [ ] **Step 3: Run tests**

Run: `just test -k result_cache`
Expected: Pass

- [ ] **Step 4: Commit**

```bash
git add src/context_service/cache/result_cache.py
git commit -m "feat(telemetry): add cache hit/miss metrics to result_cache"
```

---

### Task 12: Instrument node_cache.py

**Files:**
- Modify: `src/context_service/cache/node_cache.py`

- [ ] **Step 1: Add imports**

```python
from context_service.telemetry.metrics import record_cache_hit, record_cache_miss
```

- [ ] **Step 2: Add hit/miss tracking**

Same pattern as result_cache.

- [ ] **Step 3: Run tests**

Run: `just test -k node_cache`
Expected: Pass

- [ ] **Step 4: Commit**

```bash
git add src/context_service/cache/node_cache.py
git commit -m "feat(telemetry): add cache hit/miss metrics to node_cache"
```

---

### Task 13: Instrument alias_cache.py

**Files:**
- Modify: `src/context_service/cache/alias_cache.py`

- [ ] **Step 1: Add imports and hit/miss tracking**

Same pattern as previous cache files.

- [ ] **Step 2: Run tests**

Run: `just test -k alias_cache`
Expected: Pass

- [ ] **Step 3: Commit**

```bash
git add src/context_service/cache/alias_cache.py
git commit -m "feat(telemetry): add cache hit/miss metrics to alias_cache"
```

---

### Task 14: Instrument recall.py with Latency and Depth

**Files:**
- Modify: `src/context_service/mcp/tools/recall.py`

- [ ] **Step 1: Add imports**

```python
from context_service.telemetry.metrics import (
    record_recall_latency,
    record_recall_depth,
    record_recall_result_count,
)
```

- [ ] **Step 2: Add timing and metrics**

Wrap the recall logic with timing and record metrics:

```python
import time

start = time.perf_counter()
# ... existing recall logic ...
duration_ms = (time.perf_counter() - start) * 1000

# Determine source (cache, search, graph)
source = "cache" if from_cache else ("graph" if depth > 0 else "search")

record_recall_latency(duration_ms, depth=depth, source=source, silo_id=silo_id)
record_recall_depth(depth, silo_id=silo_id)
record_recall_result_count(len(results), layer=layer, silo_id=silo_id)
```

- [ ] **Step 3: Run tests**

Run: `just test -k recall`
Expected: Pass

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/recall.py
git commit -m "feat(telemetry): add latency, depth, and result count metrics to recall"
```

---

## Phase 3: Epistemic Health and Errors

### Task 15: Add Error and Supersession Metrics

**Files:**
- Modify: `src/context_service/telemetry/metrics.py`

- [ ] **Step 1: Add global instrument variables**

```python
_tool_error_counter: metrics.Counter | None = None
_supersession_used_counter: metrics.Counter | None = None
_supersession_skipped_counter: metrics.Counter | None = None
_node_confidence: metrics.Histogram | None = None
```

- [ ] **Step 2: Initialize in setup_metrics**

```python
_tool_error_counter = _meter.create_counter(
    name="tool.error",
    description="Tool errors by type",
    unit="1",
)
_supersession_used_counter = _meter.create_counter(
    name="store.supersession_used",
    description="Writes that used supersession",
    unit="1",
)
_supersession_skipped_counter = _meter.create_counter(
    name="store.supersession_skipped",
    description="Duplicates caught by Custodian that should have been supersession",
    unit="1",
)
_node_confidence = _meter.create_histogram(
    name="node.confidence",
    description="Confidence distribution at write time",
    unit="1",
)
```

- [ ] **Step 3: Add record functions**

```python
def record_tool_error(
    tool_name: str,
    error_type: str,
    silo_id: str | None = None,
) -> None:
    if _tool_error_counter is None:
        return
    attrs = {"tool": tool_name, "error_type": error_type}
    if silo_id:
        attrs["silo_id"] = silo_id
    _tool_error_counter.add(1, attrs)


def record_supersession_used(tool_name: str, silo_id: str | None = None) -> None:
    if _supersession_used_counter is None:
        return
    attrs = {"tool": tool_name}
    if silo_id:
        attrs["silo_id"] = silo_id
    _supersession_used_counter.add(1, attrs)


def record_supersession_skipped(silo_id: str | None = None) -> None:
    if _supersession_skipped_counter is None:
        return
    attrs = {}
    if silo_id:
        attrs["silo_id"] = silo_id
    _supersession_skipped_counter.add(1, attrs)


def record_node_confidence(
    confidence: float,
    layer: str,
    silo_id: str | None = None,
) -> None:
    if _node_confidence is None:
        return
    attrs = {"layer": layer}
    if silo_id:
        attrs["silo_id"] = silo_id
    _node_confidence.record(confidence, attrs)
```

- [ ] **Step 4: Run type check**

Run: `just check`
Expected: Pass

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/metrics.py
git commit -m "feat(telemetry): add error, supersession, and confidence metrics"
```

---

### Task 16: Wire Supersession and Confidence in remember.py

**Files:**
- Modify: `src/context_service/mcp/tools/remember.py`

- [ ] **Step 1: Add imports**

```python
from context_service.telemetry.metrics import record_node_confidence, record_supersession_used
```

- [ ] **Step 2: Record confidence after successful store**

```python
record_node_confidence(result.confidence, layer="memory", silo_id=silo_id)
```

- [ ] **Step 3: Record supersession if used**

```python
if supersedes:
    record_supersession_used("remember", silo_id=silo_id)
```

- [ ] **Step 4: Run tests**

Run: `just test -k remember`
Expected: Pass

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/remember.py
git commit -m "feat(telemetry): add confidence and supersession metrics to remember"
```

---

### Task 17: Wire Supersession and Confidence in learn.py

**Files:**
- Modify: `src/context_service/mcp/tools/learn.py`

- [ ] **Step 1: Add imports and metrics**

Same pattern as remember.py but with `layer="knowledge"`.

- [ ] **Step 2: Run tests**

Run: `just test -k learn`
Expected: Pass

- [ ] **Step 3: Commit**

```bash
git add src/context_service/mcp/tools/learn.py
git commit -m "feat(telemetry): add confidence and supersession metrics to learn"
```

---

### Task 18: Wire Confidence in believe.py

**Files:**
- Modify: `src/context_service/mcp/tools/believe.py`

- [ ] **Step 1: Add record_node_confidence call**

```python
record_node_confidence(result.confidence, layer="wisdom", silo_id=silo_id)
```

- [ ] **Step 2: Run tests**

Run: `just test -k believe`
Expected: Pass

- [ ] **Step 3: Commit**

```bash
git add src/context_service/mcp/tools/believe.py
git commit -m "feat(telemetry): add confidence histogram to believe"
```

---

### Task 19: Wire tool.error in MCP Tool Wrappers

**Files:**
- Modify: `src/context_service/mcp/server.py` or tool wrapper pattern

- [ ] **Step 1: Add import in server.py**

```python
from context_service.telemetry.metrics import record_tool_error
```

- [ ] **Step 2: Add error recording in exception handler**

In the MCP tool dispatch error handler:

```python
except Exception as e:
    record_tool_error(tool_name, type(e).__name__, silo_id=silo_id)
    raise
```

- [ ] **Step 3: Run tests**

Run: `just test -k mcp`
Expected: Pass

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/server.py
git commit -m "feat(telemetry): track tool errors by type"
```

---

### Task 20: Wire supersession_skipped in Custodian

**Files:**
- Modify: `src/context_service/sage/custodian/dispatch.py`

- [ ] **Step 1: Add import**

```python
from context_service.telemetry.metrics import record_supersession_skipped
```

- [ ] **Step 2: Find duplicate detection logic**

Look for where Custodian detects duplicates that should have been supersession.

- [ ] **Step 3: Add metric call**

```python
record_supersession_skipped(silo_id=silo_id)
```

- [ ] **Step 4: Run tests**

Run: `just test -k custodian`
Expected: Pass

- [ ] **Step 5: Commit**

```bash
git add src/context_service/sage/custodian/dispatch.py
git commit -m "feat(telemetry): track supersession_skipped in Custodian"
```

---

## Final Steps

### Task 21: Integration Test

- [ ] **Step 1: Run full test suite**

Run: `just ci`
Expected: All tests pass, type checks pass

- [ ] **Step 2: Local smoke test**

Run: `just up && just dev`
Then make some MCP tool calls and verify metrics are emitted (check logs for OTEL export).

- [ ] **Step 3: Commit any fixes**

---

### Task 22: Deploy and Verify

- [ ] **Step 1: Deploy infrastructure**

Run: `cd infra && pulumi up --stack beta`

- [ ] **Step 2: Verify SignozHost is running**

Run: `gcloud compute ssh engrammic-beta-signoz --zone=europe-north1-b --command="docker ps"`
Expected: Shows clickhouse, signoz-otel-collector, signoz-query, signoz-frontend

- [ ] **Step 3: Open SigNoz UI**

Run: `just signoz-tunnel`
Open: http://localhost:3301
Expected: SigNoz UI loads

- [ ] **Step 4: Verify metrics flowing**

Make some API calls and check SigNoz dashboards for metrics.

---

## Done Criteria

- [ ] SigNoz running on dedicated VM (`signoz.engrammic.internal`)
- [ ] IAP tunnel accessible via `just signoz-tunnel`
- [ ] All MCP tools emit metrics with `silo_id` tag
- [ ] Cache hit/miss visible per cache type
- [ ] Recall latency histogram with depth and source tags
- [ ] Confidence distribution visible per layer
- [ ] Supersession usage tracked

---

## Out of Scope

- Alerting via AlertManager (post-beta)
- Dagster asset instrumentation (use Dagster UI)
- SAGE synthesizer effectiveness metrics (post-beta)
- Graph node/edge count gauges (separate Dagster job)
