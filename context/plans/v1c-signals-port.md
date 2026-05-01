# v1c Signals Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port heat / freshness / priority signal subsystems from `contextr` into `src/context_service/signals/`, ship Phase 1 (stubbed heat + real freshness/priority + live access-event emitters + priority-ranked consensus) this week, defer Phase 2 (real heat Dagster asset + cursor + schedule) until after partner talks.

**Architecture:** Phase 1 introduces `signals/` as the single home for heat lookup, freshness scoring, priority math, and access-event emission. Heat is stubbed at 0.5 with a stable signature so callers don't refactor when Phase 2 flips it to a real Memgraph read. Freshness is wired into `services/context.py::query` as a multiplicative score adjustment; priority replaces the consensus sensor's simple `(distinct_agents, chain_count)` ordering with a Python-side ranking that pulls heat for each candidate. Access-event emission is best-effort XADD on a per-silo Redis stream, fired from each MCP read tool. Phase 2 ports the contextr Dagster heat asset wholesale, substituting a Memgraph singleton `:HeatCursor` for contextr's Postgres cursor table.

**Tech Stack:** Python 3.12, asyncio, Pydantic v2 (`pydantic-settings`), structlog, redis.asyncio (XADD streams), neo4j async driver (Memgraph bolt), pytest + pytest-asyncio, Dagster (Phase 2 only).

**Spec:** `context/specs/signals-port.md`
**Branch:** `phase-signals-port` (already cut, docs commit `66eb71e` landed)
**Plan filename convention:** `v1c-` prefix matches existing `v1a-*` / `v1b-*` plans in `context/plans/`.

---

## File Structure

Phase 1 creates / modifies:

| Path | Status | Responsibility |
|---|---|---|
| `src/context_service/signals/__init__.py` | modify | Public re-exports: `get_heat`, `compute_freshness`, `compute_consensus_priority`, `emit_access_event`. |
| `src/context_service/signals/heat.py` | create | `async def get_heat(memgraph, node_id, silo_id) -> float` — Phase 1 stub returning 0.5, single `heat.stub_active` log per silo per process. |
| `src/context_service/signals/freshness.py` | create | Pure `compute_freshness(created_at, now, sigma_days=30) -> float`. |
| `src/context_service/signals/priority.py` | create | Move of `custodian/priority.py::compute_consensus_priority` — formula unchanged. |
| `src/context_service/signals/access_events.py` | create | `async def emit_access_event(redis, silo_id, node_id)` — best-effort XADD with try/except. |
| `src/context_service/custodian/priority.py` | modify | Reduce to a one-line re-export of `signals.priority.compute_consensus_priority` for back-compat. |
| `src/context_service/stores/redis.py` | modify | Add `xadd(stream_key, fields, maxlen=None, approximate=True)` method on `RedisClient`. |
| `src/context_service/config/settings.py` | modify | Add `freshness_weight: float = 0.3`, `freshness_sigma_days: int = 30`, `access_stream_maxlen: int = 100_000`. |
| `src/context_service/services/context.py` | modify | Apply freshness multiplier in `query()` after candidate filtering, before final return. |
| `src/context_service/mcp/tools/context_get.py` | modify | After `ctx_svc.get` succeeds, emit access event per resolved node. |
| `src/context_service/mcp/tools/context_query.py` | modify | After result list is built, emit access event per result node. |
| `src/context_service/mcp/server.py` | modify (verify) | Confirm `RedisClient` is reachable from MCP tools via `get_redis()` helper; add helper if missing. |
| `src/context_service/custodian/sensors/consensus.py` | modify | Extend Cypher to return `avg_chain_confidence`; rank candidates Python-side via `compute_consensus_priority` with heat fetched from `signals.heat.get_heat`. |
| `tests/test_signals_freshness.py` | create | Table-driven freshness cases. |
| `tests/test_signals_priority.py` | create | Priority formula edge cases. |
| `tests/test_signals_access_events.py` | create | XADD shape + Redis-failure swallowing. |
| `tests/test_signals_heat_stub.py` | create | Stub returns 0.5; logs once per silo. |
| `tests/test_consensus_priority_ordering.py` | create | Sensor returns priority-ranked candidates. |
| `tests/test_context_query_freshness.py` | create | Fresher candidate ranks higher when freshness_weight > 0. |

Phase 2 creates / modifies:

| Path | Status | Responsibility |
|---|---|---|
| `src/context_service/signals/cursor.py` | create | `fetch_or_init_heat_cursor`, `advance_heat_cursor` against `:HeatCursor` singleton. |
| `src/context_service/signals/heat.py` | modify | Flip stub → real Memgraph read; remove `heat.stub_active` log. |
| `src/context_service/pipelines/assets/heat.py` | create | Direct port of contextr asset, substituting Memgraph cursor for Postgres. |
| `src/context_service/pipelines/schedules.py` | modify | Add hourly per-silo heat schedule. |
| `src/context_service/db/indexes.py` | modify | Add `:HeatCursor(silo_id)` and `:Cluster(tier)` indexes. |
| `src/context_service/custodian/sensors/consensus.py` | modify | Replace per-candidate heat fetch with batched `UNWIND` query. |
| `tests/test_signals_cursor.py` | create | Cursor init + atomic advance. |
| `tests/test_pipelines_heat_asset.py` | create | Asset materialises heat scores + tiers on a seeded silo. |

---

## Phase 1

### Task 1: Add `xadd` method to RedisClient

**Files:**
- Modify: `src/context_service/stores/redis.py` (after `delete`, before `close`)
- Test: `tests/test_signals_access_events.py` (covers this method indirectly via the emitter test in Task 5)

- [ ] **Step 1: Add the method**

In `src/context_service/stores/redis.py`, add immediately above `async def close`:

```python
    async def xadd(
        self,
        stream_key: str,
        fields: dict[str, str | bytes],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str | None:
        """Append an entry to a Redis stream.

        Best-effort: connection / Redis errors are logged and swallowed,
        returning None so callers in hot paths never raise.

        Args:
            stream_key: Stream key (e.g. ``silo:{silo_id}:access_events``).
            fields: Field name -> value pairs. Strings are encoded as UTF-8.
            maxlen: Optional cap on stream length.
            approximate: When True, uses ``MAXLEN ~`` (cheap, slightly fuzzy cap).

        Returns:
            The generated entry ID on success, or None on failure.
        """
        encoded: dict[bytes, bytes] = {}
        for k, v in fields.items():
            key_b = k.encode() if isinstance(k, str) else k
            val_b = v.encode() if isinstance(v, str) else v
            encoded[key_b] = val_b
        try:
            if maxlen is not None:
                entry_id = await self._redis.xadd(
                    stream_key, encoded, maxlen=maxlen, approximate=approximate
                )
            else:
                entry_id = await self._redis.xadd(stream_key, encoded)
            return entry_id.decode() if isinstance(entry_id, bytes) else entry_id
        except (RedisConnectionError, RedisError) as e:
            logger.warning("redis_xadd_failed", stream_key=stream_key, error=str(e))
            return None
```

- [ ] **Step 2: Run typecheck**

Run: `just typecheck`
Expected: PASS (no new mypy errors).

- [ ] **Step 3: Commit**

```bash
git add src/context_service/stores/redis.py
git commit -m "feat(redis): add best-effort xadd for streams"
```

---

### Task 2: Add freshness module + tests

**Files:**
- Create: `src/context_service/signals/freshness.py`
- Test: `tests/test_signals_freshness.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_signals_freshness.py`:

```python
"""Tests for signals.freshness.compute_freshness."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from context_service.signals.freshness import compute_freshness


NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)


def test_t_zero_returns_one() -> None:
    assert compute_freshness(NOW, NOW, sigma_days=30) == pytest.approx(1.0)


def test_t_equals_sigma_returns_exp_minus_half() -> None:
    created = NOW - timedelta(days=30)
    expected = math.exp(-0.5)  # ~0.6065
    assert compute_freshness(created, NOW, sigma_days=30) == pytest.approx(expected, rel=1e-6)


def test_t_three_sigma_clamped_to_floor() -> None:
    created = NOW - timedelta(days=90)
    assert compute_freshness(created, NOW, sigma_days=30) == 0.25


def test_far_future_clock_skew_clamped_to_one() -> None:
    created = NOW + timedelta(days=10)
    assert compute_freshness(created, NOW, sigma_days=30) == 1.0


def test_floor_applies_for_very_old_content() -> None:
    created = NOW - timedelta(days=10_000)
    assert compute_freshness(created, NOW, sigma_days=30) == 0.25


def test_naive_datetime_treated_as_utc() -> None:
    naive_now = datetime(2026, 5, 1)
    naive_created = datetime(2026, 5, 1)
    assert compute_freshness(naive_created, naive_now, sigma_days=30) == pytest.approx(1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_signals_freshness.py -v`
Expected: FAIL — `ModuleNotFoundError: context_service.signals.freshness`.

- [ ] **Step 3: Implement freshness**

Create `src/context_service/signals/freshness.py`:

```python
"""Freshness scoring (Gaussian decay with floor).

Pure function: no I/O. Used in retrieval ranking by services/context.py.
"""

from __future__ import annotations

import math
from datetime import datetime

FRESHNESS_FLOOR = 0.25


def compute_freshness(
    created_at: datetime,
    now: datetime,
    sigma_days: int = 30,
) -> float:
    """Gaussian decay freshness score in [FRESHNESS_FLOOR, 1.0].

    Score is ``max(FRESHNESS_FLOOR, exp(-0.5 * (t/sigma)**2))`` where ``t`` is
    age in days. Clock-skewed future timestamps clamp to 1.0.

    Args:
        created_at: When the node was created.
        now: Reference time (caller passes a single ``datetime.now(UTC)`` for
            an entire ranking pass to keep scores consistent).
        sigma_days: Width of the Gaussian. Default 30; older than ~3*sigma
            saturates at the floor.

    Returns:
        Float in [FRESHNESS_FLOOR, 1.0].
    """
    delta = now - created_at
    days = delta.total_seconds() / 86400.0
    if days <= 0:
        return 1.0
    score = math.exp(-0.5 * (days / sigma_days) ** 2)
    return max(FRESHNESS_FLOOR, score)


__all__ = ["FRESHNESS_FLOOR", "compute_freshness"]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_signals_freshness.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/signals/freshness.py tests/test_signals_freshness.py
git commit -m "feat(signals): freshness scoring (Gaussian decay)"
```

---

### Task 3: Move priority module + tests

**Files:**
- Create: `src/context_service/signals/priority.py`
- Modify: `src/context_service/custodian/priority.py` (reduce to re-export)
- Test: `tests/test_signals_priority.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_signals_priority.py`:

```python
"""Tests for signals.priority.compute_consensus_priority."""

from __future__ import annotations

import math

import pytest

from context_service.signals.priority import compute_consensus_priority


def test_zero_heat_yields_zero_priority() -> None:
    assert compute_consensus_priority(0.5, 0.0, 3) == 0.0


def test_full_confidence_yields_zero_priority() -> None:
    assert compute_consensus_priority(1.0, 0.8, 3) == 0.0


def test_single_agent_low_priority() -> None:
    """Agent count = 1 yields log(2) factor — low compared to multi-agent."""
    single = compute_consensus_priority(0.2, 0.8, 1)
    multi = compute_consensus_priority(0.2, 0.8, 3)
    assert single < multi
    assert single == pytest.approx((1 - 0.2) * 0.8 * math.log(2))


def test_agent_count_caps_at_five() -> None:
    five = compute_consensus_priority(0.3, 0.7, 5)
    ten = compute_consensus_priority(0.3, 0.7, 10)
    assert five == pytest.approx(ten)


def test_confidence_clamped_to_unit_interval() -> None:
    assert compute_consensus_priority(-0.5, 0.5, 3) == compute_consensus_priority(0.0, 0.5, 3)
    assert compute_consensus_priority(2.0, 0.5, 3) == compute_consensus_priority(1.0, 0.5, 3)


def test_back_compat_re_export() -> None:
    """custodian.priority must still expose compute_consensus_priority for legacy callers."""
    from context_service.custodian.priority import (
        compute_consensus_priority as legacy,
    )
    from context_service.signals.priority import compute_consensus_priority as canonical

    assert legacy is canonical
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_signals_priority.py -v`
Expected: FAIL — `ModuleNotFoundError: context_service.signals.priority`.

- [ ] **Step 3: Create signals/priority.py**

Create `src/context_service/signals/priority.py`:

```python
"""Priority formulas for Custodian task types.

Moved from custodian/priority.py during the v1c signals port. The custodian
module re-exports this function for back-compat with existing imports.
"""

from __future__ import annotations

import math


def compute_consensus_priority(
    avg_chain_confidence: float,
    avg_heat: float,
    distinct_agent_count: int,
) -> float:
    """Compute priority for the consensus_on_chains custodian task.

    Formula: ``(1 - avg_confidence) * avg_heat * log(min(distinct_agents, 5) + 1)``.

    Caps agent diversity at 5 (R16-10 — diminishing returns). The formula
    blocks the self-promotion loop by construction: N self-copies count as a
    single distinct agent, yielding low priority.
    """
    capped_agents = min(distinct_agent_count, 5)
    confidence_gap = 1.0 - max(0.0, min(1.0, avg_chain_confidence))
    heat_factor = max(0.0, min(1.0, avg_heat))
    agent_factor = math.log(capped_agents + 1)

    return confidence_gap * heat_factor * agent_factor


__all__ = ["compute_consensus_priority"]
```

- [ ] **Step 4: Reduce custodian/priority.py to a re-export**

Replace the contents of `src/context_service/custodian/priority.py` with:

```python
"""Back-compat shim: priority formulas now live in signals.priority.

Legacy import path retained so existing callers keep working until they
migrate to ``context_service.signals.priority`` directly.
"""

from __future__ import annotations

from context_service.signals.priority import compute_consensus_priority

__all__ = ["compute_consensus_priority"]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_signals_priority.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/context_service/signals/priority.py src/context_service/custodian/priority.py tests/test_signals_priority.py
git commit -m "refactor(signals): move priority formula from custodian to signals"
```

---

### Task 4: Add heat stub + tests

**Files:**
- Create: `src/context_service/signals/heat.py`
- Test: `tests/test_signals_heat_stub.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_signals_heat_stub.py`:

```python
"""Phase-1 stub coverage for signals.heat.get_heat.

Phase 2 swaps this for a real Memgraph read; the test suite for that lives
in test_signals_heat.py (created in Phase 2).
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from context_service.signals.heat import _STUB_LOG_GUARD, get_heat


@pytest.fixture(autouse=True)
def _reset_stub_log_guard() -> None:
    _STUB_LOG_GUARD.clear()
    yield
    _STUB_LOG_GUARD.clear()


@pytest.mark.asyncio
async def test_stub_returns_neutral() -> None:
    memgraph = AsyncMock()
    result = await get_heat(memgraph, "node-1", "silo-a")
    assert result == 0.5


@pytest.mark.asyncio
async def test_stub_does_not_touch_memgraph() -> None:
    memgraph = AsyncMock()
    await get_heat(memgraph, "node-1", "silo-a")
    memgraph.execute_query.assert_not_called()


@pytest.mark.asyncio
async def test_stub_logs_once_per_silo(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    memgraph = AsyncMock()

    await get_heat(memgraph, "node-1", "silo-a")
    await get_heat(memgraph, "node-2", "silo-a")
    await get_heat(memgraph, "node-3", "silo-b")

    stub_logs = [r for r in caplog.records if "heat.stub_active" in r.getMessage()]
    silos_logged = {r.__dict__.get("silo_id") for r in stub_logs}
    assert len(stub_logs) == 2
    assert silos_logged == {"silo-a", "silo-b"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_signals_heat_stub.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the stub**

Create `src/context_service/signals/heat.py`:

```python
"""Heat lookup.

Phase 1 (this file) is a stub returning a neutral 0.5 so the priority formula
remains well-defined while the real heat asset is deferred to Phase 2.
The function signature is the Phase 2 signature so callers don't refactor
when the stub flips to a Memgraph read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from context_service.stores import MemgraphClient

logger = structlog.get_logger(__name__)

STUB_HEAT_VALUE = 0.5

# Process-local set: silo_ids for which we have already emitted the
# heat.stub_active log line. Cleared in tests via fixture.
_STUB_LOG_GUARD: set[str] = set()


async def get_heat(
    memgraph: MemgraphClient,  # noqa: ARG001  -- Phase 2 will use this
    node_id: str,
    silo_id: str,
) -> float:
    """Return the heat score for a node.

    Phase 1: returns ``STUB_HEAT_VALUE`` (0.5) without touching Memgraph.
    Phase 2: reads ``n.heat_score`` from Memgraph; falls back to 0.5 if absent.
    """
    if silo_id not in _STUB_LOG_GUARD:
        _STUB_LOG_GUARD.add(silo_id)
        logger.info("heat.stub_active", silo_id=silo_id)
    return STUB_HEAT_VALUE


__all__ = ["STUB_HEAT_VALUE", "get_heat"]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_signals_heat_stub.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/signals/heat.py tests/test_signals_heat_stub.py
git commit -m "feat(signals): heat get_heat() Phase-1 stub"
```

---

### Task 5: Add access-event emitter + tests

**Files:**
- Create: `src/context_service/signals/access_events.py`
- Test: `tests/test_signals_access_events.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_signals_access_events.py`:

```python
"""Tests for signals.access_events.emit_access_event."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_service.signals.access_events import (
    ACCESS_STREAM_MAXLEN,
    access_stream_key,
    emit_access_event,
)


