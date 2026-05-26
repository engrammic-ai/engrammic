# Self-Hosted Distribution Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add version deprecation warnings to self-hosted containers and provide quickstart documentation.

**Architecture:** Beacon service exposes `/versions` endpoint with latest/minimum/deprecated thresholds. Context service checks on startup and logs warnings for deprecated versions. Background task repeats check every 24h.

**Tech Stack:** Python (FastAPI, httpx, packaging), structlog

**Spec:** `docs/superpowers/specs/2026-05-26-self-hosted-phase2-design.md`

---

## File Structure

### Beacon Service (tel.engrammic.ai)

```
src/beacon_service/
  config.py           # MODIFY - add version thresholds
  main.py             # MODIFY - add /versions endpoint
```

### Context Service

```
src/context_service/
  license/
    version_check.py  # NEW - version check logic
    __init__.py       # MODIFY - export check_version
  api/
    app.py            # MODIFY - call version check on startup
```

### Documentation

```
docs/self-hosted/
  quickstart.md       # NEW - installation guide
```

### Tests

```
tests/license/
  test_version_check.py  # NEW - unit tests for version check
```

---

## Task 1: Add Version Thresholds to Beacon Config

**Files:**
- Modify: `src/beacon_service/config.py`

- [ ] **Step 1: Add version fields to BeaconConfig**

```python
@dataclass(frozen=True)
class BeaconConfig:
    """Beacon service configuration from environment."""

    database_url: str
    log_level: str = "INFO"
    version_latest: str = "0.1.0"
    version_minimum: str = "0.1.0"
    version_deprecated: str = "0.1.0"

    @classmethod
    def from_env(cls) -> BeaconConfig:
        """Load configuration from environment variables."""
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is required")

        return cls(
            database_url=database_url,
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            version_latest=os.environ.get("VERSION_LATEST", "0.1.0"),
            version_minimum=os.environ.get("VERSION_MINIMUM", "0.1.0"),
            version_deprecated=os.environ.get("VERSION_DEPRECATED", "0.1.0"),
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/beacon_service/config.py
git commit -m "feat(beacon): add version threshold config"
```

---

## Task 2: Add /versions Endpoint to Beacon

**Files:**
- Modify: `src/beacon_service/main.py`

- [ ] **Step 1: Add VersionInfo model and endpoint**

Add imports at top:
```python
from pydantic import BaseModel
```

Add after the `BeaconConfig` import:
```python
class VersionInfo(BaseModel):
    """Version information for self-hosted instances."""

    latest: str
    minimum_supported: str
    deprecation_threshold: str
```

Add endpoint after the `/health` endpoint:
```python
@app.get("/versions")
async def get_versions() -> VersionInfo:
    """Return version thresholds for self-hosted instances."""
    config = BeaconConfig.from_env()
    return VersionInfo(
        latest=config.version_latest,
        minimum_supported=config.version_minimum,
        deprecation_threshold=config.version_deprecated,
    )
```

- [ ] **Step 2: Run linter**

Run: `uv run ruff check src/beacon_service/main.py --fix`
Expected: No errors or auto-fixed

- [ ] **Step 3: Commit**

```bash
git add src/beacon_service/main.py
git commit -m "feat(beacon): add /versions endpoint"
```

---

## Task 3: Create Version Check Module

**Files:**
- Create: `src/context_service/license/version_check.py`
- Create: `tests/license/test_version_check.py`

- [ ] **Step 1: Write failing test for version check**

```python
# tests/license/test_version_check.py
"""Tests for version check functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from context_service.license.version_check import check_version, VersionCheckResult


@pytest.fixture
def mock_httpx_response():
    """Factory for mock httpx responses."""
    def _make_response(data: dict, status_code: int = 200):
        mock = AsyncMock()
        mock.status_code = status_code
        mock.json.return_value = data
        mock.raise_for_status = AsyncMock()
        if status_code >= 400:
            mock.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        return mock
    return _make_response


@pytest.mark.asyncio
async def test_check_version_current_is_latest(mock_httpx_response):
    """No warning when running latest version."""
    response = mock_httpx_response({
        "latest": "0.1.0",
        "minimum_supported": "0.1.0",
        "deprecation_threshold": "0.1.0",
    })

    with patch("context_service.license.version_check.__version__", "0.1.0"):
        with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            result = await check_version()

    assert result == VersionCheckResult.UP_TO_DATE


@pytest.mark.asyncio
async def test_check_version_newer_available(mock_httpx_response):
    """Info logged when newer version available."""
    response = mock_httpx_response({
        "latest": "0.2.0",
        "minimum_supported": "0.1.0",
        "deprecation_threshold": "0.1.0",
    })

    with patch("context_service.license.version_check.__version__", "0.1.0"):
        with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            result = await check_version()

    assert result == VersionCheckResult.UPDATE_AVAILABLE


@pytest.mark.asyncio
async def test_check_version_deprecated(mock_httpx_response):
    """Warning logged when running deprecated version."""
    response = mock_httpx_response({
        "latest": "0.3.0",
        "minimum_supported": "0.1.0",
        "deprecation_threshold": "0.2.0",
    })

    with patch("context_service.license.version_check.__version__", "0.1.5"):
        with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            result = await check_version()

    assert result == VersionCheckResult.DEPRECATED


@pytest.mark.asyncio
async def test_check_version_unsupported(mock_httpx_response):
    """Error raised when below minimum supported."""
    response = mock_httpx_response({
        "latest": "0.3.0",
        "minimum_supported": "0.2.0",
        "deprecation_threshold": "0.2.5",
    })

    with patch("context_service.license.version_check.__version__", "0.1.0"):
        with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            with pytest.raises(SystemExit) as exc_info:
                await check_version()

    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_check_version_network_failure():
    """Graceful degradation when endpoint unreachable."""
    with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception("Connection refused")
        )
        result = await check_version()

    assert result == VersionCheckResult.CHECK_FAILED


@pytest.mark.asyncio
async def test_check_version_strips_dev_suffix(mock_httpx_response):
    """Dev suffix is stripped before comparison."""
    response = mock_httpx_response({
        "latest": "0.1.0",
        "minimum_supported": "0.1.0",
        "deprecation_threshold": "0.1.0",
    })

    with patch("context_service.license.version_check.__version__", "0.1.0-dev"):
        with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            result = await check_version()

    assert result == VersionCheckResult.UP_TO_DATE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/license/test_version_check.py -v`
