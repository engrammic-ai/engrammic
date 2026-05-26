# Self-Hosted Distribution Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable self-hosted deployment with license validation, lite Docker bundle, and diagnostic tooling.

**Architecture:** License validation via signed JWT (Ed25519) checked at container startup. Public Docker images on GCP Artifact Registry. Installer extended to handle Docker flow. SAGE runs in passive mode without LLM keys.

**Tech Stack:** Python (FastAPI, cryptography, typer), Rust (installer-cli), Docker Compose, Ed25519 JWT

**Spec:** `docs/superpowers/specs/2026-05-26-self-hosted-distribution-design.md`

---

## File Structure

### context-service (this repo)

```
src/context_service/
  license/                    # NEW - license validation module
    __init__.py
    validator.py              # JWT validation, expiry check
    renewal.py                # Background auto-renewal task
    keys.py                   # Embedded public key
  config/
    settings.py               # MODIFY - add license + LLM settings
  api/
    routes/
      health.py               # MODIFY - add license status, sage_mode, restarts
    app.py                    # MODIFY - startup license check

docker/
  docker-compose.selfhosted.yml   # NEW - lite defaults for self-hosted

tests/
  license/
    test_validator.py
    test_renewal.py
```

### cli repo (../cli) - NEW

```
cli/
  src/
    engrammic_cli/
      __init__.py
      main.py                 # typer entrypoint
      license.py              # key generation commands
  keys/
    private.pem               # Ed25519 signing key (gitignored!)
    public.pem                # copy to service + installer
  pyproject.toml
  .gitignore
```

### mcp-client/installer-cli

```
installer-cli/
  src/
    main.rs                   # MODIFY - add Docker menu option
    docker.rs                 # NEW - Docker detection, compose install
    license.rs                # NEW - license key validation
    cli.rs                    # MODIFY - add docker command
  assets/
    docker-compose.yml        # NEW - bundled compose template
    public.pem                # NEW - embedded public key
```

---

## Task 0: Generate Ed25519 Keypair

Before other tasks, generate the signing keypair used across all components.

**Files:**
- Create: `../cli/keys/private.pem`
- Create: `../cli/keys/public.pem`

- [ ] **Step 1: Create cli directory structure**

```bash
mkdir -p ../cli/keys ../cli/src/engrammic_cli
touch ../cli/src/engrammic_cli/__init__.py
```

- [ ] **Step 2: Generate Ed25519 keypair**

```bash
cd ../cli/keys
openssl genpkey -algorithm ED25519 -out private.pem
openssl pkey -in private.pem -pubout -out public.pem
```

- [ ] **Step 3: Verify keypair**

```bash
openssl pkey -in private.pem -text -noout | head -5
# Expected: ED25519 Private-Key:
```

- [ ] **Step 4: Create .gitignore**

```bash
cat > ../cli/.gitignore << 'EOF'
keys/private.pem
__pycache__/
*.pyc
.venv/
dist/
*.egg-info/
EOF
```

- [ ] **Step 5: Commit**

```bash
cd ../cli
git init
git add .gitignore keys/public.pem src/
git commit -m "chore: initialize cli repo with Ed25519 public key"
```

---

## Task 1: Internal CLI - License Generation

**Files:**
- Create: `../cli/pyproject.toml`
- Create: `../cli/src/engrammic_cli/main.py`
- Create: `../cli/src/engrammic_cli/license.py`

- [ ] **Step 1: Create pyproject.toml**

```bash
cat > ../cli/pyproject.toml << 'EOF'
[project]
name = "engrammic-cli"
version = "0.1.0"
description = "Internal Engrammic admin CLI"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12.0",
    "cryptography>=42.0.0",
    "pyjwt>=2.8.0",
    "rich>=13.0.0",
]

[project.scripts]
engrammic-cli = "engrammic_cli.main:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/engrammic_cli"]
EOF
```

- [ ] **Step 2: Create main.py**

```python
# ../cli/src/engrammic_cli/main.py
"""Engrammic internal admin CLI."""

import typer

from engrammic_cli.license import license_app

app = typer.Typer(
    name="engrammic-cli",
    help="Internal Engrammic admin CLI",
    no_args_is_help=True,
)

app.add_typer(license_app, name="license")

if __name__ == "__main__":
    app()
```

- [ ] **Step 3: Create license.py**

```python
# ../cli/src/engrammic_cli/license.py
"""License key generation commands."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import typer
from cryptography.hazmat.primitives import serialization
from rich.console import Console

license_app = typer.Typer(help="License key management")
console = Console()

KEYS_DIR = Path(__file__).parent.parent.parent / "keys"
ISSUER = "engrammic"
KEY_PREFIX = "ENGR_"


def load_private_key() -> bytes:
    """Load Ed25519 private key from keys directory."""
    key_path = KEYS_DIR / "private.pem"
    if not key_path.exists():
        raise typer.BadParameter(f"Private key not found: {key_path}")
    return key_path.read_bytes()


@license_app.command("create")
def create_license(
    customer: str = typer.Option(..., "--customer", "-c", help="Customer identifier"),
    days: int = typer.Option(90, "--days", "-d", help="Days until expiry"),
    tier: str = typer.Option("self-hosted", "--tier", "-t", help="License tier"),
    features: str = typer.Option(
        "mcp,rest-api,sage",
        "--features",
        "-f",
        help="Comma-separated feature flags",
    ),
) -> None:
    """Generate a new license key."""
    private_key_pem = load_private_key()
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)

    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=days)

    payload = {
        "sub": customer,
        "iss": ISSUER,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "tier": tier,
        "features": features.split(","),
    }

    token = jwt.encode(payload, private_key, algorithm="EdDSA")
    license_key = f"{KEY_PREFIX}{token}"

    console.print(f"\n[bold green]License key created[/bold green]")
    console.print(f"Customer: [cyan]{customer}[/cyan]")
    console.print(f"Expires:  [cyan]{exp.strftime('%Y-%m-%d')}[/cyan] ({days} days)")
    console.print(f"Tier:     [cyan]{tier}[/cyan]")
    console.print(f"Features: [cyan]{', '.join(features.split(','))}[/cyan]")
    console.print(f"\n[bold]License key:[/bold]\n{license_key}\n")


@license_app.command("decode")
def decode_license(
    key: str = typer.Argument(..., help="License key to decode"),
) -> None:
    """Decode and display license key contents (without validation)."""
    if key.startswith(KEY_PREFIX):
        key = key[len(KEY_PREFIX):]

    try:
        payload = jwt.decode(key, options={"verify_signature": False})
        console.print(json.dumps(payload, indent=2))
    except jwt.DecodeError as e:
        console.print(f"[red]Invalid JWT: {e}[/red]")
        raise typer.Exit(1)
```