@pytest.mark.asyncio
async def test_emit_calls_xadd_with_expected_shape() -> None:
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value="1700000000-0")

    await emit_access_event(redis, "silo-a", "node-42")

    redis.xadd.assert_awaited_once()
    args, kwargs = redis.xadd.call_args
    assert args[0] == "silo:silo-a:access_events"
    assert args[1] == {"node_id": "node-42"}
    assert kwargs == {"maxlen": ACCESS_STREAM_MAXLEN, "approximate": True}


@pytest.mark.asyncio
async def test_emit_swallows_redis_failure() -> None:
    redis = AsyncMock()
    redis.xadd = AsyncMock(side_effect=RuntimeError("connection refused"))

    # Must not raise.
    await emit_access_event(redis, "silo-a", "node-42")


def test_access_stream_key_format() -> None:
    assert access_stream_key("silo-x") == "silo:silo-x:access_events"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_signals_access_events.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the emitter**

Create `src/context_service/signals/access_events.py`:

```python
"""Access-event emission for the heat asset.

Each MCP read tool calls ``emit_access_event`` after a node is resolved into
user-visible output. Events land on a per-silo Redis stream which the Phase-2
heat Dagster asset drains hourly to compute decay-weighted heat scores.

This is a best-effort signal: Redis errors are logged and swallowed so a
broken Redis never blocks reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from context_service.stores import RedisClient

logger = structlog.get_logger(__name__)

# Stream cap. Approximate trim — at the default cadence (~1h between heat
# asset runs), 100k entries permits ~28 events/sec sustained without loss.
ACCESS_STREAM_MAXLEN = 100_000


def access_stream_key(silo_id: str) -> str:
    """Build the per-silo access-event stream key."""
    return f"silo:{silo_id}:access_events"


async def emit_access_event(
    redis: RedisClient,
    silo_id: str,
    node_id: str,
) -> None:
    """Append an access event to the silo's stream. Best-effort.

    Failures are logged and swallowed — never raised — so callers in MCP read
    paths don't need a try/except around every emit.
    """
    try:
        await redis.xadd(
            access_stream_key(silo_id),
            {"node_id": str(node_id)},
            maxlen=ACCESS_STREAM_MAXLEN,
            approximate=True,
        )
    except Exception as exc:
        logger.warning(
            "access_event_emit_failed",
            silo_id=silo_id,
            node_id=str(node_id),
            error=str(exc),
        )


__all__ = ["ACCESS_STREAM_MAXLEN", "access_stream_key", "emit_access_event"]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_signals_access_events.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/signals/access_events.py tests/test_signals_access_events.py
git commit -m "feat(signals): per-silo access-event XADD emitter"
```

---

### Task 6: Wire signals public API

**Files:**
- Modify: `src/context_service/signals/__init__.py`

- [ ] **Step 1: Replace contents**

Replace `src/context_service/signals/__init__.py` with:

```python
"""Signals subsystem: heat, freshness, priority, access-event emission.

Phase 1 (v1c): stubs heat at 0.5; ships real freshness, priority, and live
access-event emitters.
Phase 2 (after partner talks): replaces the heat stub with a Memgraph read
backed by an hourly Dagster asset.
"""

from __future__ import annotations

from context_service.signals.access_events import (
    ACCESS_STREAM_MAXLEN,
    access_stream_key,
    emit_access_event,
)
from context_service.signals.freshness import FRESHNESS_FLOOR, compute_freshness
from context_service.signals.heat import STUB_HEAT_VALUE, get_heat
from context_service.signals.priority import compute_consensus_priority

__all__ = [
    "ACCESS_STREAM_MAXLEN",
    "FRESHNESS_FLOOR",
    "STUB_HEAT_VALUE",
    "access_stream_key",
    "compute_consensus_priority",
    "compute_freshness",
    "emit_access_event",
    "get_heat",
]
```

- [ ] **Step 2: Verify imports resolve**

Run: `uv run python -c "from context_service.signals import compute_freshness, compute_consensus_priority, get_heat, emit_access_event; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/context_service/signals/__init__.py
git commit -m "feat(signals): public API surface"
```

---

### Task 7: Add settings for freshness + access stream

**Files:**
- Modify: `src/context_service/config/settings.py`

- [ ] **Step 1: Add settings fields**

Insert into `Settings` immediately above `otel_endpoint: str = ""` (around line 74):

```python
    # Signals (heat / freshness / priority).
    freshness_weight: float = 0.3
    freshness_sigma_days: int = 30
    access_stream_maxlen: int = 100_000
```

- [ ] **Step 2: Verify settings load**

Run: `uv run python -c "from context_service.config.settings import get_settings; s = get_settings(); print(s.freshness_weight, s.freshness_sigma_days, s.access_stream_maxlen)"`
Expected: prints `0.3 30 100000`.

- [ ] **Step 3: Commit**

```bash
git add src/context_service/config/settings.py
git commit -m "feat(config): freshness + access-stream settings"
```

---

### Task 8: Apply freshness in `services/context.py::query`

