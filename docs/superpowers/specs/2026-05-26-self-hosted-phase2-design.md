# Self-Hosted Distribution Phase 2 Design

**Date:** 2026-05-26
**Status:** Ready
**Depends on:** Phase 1 (complete)

## Problem

Self-hosted customers have no way to know when they're running outdated or deprecated versions. Additionally, there's no documentation for the self-hosted installation flow.

## Goals

1. Version check endpoint to inform containers of latest/minimum versions
2. Deprecation warnings in container logs for outdated versions
3. Quickstart documentation for self-hosted setup

## Non-Goals

- Automatic updates (customers control their upgrade schedule)
- Blocking startup for deprecated (but still supported) versions
- Comprehensive reference documentation (future work)

## Design

### 1. Version API Endpoint

**Endpoint:** `GET tel.engrammic.ai/versions`

```json
{
  "latest": "0.3.0",
  "minimum_supported": "0.2.0",
  "deprecation_threshold": "0.2.5"
}
```

| Field | Purpose |
|-------|---------|
| `latest` | Current release, informational |
| `minimum_supported` | Below this: ERROR, container exits |
| `deprecation_threshold` | Below this: WARNING in logs |

**Why tel.engrammic.ai:** Telemetry endpoint already exists and is called by self-hosted containers. Adding version info here avoids new infrastructure.

**Version management:** Stored in beacon config, updated when we cut releases.

### 2. Client-Side Version Check

**Location:** `src/context_service/license/version_check.py`

**Startup behavior:**

```
1. Fetch tel.engrammic.ai/versions (timeout: 5s)
2. Compare __version__ against thresholds
3. Log appropriate message and take action
```

| Condition | Log Level | Action |
|-----------|-----------|--------|
| Below `minimum_supported` | ERROR | Exit 1 |
| Below `deprecation_threshold` | WARNING | Continue, log upgrade instructions |
| Below `latest` | INFO | "Newer version available: X.Y.Z" |
| At or above `latest` | DEBUG | No message |
| Endpoint unreachable | WARNING | Continue (don't block startup) |

**Log format (deprecation):**
```
WARN  Running deprecated version 0.2.3. Upgrade to 0.3.0: docker compose pull && docker compose up -d
```

**Periodic check:** Background task runs every 24 hours, repeats the check, logs warnings if still deprecated. Uses existing Dagster scheduler or asyncio background task.

### 3. Documentation

**File:** `docs/self-hosted/quickstart.md`

**Sections:**

1. **Prerequisites**
   - Docker 20.10+
   - 4GB RAM minimum
   - License key from engrammic.ai/self-hosted

2. **Install**
   ```bash
   curl -fsSL https://get.engrammic.ai | sh
   engrammic docker
   ```

3. **Configure**
   - Edit `.env`: set `POSTGRES_PASSWORD`
   - Optional: add `LLM_API_KEY` for full SAGE features

4. **Start**
   ```bash
   cd engrammic
   docker compose up -d
   ```

5. **Verify**
   ```bash
   curl http://localhost:8000/health
   ```

6. **Diagnostics**
   - `engrammic doctor` for health checks
   - `engrammic scale` for resource monitoring

7. **Upgrading**
   ```bash
   docker compose pull
   docker compose up -d
   ```

**Length:** ~150-200 lines, single page.

### 4. File Changes

| Location | Change |
|----------|--------|
| `beacon/src/routes/versions.py` | New: `/versions` endpoint |
| `beacon/config.py` | Add version thresholds config |
| `src/context_service/license/version_check.py` | New: version check logic |
| `src/context_service/api/app.py` | Call version check on startup |
| `docs/self-hosted/quickstart.md` | New: quickstart guide |

### 5. Beacon Endpoint Implementation

```python
# beacon/src/routes/versions.py
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class VersionInfo(BaseModel):
    latest: str
    minimum_supported: str
    deprecation_threshold: str

@router.get("/versions")
async def get_versions() -> VersionInfo:
    return VersionInfo(
        latest=settings.version_latest,
        minimum_supported=settings.version_minimum,
        deprecation_threshold=settings.version_deprecated,
    )
```

### 6. Version Check Implementation

```python
# src/context_service/license/version_check.py
import httpx
from packaging.version import Version

from context_service import __version__
from context_service.config.logging import get_logger

logger = get_logger(__name__)
VERSIONS_URL = "https://tel.engrammic.ai/versions"

async def check_version() -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(VERSIONS_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("version_check_failed", error=str(e))
        return

    current = Version(__version__.replace("-dev", ""))
    minimum = Version(data["minimum_supported"])
    deprecated = Version(data["deprecation_threshold"])
    latest = Version(data["latest"])

    if current < minimum:
        logger.error(
            "unsupported_version",
            current=str(current),
            minimum=str(minimum),
            message=f"Version {current} is no longer supported. Minimum: {minimum}",
        )
        raise SystemExit(1)

    if current < deprecated:
        logger.warning(
            "deprecated_version",
            current=str(current),
            latest=str(latest),
            message=f"Running deprecated version {current}. Upgrade: docker compose pull && docker compose up -d",
        )
    elif current < latest:
        logger.info("newer_version_available", current=str(current), latest=str(latest))
```

## Success Criteria

1. Containers log deprecation warnings when running old versions
2. Containers refuse to start when below minimum supported version
3. New users can install self-hosted Engrammic using quickstart guide
4. Version check doesn't block startup if tel.engrammic.ai is unreachable