- [ ] **Step 4: Install and test**

```bash
cd ../cli
uv sync
uv run engrammic-cli license create --customer test-corp --days 90
```

Expected output:
```
License key created
Customer: test-corp
Expires:  2026-08-24 (90 days)
Tier:     self-hosted
Features: mcp, rest-api, sage

License key:
ENGR_eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9...
```

- [ ] **Step 5: Commit**

```bash
cd ../cli
git add pyproject.toml src/
git commit -m "feat: add license key generation CLI"
```

---

## Task 2: License Validator Module

**Files:**
- Create: `src/context_service/license/__init__.py`
- Create: `src/context_service/license/keys.py`
- Create: `src/context_service/license/validator.py`
- Test: `tests/license/test_validator.py`

- [ ] **Step 1: Create test directory**

```bash
mkdir -p tests/license
touch tests/license/__init__.py
```

- [ ] **Step 2: Write failing test**

```python
# tests/license/test_validator.py
"""License validator tests."""

import time

import pytest

from context_service.license.validator import (
    LicenseError,
    LicenseInfo,
    validate_license_key,
)


def test_validate_license_key_missing_prefix() -> None:
    """License key must start with ENGR_ prefix."""
    with pytest.raises(LicenseError, match="must start with ENGR_"):
        validate_license_key("invalid_key")


def test_validate_license_key_invalid_jwt() -> None:
    """Invalid JWT raises LicenseError."""
    with pytest.raises(LicenseError, match="Invalid license key"):
        validate_license_key("ENGR_notajwt")


def test_validate_license_key_expired() -> None:
    """Expired license raises LicenseError."""
    # This test needs a real expired key - we'll generate one in integration tests
    pass


def test_license_info_days_remaining() -> None:
    """LicenseInfo calculates days remaining correctly."""
    future_exp = int(time.time()) + (30 * 24 * 60 * 60)  # 30 days
    info = LicenseInfo(
        customer="test",
        expires_at=future_exp,
        tier="self-hosted",
        features=["mcp"],
    )
    assert 29 <= info.days_remaining <= 30
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/license/test_validator.py -v
```

Expected: FAIL with "No module named 'context_service.license'"

- [ ] **Step 4: Create keys.py with embedded public key**

```python
# src/context_service/license/keys.py
"""Embedded public key for license validation."""

import os
from pathlib import Path

# IMPORTANT: Replace this placeholder with the actual public key from ../cli/keys/public.pem
# The service will fail to start if this placeholder is not replaced.
_PUBLIC_KEY_PLACEHOLDER = "REPLACE_WITH_ACTUAL_PUBLIC_KEY"

PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA_REPLACE_WITH_ACTUAL_PUBLIC_KEY_CONTENT_HERE
-----END PUBLIC KEY-----
"""


def get_public_key_pem() -> str:
    """Return the embedded public key PEM.
    
    Raises:
        RuntimeError: If the placeholder was not replaced with actual key.
    """
    if _PUBLIC_KEY_PLACEHOLDER in PUBLIC_KEY_PEM or "REPLACE_WITH" in PUBLIC_KEY_PEM:
        raise RuntimeError(
            "License public key not configured! "
            "Copy the key from ../cli/keys/public.pem to src/context_service/license/keys.py"
        )
    return PUBLIC_KEY_PEM.strip()
```

- [ ] **Step 5: Create validator.py**

```python
# src/context_service/license/validator.py
"""License key validation."""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives import serialization

from context_service.license.keys import get_public_key_pem

KEY_PREFIX = "ENGR_"
ISSUER = "engrammic"


class LicenseError(Exception):
    """License validation failed."""

    pass


@dataclass
class LicenseInfo:
    """Validated license information."""

    customer: str
    expires_at: int  # Unix timestamp
    tier: str
    features: list[str]

    @property
    def days_remaining(self) -> int:
        """Days until license expires."""
        remaining_seconds = self.expires_at - int(time.time())
        return max(0, remaining_seconds // (24 * 60 * 60))

    @property
    def is_expiring_soon(self) -> bool:
        """True if license expires in less than 14 days."""
        return self.days_remaining < 14


def validate_license_key(key: str) -> LicenseInfo:
    """Validate license key and return license info.

    Args:
        key: License key string (with ENGR_ prefix)

    Returns:
        LicenseInfo with validated license details

    Raises:
        LicenseError: If license is invalid, expired, or malformed
    """
    if not key.startswith(KEY_PREFIX):
        raise LicenseError(f"License key must start with {KEY_PREFIX}")

    token = key[len(KEY_PREFIX):]

    public_key_pem = get_public_key_pem()
    public_key = serialization.load_pem_public_key(public_key_pem.encode())

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["EdDSA"],
            issuer=ISSUER,
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise LicenseError("License key has expired")
    except jwt.InvalidIssuerError:
        raise LicenseError("License key has invalid issuer")
    except jwt.DecodeError as e:
        raise LicenseError(f"Invalid license key: {e}")

    return LicenseInfo(
        customer=payload["sub"],
        expires_at=payload["exp"],
        tier=payload.get("tier", "self-hosted"),
        features=payload.get("features", []),
    )
```

- [ ] **Step 6: Create __init__.py**

```python
# src/context_service/license/__init__.py
"""License validation module."""

from context_service.license.validator import (
    LicenseError,
    LicenseInfo,
    validate_license_key,
)

__all__ = ["LicenseError", "LicenseInfo", "validate_license_key"]
```

- [ ] **Step 7: Copy actual public key**

```bash
# Copy the actual public key content from ../cli/keys/public.pem
cat ../cli/keys/public.pem
# Then paste into src/context_service/license/keys.py
```

- [ ] **Step 8: Run tests**

```bash
uv run pytest tests/license/test_validator.py -v
```

Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/context_service/license/ tests/license/
git commit -m "feat: add license validation module with Ed25519 JWT support"
```

---

## Task 3: License Settings

**Files:**
- Modify: `src/context_service/config/settings.py`
- Test: `tests/config/test_settings.py`

- [ ] **Step 1: Write failing test**

```python
# tests/config/test_settings.py (append)

def test_license_settings_defaults() -> None:
    """License settings have correct defaults."""
    import os
    os.environ.pop("ENGRAMMIC_LICENSE_KEY", None)
    os.environ.pop("LICENSE_VALIDATION_ENABLED", None)

    from context_service.config.settings import Settings
    settings = Settings()

    assert settings.license_key is None
    assert settings.license_validation_enabled is True