**Files:**
- Modify: `src/context_service/services/context.py` (around lines 902-944, the `query` result-build block)
- Test: `tests/test_context_query_freshness.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_context_query_freshness.py`:

```python
"""End-to-end freshness ranking test for ContextService.query.

Uses a stubbed embedding service + an in-memory fake of the qdrant + memgraph
batch fetch path, so the test isolates the freshness multiplier behaviour.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from context_service.services.context import ContextService
from context_service.services.models import Node, ScopeContext


NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _make_node(node_id: str, created_at: datetime, content: str) -> Node:
    return Node(
        id=uuid.UUID(node_id),
        type="Document",
        content=content,
        silo_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        properties={"layer": "memory", "confidence": 1.0},
        source_uri=None,
        content_hash=None,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_fresher_candidate_outranks_stale_when_scores_tied(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_id = "11111111-1111-1111-1111-111111111111"
    stale_id = "22222222-2222-2222-2222-222222222222"
    fresh_node = _make_node(fresh_id, NOW - timedelta(days=1), "fresh")
    stale_node = _make_node(stale_id, NOW - timedelta(days=120), "stale")

    embedding = AsyncMock()
    embedding.embed_query = AsyncMock(return_value=[0.0] * 8)

    qdrant = AsyncMock()
    qdrant.search = AsyncMock(
        return_value=[
            SimpleNamespace(node_id=stale_id, score=0.9),
            SimpleNamespace(node_id=fresh_id, score=0.9),
        ]
    )

    svc = ContextService(memgraph=AsyncMock(), qdrant=qdrant, embedding=embedding)

    async def fake_batch_fetch(ids: list[str], silo_id: uuid.UUID) -> dict[str, Node]:
        return {fresh_id: fresh_node, stale_id: stale_node}

    monkeypatch.setattr(svc, "_batch_fetch_nodes", fake_batch_fetch)

    # Pin "now" used by query() so the test is deterministic.
    monkeypatch.setattr("context_service.services.context._now_utc", lambda: NOW)

    scope = ScopeContext(
        org_id="org-test",
        silo_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    )
    results = await svc.query(scope=scope, query="anything")

    assert [str(r.node_id) for r in results] == [fresh_id, stale_id]
    # Fresh node retains a higher relevance_score after the multiplier.
    fresh_score = next(r.relevance_score for r in results if str(r.node_id) == fresh_id)
    stale_score = next(r.relevance_score for r in results if str(r.node_id) == stale_id)
    assert fresh_score > stale_score
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_context_query_freshness.py -v`
Expected: FAIL — `_now_utc` not defined; ordering still by raw score.

- [ ] **Step 3: Add a `_now_utc` indirection**

In `src/context_service/services/context.py`, add at module scope just below the existing `_CREATE_PROPS` definition (near line 54):

```python
def _now_utc() -> datetime:
    """Indirection for testability — patched in tests to pin a fixed reference time."""
    return datetime.now(timezone.utc)
```

Update the import line `from datetime import datetime` (line 9) to:

```python
from datetime import datetime, timezone
```

- [ ] **Step 4: Apply freshness multiplier and re-sort**

In `src/context_service/services/context.py::query`, replace the result-build block (currently lines ~902-936, ending just before the `logger.info("query_complete", ...)` call) with:

```python
        from context_service.config.settings import get_settings
        from context_service.signals import compute_freshness

        settings = get_settings()
        freshness_weight = settings.freshness_weight
        sigma_days = settings.freshness_sigma_days
        now = _now_utc()

        results: list[QueryResult] = []
        for node_id_str in result_ids:
            node = node_map.get(node_id_str)
            if node is None:
                continue

            props = node.properties or {}
            node_layer = props.get("layer", "memory")

            if layer_values and node_layer not in layer_values:
                continue

            node_confidence = float(props.get("confidence", 1.0))
            if min_confidence is not None and node_confidence < min_confidence:
                continue

            node_tags: list[str] = props.get("tags", [])
            if tags_filter and not any(t in node_tags for t in tags_filter):
                continue

            if not include_superseded and props.get("superseded_by"):
                continue

            relevance = score_map[node_id_str]
            if freshness_weight > 0 and node.created_at is not None:
                fresh = compute_freshness(node.created_at, now, sigma_days=sigma_days)
                relevance = relevance * ((1.0 - freshness_weight) + freshness_weight * fresh)

            results.append(
                QueryResult(
                    node_id=node.id,
                    layer=node_layer,
                    content=node.content,
                    confidence=node_confidence,
                    relevance_score=relevance,
                    summary=props.get("summary"),
                    tags=node_tags or None,
                    created_at=node.created_at,
                )
            )

        results.sort(key=lambda r: r.relevance_score, reverse=True)
```

- [ ] **Step 5: Run test**

Run: `uv run pytest tests/test_context_query_freshness.py -v`
Expected: PASS.

- [ ] **Step 6: Run full check**