Expected: FAIL with ModuleNotFoundError or ImportError

- [ ] **Step 3: Write version_check.py implementation**

```python
# src/context_service/license/version_check.py
"""Version check against telemetry endpoint."""

from __future__ import annotations

from enum import Enum

import httpx
from packaging.version import Version

from context_service import __version__
from context_service.config.logging import get_logger
from context_service.config.settings import get_settings

logger = get_logger(__name__)


class VersionCheckResult(Enum):
    """Result of version check."""

    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    DEPRECATED = "deprecated"
    UNSUPPORTED = "unsupported"
    CHECK_FAILED = "check_failed"


def _get_versions_url() -> str:
    """Get versions endpoint URL from settings."""
    settings = get_settings()
    base_url = settings.telemetry.beacon_url.rstrip("/beacon").rstrip("/v1")
    return f"{base_url}/versions"


async def check_version() -> VersionCheckResult:
    """Check current version against telemetry endpoint.

    Returns:
        VersionCheckResult indicating version status.

    Raises:
        SystemExit: If version is below minimum supported.
    """
    versions_url = _get_versions_url()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(versions_url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("version_check_failed", error=str(e), url=versions_url)
        return VersionCheckResult.CHECK_FAILED

    current = Version(__version__.replace("-dev", ""))
    minimum = Version(data["minimum_supported"])
    deprecated = Version(data["deprecation_threshold"])
    latest = Version(data["latest"])

    if current < minimum:
        logger.error(
            "unsupported_version",
            current=str(current),
            minimum=str(minimum),
            message=f"Version {current} is no longer supported. Minimum required: {minimum}",
        )
        raise SystemExit(1)

    if current < deprecated:
        logger.warning(
            "deprecated_version",
            current=str(current),
            latest=str(latest),
            message=f"Running deprecated version {current}. Upgrade to {latest}: docker compose pull && docker compose up -d",
        )
        return VersionCheckResult.DEPRECATED

    if current < latest:
        logger.info(
            "newer_version_available",
            current=str(current),
            latest=str(latest),
        )
        return VersionCheckResult.UPDATE_AVAILABLE

    return VersionCheckResult.UP_TO_DATE
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/license/test_version_check.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check src/context_service/license/version_check.py --fix && uv run mypy src/context_service/license/version_check.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/context_service/license/version_check.py tests/license/test_version_check.py
git commit -m "feat(license): add version check against telemetry endpoint"
```

---

## Task 4: Export check_version from License Module

**Files:**
- Modify: `src/context_service/license/__init__.py`

- [ ] **Step 1: Read current __init__.py**

Check existing exports to understand the pattern.

- [ ] **Step 2: Add version_check exports**

Add to the imports:
```python
from context_service.license.version_check import VersionCheckResult, check_version
```

Add to `__all__` if it exists, or ensure the imports are at module level.

- [ ] **Step 3: Commit**

```bash
git add src/context_service/license/__init__.py
git commit -m "feat(license): export version check functions"
```

---

## Task 5: Wire Version Check into App Startup

**Files:**
- Modify: `src/context_service/api/app.py`

- [ ] **Step 1: Add version check to lifespan**

Add import at top with other license imports:
```python
from context_service.license.version_check import check_version
```

Add after the license check block (around line 48-54), inside the lifespan function. Note: use the existing `settings` variable from line 44, don't call `get_settings()` again:
```python
    # Version deprecation check (non-blocking on failure)
    if settings.telemetry.enabled:
        try:
            await check_version()
        except SystemExit:
            raise
        except Exception as e:
            logger.warning("version_check_startup_failed", error=str(e))
```