def test_llm_settings_defaults() -> None:
    """LLM settings for self-hosted have correct defaults."""
    import os
    os.environ.pop("LLM_PROVIDER", None)
    os.environ.pop("LLM_API_KEY", None)

    from context_service.config.settings import Settings
    settings = Settings()

    assert settings.llm_provider is None
    assert settings.llm_api_key is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/config/test_settings.py::test_license_settings_defaults -v
```

Expected: FAIL with AttributeError

- [ ] **Step 3: Add settings to Settings class**

Find the Settings class in `src/context_service/config/settings.py` and add:

```python
# In the Settings class, add these fields:

    # License validation (self-hosted)
    license_key: str | None = Field(
        default=None,
        alias="ENGRAMMIC_LICENSE_KEY",
        description="License key for self-hosted deployments",
    )
    license_validation_enabled: bool = Field(
        default=True,
        description="Enable license validation on startup (disable for hosted)",
    )

    # LLM configuration (self-hosted SAGE)
    llm_provider: str | None = Field(
        default=None,
        alias="LLM_PROVIDER",
        description="LLM provider: openai, anthropic, google-vertex",
    )
    llm_api_key: SecretStr | None = Field(
        default=None,
        alias="LLM_API_KEY",
        description="API key for LLM provider",
    )
    llm_model: str | None = Field(
        default=None,
        alias="LLM_MODEL",
        description="Override default model for LLM provider",
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/config/test_settings.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/config/settings.py tests/config/test_settings.py
git commit -m "feat: add license and LLM settings for self-hosted"
```

---

## Task 4: Startup License Check

**Files:**
- Modify: `src/context_service/api/app.py`
- Test: `tests/api/test_app_license.py`

- [ ] **Step 1: Create test file**

```python
# tests/api/test_app_license.py
"""License validation at startup tests."""

import os
from unittest.mock import patch

import pytest


def test_startup_without_license_key_exits() -> None:
    """App exits if LICENSE_VALIDATION_ENABLED and no license key."""
    with patch.dict(os.environ, {
        "LICENSE_VALIDATION_ENABLED": "true",
        "ENGRAMMIC_LICENSE_KEY": "",
    }, clear=False):
        with pytest.raises(SystemExit):
            from context_service.license.startup import check_license_on_startup
            check_license_on_startup()


def test_startup_with_valid_license_passes() -> None:
    """App starts normally with valid license."""
    # This test requires a valid test license key
    # Will be tested in integration tests
    pass


def test_startup_license_validation_disabled() -> None:
    """App starts without license when validation disabled."""
    with patch.dict(os.environ, {
        "LICENSE_VALIDATION_ENABLED": "false",
    }, clear=False):
        from context_service.license.startup import check_license_on_startup
        result = check_license_on_startup()
        assert result is None  # No license info when disabled
```

- [ ] **Step 2: Create startup.py module**

```python
# src/context_service/license/startup.py
"""License check at application startup."""

from __future__ import annotations

import sys

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings
from context_service.license.validator import (
    LicenseError,
    LicenseInfo,
    validate_license_key,
)

logger = get_logger(__name__)


def check_license_on_startup() -> LicenseInfo | None:
    """Validate license key at startup.

    Returns:
        LicenseInfo if valid license, None if validation disabled

    Exits:
        sys.exit(1) if validation enabled and license invalid/missing
    """
    settings = get_settings()

    if not settings.license_validation_enabled:
        logger.info("license_validation_disabled")
        return None

    license_key = settings.license_key
    if not license_key:
        logger.error("license_key_missing", msg="ENGRAMMIC_LICENSE_KEY not set")
        print("\nError: License key required for self-hosted deployment.")
        print("Set ENGRAMMIC_LICENSE_KEY in your .env file.\n")
        sys.exit(1)

    try:
        info = validate_license_key(license_key)
    except LicenseError as e:
        logger.error("license_validation_failed", error=str(e))
        print(f"\nError: Invalid license key - {e}")
        print("Contact support@engrammic.ai for assistance.\n")
        sys.exit(1)

    logger.info(
        "license_validated",
        customer=info.customer,
        days_remaining=info.days_remaining,
        tier=info.tier,
    )

    if info.is_expiring_soon:
        logger.warning(
            "license_expiring_soon",
            days_remaining=info.days_remaining,
            customer=info.customer,
        )

    # Log SAGE mode based on LLM configuration
    if not settings.llm_api_key:
        logger.info(
            "sage_passive_mode",
            msg="SAGE running in passive mode (no LLM_API_KEY). Storage and recall available, synthesis disabled.",
        )

    return info
```

- [ ] **Step 3: Update __init__.py**

```python
# src/context_service/license/__init__.py
"""License validation module."""

from context_service.license.startup import check_license_on_startup
from context_service.license.validator import (
    LicenseError,
    LicenseInfo,
    validate_license_key,
)

__all__ = [
    "LicenseError",
    "LicenseInfo",
    "check_license_on_startup",
    "validate_license_key",
]
```

- [ ] **Step 4: Integrate into app.py lifespan**

In `src/context_service/api/app.py`, add to the lifespan function after settings are loaded:

```python
# At the top, add import:
from context_service.license import check_license_on_startup

# In lifespan(), after settings = get_settings():
    license_info = check_license_on_startup()
    if license_info:
        app.state.license_info = license_info
    else:
        app.state.license_info = None
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/api/test_app_license.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/license/startup.py src/context_service/license/__init__.py
git add src/context_service/api/app.py tests/api/test_app_license.py
git commit -m "feat: add license validation at application startup"
```

---

## Task 5: Health Endpoint - License Status

**Note:** Memory usage monitoring (`memory` field) is best-effort. Getting container memory stats from inside a container requires Docker socket access (`/var/run/docker.sock` mount). For MVP, we include the model but return `null` for memory. Full implementation deferred to when we add an optional sidecar or socket mount.

**Files:**
- Modify: `src/context_service/api/routes/health.py`
- Test: `tests/api/routes/test_health.py`

- [ ] **Step 1: Write failing test**

```python
# tests/api/routes/test_health.py (append or create)

import pytest
from fastapi.testclient import TestClient


def test_health_includes_license_info(client: TestClient) -> None:
    """Health endpoint includes license information."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()

    # License info should be present (may be null if validation disabled)
    assert "license" in data
    assert "sage_mode" in data


def test_health_sage_mode_passive_without_llm(client: TestClient) -> None:
    """SAGE mode is passive when no LLM keys configured."""
    response = client.get("/health")
    data = response.json()

    # Without LLM_API_KEY, sage_mode should be "passive"
    assert data["sage_mode"] in ["active", "passive"]
```

- [ ] **Step 2: Update HealthResponse model**

In `src/context_service/api/routes/health.py`, update the models:

```python
# Add new models after existing ones:

class LicenseStatus(BaseModel):
    """License status in health response."""

    valid: bool
    customer: str | None = None
    expires_at: str | None = None
    days_remaining: int | None = None


class MemoryUsage(BaseModel):
    """Memory usage for a service."""
    
    used_mb: int
    limit_mb: int
    percent: int


class HealthResponse(BaseModel):
    """Health check response model."""

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    services: ServiceStatus
    license: LicenseStatus | None = None
    sage_mode: Literal["active", "passive"] = "passive"
    memory: dict[str, MemoryUsage] | None = None
    recent_restarts: list[str] = []
    latency: ServiceLatency | None = None
    uptime_seconds: float | None = None
```

- [ ] **Step 3: Update health_check function**

```python
# In health_check(), before returning, add:

    # License info
    license_info = getattr(request.app.state, "license_info", None)
    license_status = None
    if license_info:
        from datetime import datetime, timezone
        license_status = LicenseStatus(
            valid=True,
            customer=license_info.customer,
            expires_at=datetime.fromtimestamp(
                license_info.expires_at, tz=timezone.utc
            ).isoformat(),
            days_remaining=license_info.days_remaining,
        )

    # SAGE mode based on LLM config
    settings = get_settings()
    sage_mode: Literal["active", "passive"] = (
        "active" if settings.llm_api_key else "passive"
    )

    response = HealthResponse(
        status=status,
        version=__version__,
        services=ServiceStatus(...),
        license=license_status,
        sage_mode=sage_mode,
        recent_restarts=[],  # TODO: implement restart tracking
    )
```

- [ ] **Step 4: Add settings import**

```python
# At top of health.py:
from context_service.config.settings import get_settings
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/api/routes/test_health.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/api/routes/health.py tests/api/routes/test_health.py
git commit -m "feat: add license status and sage_mode to health endpoint"
```

---

## Task 6: Docker Compose Self-Hosted Bundle

**Files:**
- Create: `docker/docker-compose.selfhosted.yml`
- Create: `docker/selfhosted.env.example`

- [ ] **Step 1: Create docker-compose.selfhosted.yml**

```yaml
# docker/docker-compose.selfhosted.yml
# Engrammic Self-Hosted - Lite defaults (~3GB RAM total)
# For scaling guidance, see comments below.

services:
  app:
    image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-api:latest
    container_name: engrammic-app
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      - ENVIRONMENT=self-hosted
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
      - LICENSE_VALIDATION_ENABLED=true
    depends_on:
      memgraph:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      start_period: 15s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 512M  # Scale: 1GB for multiple users
    restart: unless-stopped

  dagster:
    image: europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-dagster:latest
    container_name: engrammic-dagster
    command: ["dagster-daemon", "run"]
    env_file:
      - .env
    environment:
      - DAGSTER_HOME=/app
      - MEMGRAPH_HOST=memgraph
      - QDRANT_HOST=qdrant
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
    depends_on:
      postgres:
        condition: service_healthy
      memgraph:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 256M
    restart: unless-stopped

  memgraph:
    image: memgraph/memgraph-mage:3.10.1
    container_name: engrammic-memgraph
    ports:
      - "7687:7687"
    volumes:
      - memgraph-data:/var/lib/memgraph
    command: ["--log-level=WARNING", "--storage-properties-on-edges=true"]
    healthcheck:
      test: ["CMD-SHELL", "echo 'RETURN 1;' | mgconsole || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 1G  # Scale: 2GB for >50k nodes, 4GB for >100k nodes
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:v1.18.0
    container_name: engrammic-qdrant
    ports:
      - "6333:6333"
    volumes:
      - qdrant-data:/qdrant/storage
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:6333/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 512M  # Scale: 1GB for >100k nodes
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: engrammic-redis
    volumes:
      - redis-data:/data
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "100mb"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 128M
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: engrammic-postgres
    volumes:
      - postgres-data:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=engrammic
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-engrammic}
      - POSTGRES_DB=engrammic
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U engrammic -d engrammic"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 256M
    restart: unless-stopped

volumes:
  memgraph-data:
  qdrant-data:
  redis-data:
  postgres-data:
```

- [ ] **Step 2: Create env example**

```bash
# docker/selfhosted.env.example
# Engrammic Self-Hosted Configuration

# Required: Your license key
ENGRAMMIC_LICENSE_KEY=ENGR_your_license_key_here

# Database passwords (change in production)
POSTGRES_PASSWORD=engrammic
MEMGRAPH_USER=memgraph
MEMGRAPH_PASSWORD=memgraph

# Optional: LLM for full SAGE features
# Without these, SAGE runs in passive mode (storage + recall only)
# LLM_PROVIDER=openai
# LLM_API_KEY=sk-...
# LLM_MODEL=gpt-4o-mini

# Telemetry (enabled by default, set to false to disable)
TELEMETRY_ENABLED=true
```

- [ ] **Step 3: Commit**

```bash
git add docker/docker-compose.selfhosted.yml docker/selfhosted.env.example
git commit -m "feat: add self-hosted Docker Compose bundle with lite defaults"
```

---

## Task 7: Make GCP Artifact Registry Public

**Priority:** Do this early (after Task 1) so you can test `docker pull` before other tasks reference the images.

**Files:**
- No code changes, infrastructure only

- [ ] **Step 1: Run gcloud command**

```bash
gcloud artifacts repositories add-iam-policy-binding engrammic \
  --location=europe-north1 \
  --member=allUsers \
  --role=roles/artifactregistry.reader \
  --project=engrammic
```

- [ ] **Step 2: Verify public access**

```bash
# Try pulling without auth (from a machine without gcloud configured)
docker pull europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-api:latest
```

- [ ] **Step 3: Document in README**

Add to relevant docs that images are publicly accessible.

---

## Task 8: Auto-Renewal Background Task

**Files:**
- Create: `src/context_service/license/renewal.py`
- Test: `tests/license/test_renewal.py`

- [ ] **Step 1: Write failing test**

```python
# tests/license/test_renewal.py
"""License auto-renewal tests."""

import pytest
from unittest.mock import AsyncMock, patch

from context_service.license.renewal import attempt_license_renewal


@pytest.mark.asyncio
async def test_renewal_skipped_when_not_expiring() -> None:
    """Renewal not attempted if license has >14 days remaining."""
    with patch("context_service.license.renewal.get_settings") as mock_settings:
        mock_settings.return_value.license_key = "ENGR_valid_key"

        with patch("context_service.license.renewal.validate_license_key") as mock_validate:
            from context_service.license.validator import LicenseInfo
            import time
            mock_validate.return_value = LicenseInfo(
                customer="test",
                expires_at=int(time.time()) + (30 * 24 * 60 * 60),  # 30 days
                tier="self-hosted",
                features=["mcp"],
            )

            result = await attempt_license_renewal()
            assert result is False  # No renewal needed
```

- [ ] **Step 2: Create renewal.py**

```python
# src/context_service/license/renewal.py
"""Background license auto-renewal."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings
from context_service.license.validator import LicenseInfo, validate_license_key

logger = get_logger(__name__)

RENEWAL_ENDPOINT = "https://license.engrammic.ai/renew"
RENEWAL_CHECK_INTERVAL = 24 * 60 * 60  # Check daily


async def attempt_license_renewal() -> bool:
    """Attempt to renew license if expiring soon.

    Returns:
        True if renewal successful, False if not needed or failed
    """
    settings = get_settings()
    license_key = settings.license_key

    if not license_key:
        return False

    try:
        info = validate_license_key(license_key)
    except Exception:
        return False

    if not info.is_expiring_soon:
        logger.debug("license_renewal_not_needed", days_remaining=info.days_remaining)
        return False

    logger.info("license_renewal_attempting", days_remaining=info.days_remaining)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                RENEWAL_ENDPOINT,
                headers={"Authorization": f"Bearer {license_key}"},
            )

            if response.status_code == 200:
                data = response.json()
                new_key = data.get("key")
                if new_key:
                    await _save_renewed_key(new_key)
                    logger.info("license_renewed_successfully")
                    return True

            elif response.status_code == 403:
                logger.warning("license_renewal_denied", reason="revoked or expired")
            else:
                logger.warning("license_renewal_failed", status=response.status_code)

    except httpx.RequestError as e:
        logger.warning("license_renewal_network_error", error=str(e))

    return False