Run: `just check && just test`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add src/context_service/services/context.py tests/test_context_query_freshness.py
git commit -m "feat(query): apply freshness multiplier in retrieval ranking"
```

---

### Task 9: Wire access-event emission into MCP read tools

**Files:**
- Modify: `src/context_service/mcp/server.py` (verify / add a `get_redis()` helper if missing)
- Modify: `src/context_service/mcp/tools/context_get.py`
- Modify: `src/context_service/mcp/tools/context_query.py`

- [ ] **Step 1: Verify a redis accessor exists in mcp/server.py**

Run: `grep -n "get_redis\|redis" src/context_service/mcp/server.py`
Expected: an existing `get_redis()` (or similar) helper. If absent:
  - Locate the existing `get_context_service`, `get_silo_service`, `get_mcp_auth_context` accessor block.
  - Add alongside them:

    ```python
    def get_redis() -> RedisClient | None:
        """Return the registered Redis client, or None if Redis is not wired."""
        return _redis
    ```

  - Add `_redis: RedisClient | None = None` to the module-level state and set it in the existing `set_context_service(...)` (or equivalent registration function) signature alongside the other deps.

- [ ] **Step 2: Emit from `context_get`**

Modify `src/context_service/mcp/tools/context_get.py`:

  - Add to imports near the top:

    ```python
    from context_service.mcp.server import get_redis
    from context_service.signals import emit_access_event
    ```

  - Inside `context_get`, after the `else` branch that appends a node dict (just before the final `return {"nodes": nodes_out}`), add:

    ```python
        redis = get_redis()
        if redis is not None:
            for n in nodes_out:
                node_id = n.get("node_id")
                if node_id is not None:
                    await emit_access_event(redis, str(resolved_silo_id), node_id)
    ```

  Place this *outside* the per-node loop so a single failed emit doesn't skip subsequent ones (the emitter already swallows errors per call).

- [ ] **Step 3: Emit from `context_query`**

Modify `src/context_service/mcp/tools/context_query.py::_context_query`:

  - Add to imports:

    ```python
    from context_service.mcp.server import get_redis
    from context_service.signals import emit_access_event
    ```

  - Just before the `return { "results": [...], ... }`, add:

    ```python
    redis = get_redis()
    if redis is not None:
        for r in results:
            await emit_access_event(redis, silo_id, str(r.node_id))
    ```

- [ ] **Step 4: Run typecheck**

Run: `just typecheck`
Expected: PASS.

- [ ] **Step 5: Run tests**

Run: `just test`
Expected: green (no test for this wiring at unit level — covered manually in Step 6 and by the β5 integration pack).

- [ ] **Step 6: Manual smoke (skip if Docker stack not running)**

```bash
docker compose ps redis             # confirm redis is up
just dev &                          # FastAPI / MCP server in dev mode
# In another shell: invoke context_get on a known node, then:
docker compose exec redis redis-cli XLEN silo:<silo_id>:access_events
```

Expected: `XLEN` increments by 1 per node returned.

- [ ] **Step 7: Commit**

```bash
git add src/context_service/mcp/server.py src/context_service/mcp/tools/context_get.py src/context_service/mcp/tools/context_query.py
git commit -m "feat(mcp): emit access events from context_get and context_query"
```

---

### Task 10: Priority-rank consensus sensor

**Files:**
- Modify: `src/context_service/custodian/sensors/consensus.py`
- Test: `tests/test_consensus_priority_ordering.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_consensus_priority_ordering.py`:

```python
"""Sensor returns priority-ranked candidates, not (distinct_agents, chain_count)-ranked."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_service.custodian.sensors.consensus import find_consensus_candidates


@pytest.mark.asyncio
async def test_candidates_ranked_by_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """High-confidence candidates rank below low-confidence ones at equal heat / agents."""
    cypher_rows = [
        # high confidence -> low priority despite many agents
        {"commitment_id": "cm-high", "chain_count": 5, "distinct_agents": 5, "avg_chain_confidence": 0.95},
        # low confidence -> high priority even with fewer agents
        {"commitment_id": "cm-low", "chain_count": 2, "distinct_agents": 2, "avg_chain_confidence": 0.10},
    ]
    memgraph = AsyncMock()
    memgraph.execute_query = AsyncMock(return_value=cypher_rows)

    # Stub heat to a constant so ordering depends solely on confidence + agents.
    async def fake_heat(_mg, _node_id, _silo):
        return 0.5

    monkeypatch.setattr(
        "context_service.custodian.sensors.consensus.get_heat", fake_heat
    )

    rows = await find_consensus_candidates(
        memgraph=memgraph,
        silo_id="silo-a",
        min_chain_count=2,
        min_distinct_agents=2,
        limit=10,
    )

    assert [r["commitment_id"] for r in rows] == ["cm-low", "cm-high"]
    assert all("priority" in r for r in rows)
    assert rows[0]["priority"] > rows[1]["priority"]


@pytest.mark.asyncio
async def test_limit_applied_after_priority_sort(monkeypatch: pytest.MonkeyPatch) -> None:
    cypher_rows = [
        {"commitment_id": f"cm-{i}", "chain_count": 2, "distinct_agents": 2, "avg_chain_confidence": c}
        for i, c in enumerate([0.9, 0.1, 0.5, 0.2])
    ]
    memgraph = AsyncMock()
    memgraph.execute_query = AsyncMock(return_value=cypher_rows)

    async def fake_heat(_mg, _node_id, _silo):
        return 0.5

    monkeypatch.setattr(
        "context_service.custodian.sensors.consensus.get_heat", fake_heat
    )

    rows = await find_consensus_candidates(
        memgraph=memgraph,
        silo_id="silo-a",
        min_chain_count=2,
        min_distinct_agents=2,
        limit=2,
    )

    # Top two by priority are the lowest-confidence rows: 0.1 then 0.2.
    assert [r["commitment_id"] for r in rows] == ["cm-1", "cm-3"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_consensus_priority_ordering.py -v`
Expected: FAIL — Cypher does not return `avg_chain_confidence`; sensor does not call `get_heat`.

- [ ] **Step 3: Update the sensor**

Replace `src/context_service/custodian/sensors/consensus.py` with:

```python
"""Sensor for the consensus_on_chains custodian task type.

Returns candidates ranked by ``compute_consensus_priority`` (confidence gap *
heat * agent diversity), not by raw `(distinct_agents, chain_count)`. This
keeps the custodian focused on hot, contested, multi-agent chains.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.signals import compute_consensus_priority, get_heat