- [ ] **Step 2: Run type checker**

Run: `uv run mypy src/context_service/api/app.py`
Expected: No new errors

- [ ] **Step 3: Commit**

```bash
git add src/context_service/api/app.py
git commit -m "feat(api): check version on startup"
```

---

## Task 6: Add Periodic Version Check Background Task

**Files:**
- Modify: `src/context_service/api/app.py`

- [ ] **Step 1: Create background task function**

Add after `logger = get_logger(__name__)` (around line 38), before the `lifespan` function:
```python
async def _periodic_version_check(interval_hours: int = 24) -> None:
    """Background task to periodically check version."""
    from context_service.license.version_check import check_version

    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            await check_version()
        except SystemExit:
            pass  # Don't exit from background task, just log
        except Exception as e:
            logger.warning("periodic_version_check_failed", error=str(e))
```

- [ ] **Step 2: Start background task in lifespan**

Add immediately after the version check block from Task 5 (uses existing `settings` variable):
```python
        # Start periodic version check (every 24h)
        asyncio.create_task(_periodic_version_check())
```

Note: This goes inside the `if settings.telemetry.enabled:` block, so no need to check again.

- [ ] **Step 3: Run linter**

Run: `uv run ruff check src/context_service/api/app.py --fix`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/context_service/api/app.py
git commit -m "feat(api): add periodic version check background task"
```

---

## Task 7: Write Quickstart Documentation

**Files:**
- Create: `docs/self-hosted/quickstart.md`

- [ ] **Step 1: Write quickstart guide**

```markdown
# Self-Hosted Quickstart

Get Engrammic running on your own infrastructure in under 10 minutes.

## Prerequisites

- Docker 20.10+ with Compose v2
- 4GB RAM minimum (8GB recommended for production)
- License key from [engrammic.ai/self-hosted](https://engrammic.ai/self-hosted)

## Install

Download and run the installer:

```bash
curl -fsSL https://get.engrammic.ai | sh
```

Then run the Docker setup:

```bash
engrammic docker
```

The installer will:
1. Validate your license key
2. Create an `engrammic/` directory with `docker-compose.yml` and `.env`

## Configure

Edit `engrammic/.env`:

```bash
# Required: set a strong password
POSTGRES_PASSWORD=your-secure-password-here

# Optional: enable full SAGE features (synthesis, deduplication)
# LLM_PROVIDER=openai
# LLM_API_KEY=sk-...
```

Without LLM keys, Engrammic runs in passive mode: memory storage and recall work, but automatic synthesis is disabled.

## Start

```bash
cd engrammic
docker compose up -d
```

Wait for all services to become healthy (about 30 seconds):

```bash
docker compose ps
```

All services should show `healthy` status.

## Verify

Check the health endpoint:

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "services": {
    "memgraph": "connected",
    "redis": "connected",
    "qdrant": "connected",
    "postgres": "connected"
  },
  "sage_mode": "passive",
  "license": {
    "valid": true,
    "customer": "your-org",
    "days_remaining": 87
  }
}
```

## Configure Your Editor

### Claude Code

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "engrammic": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "engrammic": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## Diagnostics

If something goes wrong:

```bash
# Check container health and resource usage
engrammic doctor

# Monitor memory usage
engrammic scale
```

## Upgrading

Pull the latest images and restart:

```bash
cd engrammic
docker compose pull
docker compose up -d
```

Deprecation warnings appear in logs when running old versions.

## Telemetry

By default, anonymous usage metrics are sent to help improve Engrammic. No content or user data is collected.

To disable:

```bash
# In engrammic/.env
TELEMETRY_ENABLED=false
```

See [telemetry.md](telemetry.md) for details on what's collected.

## Next Steps

- [Telemetry configuration](telemetry.md)
- [MCP tools reference](https://docs.engrammic.ai/mcp-tools)
```

- [ ] **Step 2: Commit**

```bash
git add docs/self-hosted/quickstart.md
git commit -m "docs: add self-hosted quickstart guide"
```

---

## Task 8: Update docs/self-hosted README

**Files:**
- Create: `docs/self-hosted/README.md`

- [ ] **Step 1: Create index README**

```markdown
# Self-Hosted Documentation

Guides for running Engrammic on your own infrastructure.

## Guides

- [Quickstart](quickstart.md) - Install and configure in under 10 minutes
- [Telemetry](telemetry.md) - What's collected and how to configure it
```

- [ ] **Step 2: Commit**

```bash
git add docs/self-hosted/README.md
git commit -m "docs: add self-hosted docs index"
```

---

## Final Verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/license/ -v`
Expected: All tests pass

- [ ] **Step 2: Run type checker on modified files**

Run: `uv run mypy src/context_service/license/ src/context_service/api/app.py src/beacon_service/`
Expected: No errors

- [ ] **Step 3: Run linter on all modified files**

Run: `uv run ruff check src/context_service/license/ src/context_service/api/app.py src/beacon_service/ --fix`
Expected: No errors