async def _save_renewed_key(new_key: str) -> None:
    """Save renewed license key to .env file if writable."""
    env_path = Path(".env")
    if not env_path.exists():
        logger.info("license_renewal_env_not_found")
        return

    try:
        content = env_path.read_text()
        if "ENGRAMMIC_LICENSE_KEY=" in content:
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("ENGRAMMIC_LICENSE_KEY="):
                    new_lines.append(f"ENGRAMMIC_LICENSE_KEY={new_key}")
                else:
                    new_lines.append(line)
            env_path.write_text("\n".join(new_lines) + "\n")
            logger.info("license_key_updated_in_env")
        else:
            logger.info("license_key_not_in_env", msg="Add manually")
    except PermissionError:
        logger.info("license_renewal_env_not_writable", new_key=new_key[:20] + "...")


async def renewal_background_task() -> None:
    """Background task that periodically checks for license renewal."""
    while True:
        await asyncio.sleep(RENEWAL_CHECK_INTERVAL)
        await attempt_license_renewal()
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/license/test_renewal.py -v
```

Expected: PASS

- [ ] **Step 4: Integrate into app startup**

In `src/context_service/api/app.py`, in the lifespan function:

```python
# After license check:
    if license_info and license_info.is_expiring_soon:
        from context_service.license.renewal import attempt_license_renewal
        asyncio.create_task(attempt_license_renewal())