if TYPE_CHECKING:
    from context_service.stores.memgraph import MemgraphClient


FIND_CONSENSUS_CANDIDATES = """
MATCH (chain:ReasoningChain)-[:CRYSTALLIZED_INTO]->(target)
WHERE (target:Claim OR target:Commitment)
  AND chain.silo_id = $silo_id
  AND chain.status IN ['draft', 'published']
WITH target,
     count(DISTINCT chain) AS chain_count,
     count(DISTINCT chain.produced_by_agent_id) AS distinct_agents,
     avg(coalesce(chain.confidence, 0.5)) AS avg_chain_confidence
WHERE chain_count >= $min_chain_count
  AND distinct_agents >= $min_distinct_agents
RETURN target.id AS commitment_id,
       chain_count,
       distinct_agents,
       avg_chain_confidence
"""


async def find_consensus_candidates(
    *,
    memgraph: MemgraphClient,
    silo_id: str,
    min_chain_count: int = 2,
    min_distinct_agents: int = 2,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find commitments / claims with multi-agent chain consensus.

    Returns up to ``limit`` candidates ranked DESC by ``compute_consensus_priority``.
    Heat is fetched per-candidate via ``signals.heat.get_heat`` (Phase 1: stub
    returns 0.5; Phase 2: real Memgraph read with a batched UNWIND query — see
    the v1c plan for the migration step).
    """
    rows = await memgraph.execute_query(
        FIND_CONSENSUS_CANDIDATES,
        {
            "silo_id": silo_id,
            "min_chain_count": min_chain_count,
            "min_distinct_agents": min_distinct_agents,
        },
    )

    candidates: list[dict[str, Any]] = []
    for r in rows:
        if r["distinct_agents"] < min_distinct_agents:
            continue
        target_id = r["commitment_id"]
        heat = await get_heat(memgraph, target_id, silo_id)
        priority = compute_consensus_priority(
            avg_chain_confidence=float(r["avg_chain_confidence"]),
            avg_heat=heat,
            distinct_agent_count=int(r["distinct_agents"]),
        )
        candidates.append(
            {
                "commitment_id": target_id,
                "chain_count": int(r["chain_count"]),
                "distinct_agents": int(r["distinct_agents"]),
                "avg_chain_confidence": float(r["avg_chain_confidence"]),
                "heat": heat,
                "priority": priority,
            }
        )

    candidates.sort(key=lambda c: c["priority"], reverse=True)
    return candidates[:limit]


__all__ = ["FIND_CONSENSUS_CANDIDATES", "find_consensus_candidates"]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_consensus_priority_ordering.py -v`
Expected: all PASS.

- [ ] **Step 5: Run full check**

Run: `just check && just test`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/context_service/custodian/sensors/consensus.py tests/test_consensus_priority_ordering.py
git commit -m "feat(custodian): rank consensus candidates by priority formula"
```

---

### Task 11: Phase 1 acceptance pass

- [ ] **Step 1: Run the full quality gate**

Run: `just check && just test`
Expected: lint, typecheck, and unit tests all green.

- [ ] **Step 2: Verify acceptance criteria from spec §1.4**

Confirm by inspection / running:

  1. `signals/heat.py::get_heat` returns 0.5 and emits `heat.stub_active` once per silo:
     ```bash
     uv run pytest tests/test_signals_heat_stub.py -v
     ```
  2. Per-tool access-event emission: covered by Task 9 Step 6 manual smoke when Docker stack is up.
  3. Freshness multiplier in retrieval: pinned by `tests/test_context_query_freshness.py`.
  4. Consensus sensor priority ordering: pinned by `tests/test_consensus_priority_ordering.py`.

- [ ] **Step 3: Push the branch**

```bash
git push -u origin phase-signals-port
```

- [ ] **Step 4: Open PR titled `v1c: signals port — phase 1 (heat stub + freshness + priority + access events)`** with body referencing the spec and listing the four acceptance items above.

---

## Phase 2 — after partner talks

> Phase 2 is deferred. The tasks below assume Phase 1 has been merged and the demo arc has shipped. Re-read the spec §2.x before starting; partner-talk feedback may shift priorities.

### Task 12: Add HeatCursor index

**Files:**
- Modify: `src/context_service/db/indexes.py`

- [ ] **Step 1:** Add to the index list:

  ```python
  "CREATE INDEX ON :HeatCursor(silo_id)",
  "CREATE INDEX ON :Cluster(tier)",
  ```

- [ ] **Step 2:** Run the index applicator (or restart the service) on a dev Memgraph and verify with `SHOW INDEX INFO`.

- [ ] **Step 3:** Commit: `feat(db): heat cursor and cluster tier indexes`.

### Task 13: Implement signals.cursor

**Files:**
- Create: `src/context_service/signals/cursor.py`
- Test: `tests/test_signals_cursor.py`

- [ ] **Step 1:** Write tests for `fetch_or_init_heat_cursor` (returns `'0-0'` on first call; returns persisted `last_id` on subsequent calls) and `advance_heat_cursor` (writes `last_id` inside a single transaction).

- [ ] **Step 2:** Implement using:

  ```cypher
  MERGE (c:HeatCursor {silo_id: $silo_id})
  ON CREATE SET c.last_id = '0-0', c.created_at = $now
  RETURN c.last_id AS last_id
  ```

  and

  ```cypher
  MATCH (c:HeatCursor {silo_id: $silo_id}) SET c.last_id = $last_id
  ```

  `advance_heat_cursor(memgraph, silo_id, last_id, *, tx=None)` must accept an optional bound transaction so the asset can fold the cursor advance into the same `session.execute_write` as the heat write.

- [ ] **Step 3:** Commit: `feat(signals): heat cursor (Memgraph singleton)`.

### Task 14: Port the heat Dagster asset

**Files:**
- Create: `src/context_service/pipelines/assets/heat.py`
- Test: `tests/test_pipelines_heat_asset.py`

- [ ] **Step 1:** Copy the asset from `contextr/pipelines/assets/heat.py` and substitute:
  - Postgres cursor calls → `signals.cursor.fetch_or_init_heat_cursor` / `advance_heat_cursor` running inside `session.execute_write`.
  - `silo_partitions = dg.DynamicPartitionsDefinition(name="silo")` → reuse the existing partitions def in `pipelines/partitions.py`.
  - Resources `MemgraphResource` and `RedisResource` → existing wirings in `pipelines/resources.py`.

- [ ] **Step 2:** Keep `APPLY_HEAT_CYPHER` and `RECOMPUTE_TIERS_CYPHER` verbatim — they're already silo-scoped and use the multi-label content predicate, which matches this repo's schema.

- [ ] **Step 3:** Test by seeding access events into a Redis stream for a test silo, materialising the asset, and asserting `n.heat_score` is set on the expected nodes and `:Cluster.tier` is populated.

- [ ] **Step 4:** Commit: `feat(pipelines): hourly heat + cluster-tier asset`.

### Task 15: Schedule + concurrency key

**Files:**
- Modify: `src/context_service/pipelines/schedules.py`

- [ ] **Step 1:** Add an hourly schedule per active silo, mirroring the β2 fact-promotion pattern. Concurrency-key by silo so a slow silo doesn't block others.

- [ ] **Step 2:** Verify in `just dagster-web`: schedule shows up and ticks.

- [ ] **Step 3:** Commit: `feat(pipelines): hourly per-silo heat schedule`.

### Task 16: Flip heat stub → real Memgraph read

**Files:**
- Modify: `src/context_service/signals/heat.py`
- Modify: `src/context_service/custodian/sensors/consensus.py` (batch heat fetch)
- Test: `tests/test_signals_heat.py` (rename `test_signals_heat_stub.py` and rewrite)

- [ ] **Step 1:** Replace the body of `get_heat` with:

  ```python
  async def get_heat(memgraph: MemgraphClient, node_id: str, silo_id: str) -> float:
      rows = await memgraph.execute_query(
          "MATCH (n {id: $id, silo_id: $silo_id}) "
          "RETURN coalesce(n.heat_score, 0.5) AS h",
          {"id": str(node_id), "silo_id": silo_id},
      )
      return float(rows[0]["h"]) if rows else 0.5
  ```

  Remove `_STUB_LOG_GUARD`, `STUB_HEAT_VALUE`, and the `heat.stub_active` log.

- [ ] **Step 2:** Update `find_consensus_candidates` to batch heat:

  ```cypher
  UNWIND $ids AS id
  MATCH (n {id: id, silo_id: $silo_id})
  RETURN n.id AS id, coalesce(n.heat_score, 0.5) AS heat
  ```

  Replace the per-candidate `await get_heat(...)` loop with one batched call before the priority computation.

- [ ] **Step 3:** Tests: assert real lookup; assert fallback to 0.5 on missing `heat_score`; assert sensor regression on a fixture seeded with prior-week access events shows ordering shift versus the stub.

- [ ] **Step 4:** Commit: `feat(signals): real heat lookup (replaces phase-1 stub)`.

### Task 17: Phase 2 acceptance pass

- [ ] **Step 1:** `just check && just test && just test-integration` all green (Docker stack required for integration).

- [ ] **Step 2:** Manual: launch the heat asset on a seeded silo via `just dagster-web`; confirm `n.heat_score` and `:Cluster.tier` populate. Confirm `heat.stub_active` no longer appears in logs.

- [ ] **Step 3:** Open PR titled `v1c: signals port — phase 2 (real heat asset + cursor)`.

---

## Constants reference

| Constant | Value | Defined in |
|---|---|---|
| `STUB_HEAT_VALUE` | 0.5 | `signals/heat.py` |
| `FRESHNESS_FLOOR` | 0.25 | `signals/freshness.py` |
| `ACCESS_STREAM_MAXLEN` | 100_000 | `signals/access_events.py` |
| `freshness_weight` | 0.3 | `config/settings.py` |
| `freshness_sigma_days` | 30 | `config/settings.py` |
| `access_stream_maxlen` | 100_000 | `config/settings.py` (override of module default) |
| `HEAT_HALF_LIFE` | 7 days | Phase 2: `pipelines/assets/heat.py` (verbatim from contextr) |
| `TIER_THRESHOLDS` | HOT ≥ 0.66, WARM ≥ 0.33 | Phase 2: `pipelines/assets/heat.py` |
| `XREAD_COUNT` | 10_000 / asset run | Phase 2: `pipelines/assets/heat.py` |

---

## Self-review notes

- **Spec coverage:** Tasks 1-11 cover §1.1, §1.2, §1.3, §1.4 of the spec. Tasks 12-17 cover §2.1-§2.5. The non-goals (DR, cost tracking, dashboard, per-silo configs) remain out of scope.
- **Type consistency:** `compute_freshness(created_at, now, sigma_days)`, `get_heat(memgraph, node_id, silo_id)`, `compute_consensus_priority(avg_chain_confidence, avg_heat, distinct_agent_count)`, and `emit_access_event(redis, silo_id, node_id)` signatures are stable across phases. The Phase-2 `get_heat` keeps the Phase-1 signature so consumers don't refactor.
- **Stub guard:** `_STUB_LOG_GUARD` is process-local, not silo-local — intended. Tests reset it via fixture.
- **Freshness ordering:** the result-build block now sorts by `relevance_score` after applying the multiplier; the previous code relied on Qdrant's pre-sort, which is no longer sufficient once we mutate the score.