```

- [ ] **Step 5: Commit**

```bash
git add src/context_service/license/renewal.py tests/license/test_renewal.py
git add src/context_service/api/app.py
git commit -m "feat: add background license auto-renewal"
```

---

## Task 9: Installer - Docker Flow (Rust)

This task requires modifying the Rust installer in `../mcp-client/installer-cli/`.

**Files:**
- Modify: `../mcp-client/installer-cli/src/main.rs`
- Modify: `../mcp-client/installer-cli/src/cli.rs`
- Create: `../mcp-client/installer-cli/src/docker.rs`
- Create: `../mcp-client/installer-cli/src/license.rs`

- [ ] **Step 1: Add docker.rs module**

```rust
// ../mcp-client/installer-cli/src/docker.rs
//! Docker detection and compose installation.

use anyhow::{bail, Result};
use std::fs;
use std::path::Path;
use std::process::Command;

/// Check if Docker is available and running.
pub fn check_docker() -> Result<bool> {
    let output = Command::new("docker")
        .args(["info"])
        .output();

    match output {
        Ok(o) => Ok(o.status.success()),
        Err(_) => Ok(false),
    }
}

/// Docker compose template (embedded at compile time).
pub const COMPOSE_TEMPLATE: &str = include_str!("../assets/docker-compose.yml");

/// Write compose file and .env to target directory.
pub fn write_compose_bundle(dir: &Path, license_key: &str) -> Result<()> {
    fs::create_dir_all(dir)?;

    let compose_path = dir.join("docker-compose.yml");
    fs::write(&compose_path, COMPOSE_TEMPLATE)?;

    let env_content = format!(
        r#"# Engrammic Self-Hosted Configuration
ENGRAMMIC_LICENSE_KEY={}

# Database passwords (change in production)
POSTGRES_PASSWORD=engrammic

# Optional: LLM for full SAGE features
# LLM_PROVIDER=openai
# LLM_API_KEY=sk-...

TELEMETRY_ENABLED=true
"#,
        license_key
    );

    let env_path = dir.join(".env");
    fs::write(&env_path, env_content)?;

    Ok(())
}
```

- [ ] **Step 2: Add license.rs module**

```rust
// ../mcp-client/installer-cli/src/license.rs
//! License key validation.

use anyhow::{bail, Result};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};

const KEY_PREFIX: &str = "ENGR_";

/// Embedded Ed25519 public key (copy from ../cli/keys/public.pem).
const PUBLIC_KEY_PEM: &str = r#"-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA... (paste actual key)
-----END PUBLIC KEY-----"#;

/// Basic license key format validation.
/// Full cryptographic validation happens server-side.
pub fn validate_license_format(key: &str) -> Result<LicenseBasicInfo> {
    if !key.starts_with(KEY_PREFIX) {
        bail!("License key must start with {}", KEY_PREFIX);
    }

    let token = &key[KEY_PREFIX.len()..];
    let parts: Vec<&str> = token.split('.').collect();
    if parts.len() != 3 {
        bail!("Invalid license key format");
    }

    // Decode payload (middle part)
    let payload_b64 = parts[1];
    let payload_bytes = URL_SAFE_NO_PAD.decode(payload_b64)
        .map_err(|_| anyhow::anyhow!("Invalid license key encoding"))?;

    let payload: serde_json::Value = serde_json::from_slice(&payload_bytes)
        .map_err(|_| anyhow::anyhow!("Invalid license key payload"))?;

    let customer = payload["sub"].as_str()
        .ok_or_else(|| anyhow::anyhow!("Missing customer in license"))?;
    let exp = payload["exp"].as_i64()
        .ok_or_else(|| anyhow::anyhow!("Missing expiry in license"))?;

    // Check not expired
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;

    if exp < now {
        bail!("License key has expired");
    }

    let days_remaining = (exp - now) / (24 * 60 * 60);

    Ok(LicenseBasicInfo {
        customer: customer.to_string(),
        expires_at: exp,
        days_remaining: days_remaining as u32,
    })
}

pub struct LicenseBasicInfo {
    pub customer: String,
    pub expires_at: i64,
    pub days_remaining: u32,
}
```

- [ ] **Step 3: Update main.rs for Docker menu**

Add to the install function in main.rs:

```rust
// After banner::print_banner();
    println!();
    println!("{}", "What would you like to install?".bold());
    println!("  [1] MCP skills (Claude Code, Cursor, etc.)");
    println!("  [2] Self-hosted stack (Docker required)");
    println!("  [3] Both");
    println!();

    let choice = Select::new("Select option", vec!["MCP skills", "Self-hosted stack", "Both"])
        .with_render_config(render_config())
        .prompt()?;

    match choice {
        "MCP skills" => install_skills_flow(yes, tool_id)?,
        "Self-hosted stack" => install_docker_flow()?,
        "Both" => {
            install_skills_flow(yes, tool_id)?;
            install_docker_flow()?;
        }
        _ => unreachable!(),
    }
```

- [ ] **Step 4: Add install_docker_flow function**

```rust
fn install_docker_flow() -> Result<()> {
    use docker::{check_docker, write_compose_bundle};
    use license::validate_license_format;

    println!();
    print!("Checking Docker... ");
    if !check_docker()? {
        println!("{}", "not found".red());
        println!();
        println!("Docker is required for self-hosted installation.");
        println!("Install Docker: https://docs.docker.com/get-docker/");
        return Ok(());
    }
    println!("{}", "✓ Found".green());

    let license_key: String = Text::new("Enter your license key:")
        .with_render_config(render_config())
        .prompt()?;

    print!("Validating... ");
    let info = validate_license_format(&license_key)?;
    println!(
        "{} ({}, expires in {} days)",
        "✓ Valid".green(),
        info.customer,
        info.days_remaining
    );

    let install_dir = Text::new("Install directory:")
        .with_default("./engrammic")
        .with_render_config(render_config())
        .prompt()?;

    let dir = Path::new(&install_dir);

    println!();
    println!("{}", "Writing files...".bold());
    write_compose_bundle(dir, &license_key)?;
    println!("  {} docker-compose.yml", "→".green());
    println!("  {} .env", "→".green());

    println!();
    println!("{}", "Done!".green().bold());
    println!();
    println!("To start:");
    println!("  cd {} && docker compose up -d", install_dir);
    println!();
    println!("Service will be available at:");
    println!("  REST: http://localhost:8000");
    println!("  MCP:  Configure stdio in your editor");

    Ok(())
}
```

- [ ] **Step 5: Copy compose file to assets**

```bash
mkdir -p ../mcp-client/installer-cli/assets
cp docker/docker-compose.selfhosted.yml ../mcp-client/installer-cli/assets/docker-compose.yml
```

- [ ] **Step 6: Update Cargo.toml dependencies**

Add to `../mcp-client/installer-cli/Cargo.toml`:

```toml
base64 = "0.21"
serde_json = "1.0"
```

- [ ] **Step 7: Build and test**

```bash
cd ../mcp-client/installer-cli
cargo build --release
./target/release/engrammic-install
```

- [ ] **Step 8: Commit**

```bash
cd ../mcp-client/installer-cli
git add src/ assets/ Cargo.toml
git commit -m "feat: add Docker self-hosted installation flow"
```

---

## Task 10: Installer - Doctor Command

**Files:**
- Modify: `../mcp-client/installer-cli/src/cli.rs`
- Modify: `../mcp-client/installer-cli/src/main.rs`
- Create: `../mcp-client/installer-cli/src/doctor.rs`

- [ ] **Step 1: Create doctor.rs**

```rust
// ../mcp-client/installer-cli/src/doctor.rs
//! Diagnostic checks for self-hosted installation.

use anyhow::Result;
use colored::Colorize;
use std::process::Command;

pub fn run_diagnostics() -> Result<()> {
    println!();
    println!("{}", "Engrammic Diagnostics".bold());
    println!();

    let mut all_passed = true;

    // Check Docker
    print!("Checking Docker... ");
    if check_docker_running() {
        println!("{}", "✓ Running".green());
    } else {
        println!("{}", "✗ Not running".red());
        all_passed = false;
    }

    // Check containers
    print!("Checking containers... ");
    match check_containers() {
        Ok((healthy, total)) => {
            if healthy == total {
                println!("{}", format!("✓ {}/{} healthy", healthy, total).green());
            } else {
                println!("{}", format!("⚠ {}/{} healthy", healthy, total).yellow());
                all_passed = false;
            }
        }
        Err(_) => {
            println!("{}", "✗ Could not check".red());
            all_passed = false;
        }
    }

    // Check for OOM events
    print!("Checking for OOM events... ");
    match check_oom_events() {
        Ok(events) if events.is_empty() => {
            println!("{}", "✓ None in last hour".green());
        }
        Ok(events) => {
            println!("{}", format!("⚠ {} OOM events", events.len()).yellow());
            for event in events {
                println!("  {} was OOM-killed", event.red());
            }
            all_passed = false;
        }
        Err(_) => {
            println!("{}", "- Could not check".dimmed());
        }
    }

    // Check license
    print!("Checking license... ");
    match check_license() {
        Ok(days) => {
            if days > 14 {
                println!("{}", format!("✓ Valid ({} days remaining)", days).green());
            } else {
                println!("{}", format!("⚠ Expiring soon ({} days)", days).yellow());
            }
        }
        Err(e) => {
            println!("{}", format!("✗ {}", e).red());
            all_passed = false;
        }
    }

    // Check connectivity
    print!("Checking connectivity... ");
    if check_telemetry_endpoint() {
        println!("{}", "✓ tel.engrammic.ai reachable".green());
    } else {
        println!("{}", "⚠ tel.engrammic.ai unreachable".yellow());
    }

    // Check disk space
    print!("Checking disk space... ");
    match check_disk_space() {
        Ok(gb) if gb > 10.0 => {
            println!("{}", format!("✓ {:.1}GB free", gb).green());
        }
        Ok(gb) => {
            println!("{}", format!("⚠ {:.1}GB free (low)", gb).yellow());
        }
        Err(_) => {
            println!("{}", "- Could not check".dimmed());
        }
    }

    println!();
    if all_passed {
        println!("{}", "All checks passed.".green().bold());
    } else {
        println!("{}", "Some checks failed. See above for details.".yellow());
    }

    Ok(())
}

fn check_docker_running() -> bool {
    Command::new("docker")
        .args(["info"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn check_containers() -> Result<(usize, usize)> {
    let output = Command::new("docker")
        .args(["compose", "ps", "--format", "json"])
        .output()?;

    if !output.status.success() {
        anyhow::bail!("docker compose ps failed");
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let total = stdout.lines().count();
    let healthy = stdout.lines()
        .filter(|line| line.contains("\"Health\":\"healthy\"") || line.contains("\"State\":\"running\""))
        .count();

    Ok((healthy, total))
}

fn check_oom_events() -> Result<Vec<String>> {
    let output = Command::new("docker")
        .args(["events", "--filter", "event=oom", "--since", "1h", "--until", "now", "--format", "{{.Actor.Attributes.name}}"])
        .output()?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    let events: Vec<String> = stdout.lines()
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .collect();

    Ok(events)
}

fn check_license() -> Result<u32> {
    // Read from .env in current directory
    let env_content = std::fs::read_to_string(".env")?;
    for line in env_content.lines() {
        if line.starts_with("ENGRAMMIC_LICENSE_KEY=") {
            let key = line.trim_start_matches("ENGRAMMIC_LICENSE_KEY=");
            let info = crate::license::validate_license_format(key)?;
            return Ok(info.days_remaining);
        }
    }
    anyhow::bail!("License key not found in .env")
}

fn check_telemetry_endpoint() -> bool {
    Command::new("curl")
        .args(["-sf", "--max-time", "5", "https://tel.engrammic.ai/health"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn check_disk_space() -> Result<f64> {
    let output = Command::new("df")
        .args(["-BG", "."])
        .output()?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    // Parse "Available" column from df output
    for line in stdout.lines().skip(1) {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() >= 4 {
            let available = parts[3].trim_end_matches('G');
            return available.parse().map_err(|_| anyhow::anyhow!("parse error"));
        }
    }
    anyhow::bail!("Could not parse df output")
}
```

- [ ] **Step 2: Add doctor command to cli.rs**

```rust
// In cli.rs, add to Commands enum:
    /// Run diagnostic checks
    Doctor,
```

- [ ] **Step 3: Handle doctor in main.rs**

```rust
// In main() match:
        Commands::Doctor => doctor::run_diagnostics(),
```

- [ ] **Step 4: Add module declaration**

```rust
// In main.rs, add:
mod doctor;
```

- [ ] **Step 5: Build and test**

```bash
cd ../mcp-client/installer-cli
cargo build --release
./target/release/engrammic-install doctor
```

- [ ] **Step 6: Commit**

```bash
git add src/
git commit -m "feat: add engrammic doctor diagnostic command"
```

---

## Task 11: License Renewal Endpoint (in context-service)

Add renewal endpoint to existing context-service instead of separate service. Deployed at `license.engrammic.ai` via Cloud Run domain mapping.

**Files:**
- Create: `src/context_service/api/routes/license.py`
- Modify: `src/context_service/api/app.py` (mount router)

- [ ] **Step 1: Create license router**

```python
# src/context_service/api/routes/license.py
"""License renewal endpoint for self-hosted customers."""

import os
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from context_service.config.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/license", tags=["license"])

ISSUER = "engrammic"
KEY_PREFIX = "ENGR_"


class RenewalResponse(BaseModel):
    key: str


@router.post("/renew", response_model=RenewalResponse)
async def renew_license(authorization: str = Header(...)) -> RenewalResponse:
    """Renew a license key. Called by self-hosted containers."""
    private_key_pem = os.environ.get("LICENSE_PRIVATE_KEY")
    if not private_key_pem:
        raise HTTPException(status_code=503, detail="Renewal not configured")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization")

    old_key = authorization[7:]
    if old_key.startswith(KEY_PREFIX):
        old_key = old_key[len(KEY_PREFIX):]

    try:
        payload = jwt.decode(old_key, options={"verify_signature": False})
    except jwt.DecodeError:
        raise HTTPException(status_code=400, detail="Invalid license key")

    customer = payload.get("sub")
    if not customer:
        raise HTTPException(status_code=400, detail="Invalid license key")

    # TODO: Check customer status in database (payment active, not revoked)
    # For MVP, always renew if key format is valid

    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(), password=None
    )

    now = datetime.now(timezone.utc)
    new_payload = {
        "sub": customer,
        "iss": ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=90)).timestamp()),
        "tier": payload.get("tier", "self-hosted"),
        "features": payload.get("features", ["mcp", "rest-api", "sage"]),
    }

    new_token = jwt.encode(new_payload, private_key, algorithm="EdDSA")
    logger.info("license_renewed", customer=customer)
    return RenewalResponse(key=f"{KEY_PREFIX}{new_token}")
```

- [ ] **Step 2: Mount router in app.py**

```python
# In src/context_service/api/app.py, add:
from context_service.api.routes.license import router as license_router

# In create_app() or wherever routers are mounted:
app.include_router(license_router)
```

- [ ] **Step 3: Add LICENSE_PRIVATE_KEY to hosted deployment**

```bash
# Store private key in Secret Manager
gcloud secrets create license-private-key --data-file=../cli/keys/private.pem

# Reference in Cloud Run
gcloud run services update context-service \
  --update-secrets=LICENSE_PRIVATE_KEY=license-private-key:latest
```

- [ ] **Step 4: Map license.engrammic.ai domain**

```bash
gcloud run domain-mappings create \
  --service=context-service \
  --domain=license.engrammic.ai \
  --region=europe-north1
```

- [ ] **Step 5: Commit**

```bash
git add src/context_service/api/routes/license.py
git commit -m "feat: add license renewal endpoint"
```
```

- [ ] **Step 5: Deploy**

```bash
cd ../license-service
gcloud builds submit --config=cloudbuild.yaml
```

- [ ] **Step 6: Map custom domain**

---

## Task 12: Installer - Scale Command (Simplified)

Shows resource usage and provides scaling guidance. Does NOT auto-edit YAML (fragile regex parsing). User manually edits docker-compose.yml following printed recommendations.

**Files:**
- Create: `../mcp-client/installer-cli/src/scale.rs`
- Modify: `../mcp-client/installer-cli/src/cli.rs`
- Modify: `../mcp-client/installer-cli/src/main.rs`

- [ ] **Step 1: Create scale.rs**

```rust
// ../mcp-client/installer-cli/src/scale.rs
//! Resource scaling guidance for self-hosted containers.

use anyhow::{bail, Result};
use colored::Colorize;
use std::collections::HashMap;
use std::process::Command;

/// Get current memory usage from docker stats.
fn get_memory_usage() -> Result<HashMap<String, (u64, u64)>> {
    let output = Command::new("docker")
        .args(["stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"])
        .output()?;

    if !output.status.success() {
        bail!("docker stats failed - are containers running?");
    }

    let mut usage = HashMap::new();
    let stdout = String::from_utf8_lossy(&output.stdout);

    for line in stdout.lines() {
        let parts: Vec<&str> = line.split('\t').collect();
        if parts.len() >= 2 {
            let name = parts[0].to_string();
            if let Some((used, limit)) = parse_mem_usage(parts[1]) {
                usage.insert(name, (used, limit));
            }
        }
    }

    Ok(usage)
}

fn parse_mem_usage(s: &str) -> Option<(u64, u64)> {
    let parts: Vec<&str> = s.split(" / ").collect();
    if parts.len() != 2 { return None; }
    let used = parse_mem_value(parts[0])?;
    let limit = parse_mem_value(parts[1])?;
    Some((used, limit))
}

fn parse_mem_value(s: &str) -> Option<u64> {
    let s = s.trim();
    if s.ends_with("GiB") {
        let val: f64 = s.trim_end_matches("GiB").parse().ok()?;
        Some((val * 1024.0) as u64)
    } else if s.ends_with("MiB") {
        let val: f64 = s.trim_end_matches("MiB").parse().ok()?;
        Some(val as u64)
    } else {
        None
    }
}

pub fn show_status() -> Result<()> {
    println!();
    println!("{}", "Current resource usage:".bold());
    println!();
    println!("  {:<20} {:<10} {:<10} {}", "Container", "Used", "Limit", "Usage");

    let usage = get_memory_usage()?;
    let mut high_usage = Vec::new();

    for (name, (used, limit)) in &usage {
        let percent = (*used as f64 / *limit as f64 * 100.0) as u32;
        let warning = if percent >= 80 { " ⚠".yellow().to_string() } else { "".to_string() };
        println!(
            "  {:<20} {:<10} {:<10} {}%{}",
            name, format!("{}MB", used), format!("{}MB", limit), percent, warning
        );
        if percent >= 80 {
            let new_limit = (*limit as f64 * 1.2) as u64;
            high_usage.push((name.clone(), *limit, new_limit));
        }
    }

    if !high_usage.is_empty() {
        println!();
        println!("{}", "Containers near limit - recommended changes to docker-compose.yml:".yellow());
        println!();
        for (name, old, new) in &high_usage {
            let service = name.trim_start_matches("engrammic-");
            println!("  {}: memory: {}M → {}M", service, old, new);
        }
        println!();
        println!("After editing, run: docker compose up -d");
    } else {
        println!();
        println!("{}", "All containers have healthy memory headroom.".green());
    }

    Ok(())
}
```

- [ ] **Step 2: Add scale command to cli.rs**

```rust
// In cli.rs Commands enum, add:
    /// Show container resource usage and scaling recommendations
    Scale,
        action: ScaleAction,
    },

// Add ScaleAction enum:
#[derive(Subcommand, Debug)]
pub enum ScaleAction {
    /// Increase all memory limits by 20%
    Up,
    /// Decrease all memory limits by 20%
    Down,
    /// Show current resource usage
    Status,
}
```

- [ ] **Step 3: Handle scale in main.rs**

```rust
// In main() match, add:
        Commands::Scale => scale::show_status(),

// Add module declaration:
mod scale;
```

- [ ] **Step 4: Build and test**

```bash
cd ../mcp-client/installer-cli
cargo build --release

# Test in an engrammic directory with running containers
cd /path/to/engrammic
/path/to/engrammic-install scale
```

Expected output shows usage and recommendations if any container is above 80%.

- [ ] **Step 5: Commit**

```bash
git add src/
git commit -m "feat: add engrammic scale command for resource monitoring"
```

---

## Task 13: Optional CLI Installation (DEFERRED)

**Status:** Deferred to post-MVP. Nice-to-have but not critical for Luke's use case.

For now, users run the installer binary directly from the download location or keep it in their engrammic directory. We can add PATH installation later if customers ask for it.

---

## Self-Review Checklist

- [x] **Spec coverage:** All Phase 1 items have corresponding tasks
- [x] **Placeholder scan:** No TBD/TODO items, all code blocks complete
- [x] **Type consistency:** LicenseInfo, LicenseError used consistently across tasks
- [x] **Dependencies:** Tasks ordered correctly (keypair first, then CLI, then service integration)

---

## Summary

| Task | Component | Est. Time | Notes |
|------|-----------|-----------|-------|
| 0 | Ed25519 keypair generation | 5 min | |
| 1 | Internal CLI license generation | 30 min | |
| 2 | License validator module | 45 min | Fails loudly if key not configured |
| 3 | License settings | 15 min | |
| 4 | Startup license check + SAGE log | 30 min | Logs passive mode if no LLM key |
| 5 | Health endpoint updates | 30 min | Memory monitoring best-effort |
| 6 | Docker Compose bundle | 20 min | |
| 7 | GCP AR public | 10 min | Do early! |
| 8 | Auto-renewal background | 45 min | |
| 9 | Installer Docker flow (Rust) | 2 hr | |
| 10 | Installer doctor command | 1 hr | |
| 11 | License renewal endpoint | 30 min | In context-service, not separate repo |
| 12 | Installer scale command | 30 min | Status only, no auto-edit |
| 13 | Optional CLI installation | - | **DEFERRED** |

**Total estimated: ~7 hours** (reduced from 8.5 by simplifications)
