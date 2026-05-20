# Self-Hosted REST API Phase 1: Auth + Core Data Endpoints

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement self-hosted auth infrastructure and Memory/Knowledge layer REST endpoints.

**Architecture:** Self-hosted auth loads from YAML config when `SELF_HOSTED_AUTH=true`. Three strategies: proxy (trust headers), JWT (validate tokens), API keys (service-to-service). Data endpoints follow layer-aligned structure (`/v1/memory/`, `/v1/knowledge/`) with standard envelope responses.

**Tech Stack:** FastAPI, Pydantic v2, PyJWT, cryptography, structlog

**Spec:** `docs/superpowers/specs/2026-05-20-self-hosted-rest-api-design.md`

**Model Adaptation Note:** The actual `Node` model uses:
- `id: uuid.UUID` (not `node_id`)
- `type: str` (e.g., "Observation", "Claim")
- `properties: dict` (stores `layer`, `tags`, `metadata`)
- `silo_id: uuid.UUID` (not `str`)

All endpoint code adapts the REST API schema to this internal model structure.

---

## File Structure

```
src/context_service/
  api/
    v1/                           # NEW - versioned API routes
      __init__.py
      memory.py                   # Memory layer endpoints
      knowledge.py                # Knowledge layer endpoints
      schemas.py                  # Shared request/response models
    auth/                         # NEW - auth strategies
      __init__.py
      config.py                   # YAML config loader
      proxy.py                    # Proxy header strategy
      jwt.py                      # JWT validation strategy
      api_key.py                  # API key strategy
      context.py                  # Unified AuthContext
    deps.py                       # MODIFY - add self-hosted auth resolution
    app.py                        # MODIFY - mount v1 router
  config/
    settings.py                   # MODIFY - add SELF_HOSTED_AUTH setting

tests/
  api/
    v1/
      test_memory.py
      test_knowledge.py
    auth/
      test_proxy.py
      test_jwt.py
      test_api_key.py
      test_config.py
```

---

## Task 0: Create Test Directories

- [ ] **Step 1: Create test directories**

```bash
mkdir -p tests/api/auth tests/api/v1
touch tests/api/auth/__init__.py tests/api/v1/__init__.py
```

- [ ] **Step 2: Commit**

```bash
git add tests/api/auth/ tests/api/v1/
git commit -m "chore: create test directories for v1 API"
```

---

## Task 1: Add SELF_HOSTED_AUTH Setting

**Files:**
- Modify: `src/context_service/config/settings.py`
- Test: `tests/config/test_settings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/config/test_settings.py (append)

def test_self_hosted_auth_defaults_false() -> None:
    """SELF_HOSTED_AUTH defaults to False."""
    import os
    os.environ.pop("SELF_HOSTED_AUTH", None)
    os.environ.pop("AUTH_CONFIG_PATH", None)
    
    from context_service.config.settings import Settings
    settings = Settings()
    
    assert settings.self_hosted_auth is False
    assert settings.auth_config_path == "/etc/engrammic/auth.yaml"


def test_self_hosted_auth_enabled() -> None:
    """SELF_HOSTED_AUTH=true enables self-hosted mode."""
    import os
    os.environ["SELF_HOSTED_AUTH"] = "true"
    os.environ["AUTH_CONFIG_PATH"] = "/custom/auth.yaml"
    
    from context_service.config.settings import Settings
    settings = Settings()
    
    assert settings.self_hosted_auth is True
    assert settings.auth_config_path == "/custom/auth.yaml"
    
    os.environ.pop("SELF_HOSTED_AUTH", None)
    os.environ.pop("AUTH_CONFIG_PATH", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/config/test_settings.py::test_self_hosted_auth_defaults_false -v`
Expected: FAIL with AttributeError

- [ ] **Step 3: Add settings fields**

In `src/context_service/config/settings.py`, add to the `Settings` class:

```python
    # Self-hosted auth
    self_hosted_auth: bool = Field(
        default=False,
        description="Enable self-hosted auth mode (proxy/JWT/API key)",
    )
    auth_config_path: str = Field(
        default="/etc/engrammic/auth.yaml",
        description="Path to auth config YAML when self_hosted_auth=True",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/config/test_settings.py::test_self_hosted_auth_defaults_false tests/config/test_settings.py::test_self_hosted_auth_enabled -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/config/settings.py tests/config/test_settings.py
git commit -m "feat(auth): add SELF_HOSTED_AUTH setting"
```

---

## Task 2: Auth Config Loader

**Files:**
- Create: `src/context_service/api/auth/__init__.py`
- Create: `src/context_service/api/auth/config.py`
- Test: `tests/api/auth/test_config.py`

- [ ] **Step 1: Create auth module init**

```python
# src/context_service/api/auth/__init__.py
"""Self-hosted authentication strategies."""

from context_service.api.auth.config import AuthConfig, load_auth_config

__all__ = ["AuthConfig", "load_auth_config"]
```

- [ ] **Step 2: Write failing test for config loader**

```python
# tests/api/auth/test_config.py
"""Tests for auth config loading."""

from __future__ import annotations

import pytest
import tempfile
from pathlib import Path


def test_load_proxy_config() -> None:
    """Load proxy strategy config from YAML."""
    yaml_content = """
strategy: proxy
proxy:
  headers:
    silo_id: X-Silo-Id
    user_id: X-User-Id
    scopes: X-Auth-Scopes
  require_https: true
  trusted_source_ips:
    - 10.0.0.0/8
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        
        from context_service.api.auth.config import load_auth_config
        
        config = load_auth_config(Path(f.name))
        
        assert config.strategy == "proxy"
        assert config.proxy is not None
        assert config.proxy.headers.silo_id == "X-Silo-Id"
        assert config.proxy.headers.user_id == "X-User-Id"
        assert config.proxy.require_https is True
        assert "10.0.0.0/8" in config.proxy.trusted_source_ips


def test_load_jwt_config() -> None:
    """Load JWT strategy config from YAML."""
    yaml_content = """
strategy: jwt
jwt:
  issuer: https://auth.example.com
  jwks_uri: https://auth.example.com/.well-known/jwks.json
  audience: engrammic
  allowed_algorithms:
    - RS256
    - ES256
  max_clock_skew_seconds: 120
  claims:
    silo_id: silo
    scopes: scope
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        
        from context_service.api.auth.config import load_auth_config
        
        config = load_auth_config(Path(f.name))
        
        assert config.strategy == "jwt"
        assert config.jwt is not None
        assert config.jwt.issuer == "https://auth.example.com"
        assert config.jwt.allowed_algorithms == ["RS256", "ES256"]
        assert config.jwt.max_clock_skew_seconds == 120


def test_load_api_key_config() -> None:
    """Load API key strategy config from YAML."""
    yaml_content = """
strategy: api_key
api_key:
  keys:
    - id: svc_etl
      secret_hash: "sha256:abc123"
      silo_id: engineering
      scopes:
        - read
        - write
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        
        from context_service.api.auth.config import load_auth_config
        
        config = load_auth_config(Path(f.name))
        
        assert config.strategy == "api_key"
        assert config.api_key is not None
        assert len(config.api_key.keys) == 1
        assert config.api_key.keys[0].id == "svc_etl"
        assert config.api_key.keys[0].silo_id == "engineering"


def test_missing_config_file_raises() -> None:
    """Missing config file raises FileNotFoundError."""
    from context_service.api.auth.config import load_auth_config
    
    with pytest.raises(FileNotFoundError):
        load_auth_config(Path("/nonexistent/auth.yaml"))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/api/auth/test_config.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 4: Implement config loader**

```python
# src/context_service/api/auth/config.py
"""Self-hosted auth configuration loader."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ProxyHeaders(BaseModel):
    """Header names for proxy auth."""

    silo_id: str = "X-Silo-Id"
    user_id: str | None = "X-User-Id"
    scopes: str | None = "X-Auth-Scopes"


class ProxyConfig(BaseModel):
    """Proxy strategy configuration."""

    headers: ProxyHeaders = Field(default_factory=ProxyHeaders)
    require_https: bool = True
    trusted_source_ips: list[str] = Field(default_factory=list)


class JWTClaims(BaseModel):
    """JWT claim mappings."""

    silo_id: str = "silo_id"
    scopes: str = "scope"


class JWTConfig(BaseModel):
    """JWT strategy configuration."""

    issuer: str
    jwks_uri: str
    audience: str | None = None
    allowed_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    max_clock_skew_seconds: int = 60
    claims: JWTClaims = Field(default_factory=JWTClaims)


class APIKeyEntry(BaseModel):
    """Single API key definition."""

    id: str
    secret_hash: str
    silo_id: str
    scopes: list[str]
    expires_at: str | None = None


class APIKeyConfig(BaseModel):
    """API key strategy configuration."""

    keys_file: str | None = None
    keys: list[APIKeyEntry] = Field(default_factory=list)


class AuthConfig(BaseModel):
    """Root auth configuration."""

    strategy: Literal["proxy", "jwt", "api_key"]
    proxy: ProxyConfig | None = None
    jwt: JWTConfig | None = None
    api_key: APIKeyConfig | None = None


def load_auth_config(path: Path) -> AuthConfig:
    """Load auth configuration from YAML file.

    Args:
        path: Path to auth.yaml

    Returns:
        Parsed AuthConfig

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    if not path.exists():
        raise FileNotFoundError(f"Auth config not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    return AuthConfig.model_validate(data)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/auth/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/api/auth/ tests/api/auth/
git commit -m "feat(auth): add self-hosted auth config loader"
```

---

## Task 3: Proxy Auth Strategy

**Files:**
- Create: `src/context_service/api/auth/context.py`
- Create: `src/context_service/api/auth/proxy.py`
- Test: `tests/api/auth/test_proxy.py`

- [ ] **Step 1: Create unified AuthContext model**

```python
# src/context_service/api/auth/context.py
"""Unified auth context for all strategies."""

from __future__ import annotations

from pydantic import BaseModel


class SelfHostedAuthContext(BaseModel):
    """Auth context for self-hosted deployments."""

    silo_id: str
    user_id: str | None = None
    scopes: set[str] = {"read", "write"}
    strategy: str  # proxy, jwt, api_key

    def has_scope(self, scope: str) -> bool:
        """Check if context has required scope."""
        return scope in self.scopes
```

- [ ] **Step 2: Write failing test for proxy strategy**

```python
# tests/api/auth/test_proxy.py
"""Tests for proxy auth strategy."""

from __future__ import annotations

import pytest
from fastapi import Request
from starlette.datastructures import Headers


def make_request(headers: dict[str, str], client_ip: str = "10.0.0.1") -> Request:
    """Create a mock request with given headers."""
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (client_ip, 12345),
    }
    return Request(scope)


@pytest.fixture
def proxy_config():
    from context_service.api.auth.config import ProxyConfig, ProxyHeaders
    return ProxyConfig(
        headers=ProxyHeaders(
            silo_id="X-Silo-Id",
            user_id="X-User-Id",
            scopes="X-Auth-Scopes",
        ),
        require_https=False,
        trusted_source_ips=["10.0.0.0/8"],
    )


async def test_proxy_extracts_headers(proxy_config) -> None:
    """Proxy strategy extracts auth from headers."""
    from context_service.api.auth.proxy import ProxyAuthStrategy
    
    strategy = ProxyAuthStrategy(proxy_config)
    request = make_request({
        "X-Silo-Id": "engineering",
        "X-User-Id": "user123",
        "X-Auth-Scopes": "read,write,admin",
    })
    
    ctx = await strategy.authenticate(request)
    
    assert ctx.silo_id == "engineering"
    assert ctx.user_id == "user123"
    assert ctx.scopes == {"read", "write", "admin"}
    assert ctx.strategy == "proxy"


async def test_proxy_missing_silo_raises(proxy_config) -> None:
    """Missing silo header raises 401."""
    from context_service.api.auth.proxy import ProxyAuthStrategy, AuthenticationError
    
    strategy = ProxyAuthStrategy(proxy_config)
    request = make_request({"X-User-Id": "user123"})
    
    with pytest.raises(AuthenticationError, match="Missing required header"):
        await strategy.authenticate(request)


async def test_proxy_untrusted_ip_raises(proxy_config) -> None:
    """Request from untrusted IP raises 401."""
    from context_service.api.auth.proxy import ProxyAuthStrategy, AuthenticationError
    
    strategy = ProxyAuthStrategy(proxy_config)
    request = make_request(
        {"X-Silo-Id": "engineering"},
        client_ip="192.168.1.1",  # Not in 10.0.0.0/8
    )
    
    with pytest.raises(AuthenticationError, match="Untrusted source IP"):
        await strategy.authenticate(request)


async def test_proxy_default_scopes(proxy_config) -> None:
    """Missing scopes header uses default read,write."""
    from context_service.api.auth.proxy import ProxyAuthStrategy
    
    strategy = ProxyAuthStrategy(proxy_config)
    request = make_request({"X-Silo-Id": "engineering"})
    
    ctx = await strategy.authenticate(request)
    
    assert ctx.scopes == {"read", "write"}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/api/auth/test_proxy.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 4: Implement proxy strategy**

```python
# src/context_service/api/auth/proxy.py
"""Proxy header authentication strategy."""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from context_service.api.auth.config import ProxyConfig
from context_service.api.auth.context import SelfHostedAuthContext

if TYPE_CHECKING:
    from fastapi import Request


class AuthenticationError(Exception):
    """Authentication failed."""

    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ProxyAuthStrategy:
    """Authenticate via trusted proxy headers."""

    def __init__(self, config: ProxyConfig):
        self.config = config
        self._trusted_networks = [
            ipaddress.ip_network(cidr, strict=False)
            for cidr in config.trusted_source_ips
        ]

    def _is_trusted_ip(self, ip: str) -> bool:
        """Check if IP is in trusted networks."""
        if not self._trusted_networks:
            return True  # No restriction if no networks configured
        try:
            addr = ipaddress.ip_address(ip)
            return any(addr in network for network in self._trusted_networks)
        except ValueError:
            return False

    async def authenticate(self, request: Request) -> SelfHostedAuthContext:
        """Extract auth context from proxy headers.

        Args:
            request: FastAPI request

        Returns:
            SelfHostedAuthContext

        Raises:
            AuthenticationError: If authentication fails
        """
        # Check trusted IP
        client_ip = request.client.host if request.client else "unknown"
        if not self._is_trusted_ip(client_ip):
            raise AuthenticationError(f"Untrusted source IP: {client_ip}")

        # Check HTTPS if required
        if self.config.require_https:
            proto = request.headers.get("X-Forwarded-Proto", "http")
            if proto != "https":
                raise AuthenticationError("HTTPS required")

        # Extract silo_id (required)
        silo_id = request.headers.get(self.config.headers.silo_id)
        if not silo_id:
            raise AuthenticationError(
                f"Missing required header: {self.config.headers.silo_id}"
            )

        # Extract user_id (optional)
        user_id = None
        if self.config.headers.user_id:
            user_id = request.headers.get(self.config.headers.user_id)

        # Extract scopes (optional, default read,write)
        scopes = {"read", "write"}
        if self.config.headers.scopes:
            scopes_header = request.headers.get(self.config.headers.scopes)
            if scopes_header:
                scopes = {s.strip() for s in scopes_header.split(",")}

        return SelfHostedAuthContext(
            silo_id=silo_id,
            user_id=user_id,
            scopes=scopes,
            strategy="proxy",
        )
```

- [ ] **Step 5: Update auth module exports**

```python
# src/context_service/api/auth/__init__.py
"""Self-hosted authentication strategies."""

from context_service.api.auth.config import AuthConfig, load_auth_config
from context_service.api.auth.context import SelfHostedAuthContext
from context_service.api.auth.proxy import AuthenticationError, ProxyAuthStrategy

__all__ = [
    "AuthConfig",
    "AuthenticationError",
    "load_auth_config",
    "ProxyAuthStrategy",
    "SelfHostedAuthContext",
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/api/auth/test_proxy.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/context_service/api/auth/ tests/api/auth/test_proxy.py
git commit -m "feat(auth): add proxy header authentication strategy"
```

---

## Task 4: JWT Auth Strategy

**Files:**
- Create: `src/context_service/api/auth/jwt.py`
- Test: `tests/api/auth/test_jwt.py`

- [ ] **Step 1: Write failing test for JWT strategy**

```python
# tests/api/auth/test_jwt.py
"""Tests for JWT auth strategy."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt as pyjwt


@pytest.fixture
def rsa_keypair():
    """Generate RSA keypair for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()
    
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    
    return private_pem, public_pem, private_key, public_key


@pytest.fixture
def jwt_config():
    from context_service.api.auth.config import JWTConfig, JWTClaims
    return JWTConfig(
        issuer="https://auth.example.com",
        jwks_uri="https://auth.example.com/.well-known/jwks.json",
        audience="engrammic",
        allowed_algorithms=["RS256"],
        max_clock_skew_seconds=60,
        claims=JWTClaims(silo_id="silo", scopes="scope"),
    )


def make_request(token: str):
    """Create mock request with Authorization header."""
    from fastapi import Request
    scope = {
        "type": "http",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


async def test_jwt_validates_token(jwt_config, rsa_keypair) -> None:
    """JWT strategy validates and extracts claims."""
    from context_service.api.auth.jwt import JWTAuthStrategy
    
    private_pem, public_pem, _, public_key = rsa_keypair
    
    # Create valid token
    payload = {
        "iss": "https://auth.example.com",
        "aud": "engrammic",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "silo": "engineering",
        "scope": "read write admin",
    }
    token = pyjwt.encode(payload, private_pem, algorithm="RS256")
    
    strategy = JWTAuthStrategy(jwt_config)
    
    # Mock JWKS fetch
    with patch.object(strategy, "_get_public_key", return_value=public_key):
        request = make_request(token)
        ctx = await strategy.authenticate(request)
    
    assert ctx.silo_id == "engineering"
    assert ctx.scopes == {"read", "write", "admin"}
    assert ctx.strategy == "jwt"


async def test_jwt_rejects_expired_token(jwt_config, rsa_keypair) -> None:
    """JWT strategy rejects expired tokens."""
    from context_service.api.auth.jwt import JWTAuthStrategy
    from context_service.api.auth.proxy import AuthenticationError
    
    private_pem, _, _, public_key = rsa_keypair
    
    # Create expired token
    payload = {
        "iss": "https://auth.example.com",
        "aud": "engrammic",
        "exp": int(time.time()) - 3600,  # Expired 1 hour ago
        "iat": int(time.time()) - 7200,
        "silo": "engineering",
        "scope": "read",
    }
    token = pyjwt.encode(payload, private_pem, algorithm="RS256")
    
    strategy = JWTAuthStrategy(jwt_config)
    
    with patch.object(strategy, "_get_public_key", return_value=public_key):
        request = make_request(token)
        with pytest.raises(AuthenticationError, match="expired"):
            await strategy.authenticate(request)


async def test_jwt_rejects_wrong_issuer(jwt_config, rsa_keypair) -> None:
    """JWT strategy rejects tokens from wrong issuer."""
    from context_service.api.auth.jwt import JWTAuthStrategy
    from context_service.api.auth.proxy import AuthenticationError
    
    private_pem, _, _, public_key = rsa_keypair
    
    payload = {
        "iss": "https://evil.com",  # Wrong issuer
        "aud": "engrammic",
        "exp": int(time.time()) + 3600,
        "silo": "engineering",
        "scope": "read",
    }
    token = pyjwt.encode(payload, private_pem, algorithm="RS256")
    
    strategy = JWTAuthStrategy(jwt_config)
    
    with patch.object(strategy, "_get_public_key", return_value=public_key):
        request = make_request(token)
        with pytest.raises(AuthenticationError, match="issuer"):
            await strategy.authenticate(request)


async def test_jwt_rejects_none_algorithm(jwt_config, rsa_keypair) -> None:
    """JWT strategy rejects 'none' algorithm attack."""
    from context_service.api.auth.jwt import JWTAuthStrategy
    from context_service.api.auth.proxy import AuthenticationError
    
    _, _, _, public_key = rsa_keypair
    
    # Create unsigned token (none algorithm attack)
    header = {"alg": "none", "typ": "JWT"}
    payload = {
        "iss": "https://auth.example.com",
        "aud": "engrammic",
        "exp": int(time.time()) + 3600,
        "silo": "engineering",
        "scope": "admin",
    }
    token = pyjwt.encode(payload, None, algorithm="none")
    
    strategy = JWTAuthStrategy(jwt_config)
    
    with patch.object(strategy, "_get_public_key", return_value=public_key):
        request = make_request(token)
        with pytest.raises(AuthenticationError):
            await strategy.authenticate(request)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/auth/test_jwt.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement JWT strategy**

```python
# src/context_service/api/auth/jwt.py
"""JWT authentication strategy."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import httpx
import jwt as pyjwt
from jwt import PyJWKClient

from context_service.api.auth.config import JWTConfig
from context_service.api.auth.context import SelfHostedAuthContext
from context_service.api.auth.proxy import AuthenticationError

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.types import PublicKeyTypes
    from fastapi import Request


class JWTAuthStrategy:
    """Authenticate via JWT tokens validated against JWKS."""

    def __init__(self, config: JWTConfig):
        self.config = config
        self._jwks_client: PyJWKClient | None = None

    def _get_jwks_client(self) -> PyJWKClient:
        """Get or create JWKS client."""
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self.config.jwks_uri)
        return self._jwks_client

    async def _get_public_key(self, token: str) -> PublicKeyTypes:
        """Fetch public key from JWKS for token."""
        client = self._get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        return signing_key.key

    async def authenticate(self, request: Request) -> SelfHostedAuthContext:
        """Validate JWT and extract auth context.

        Args:
            request: FastAPI request

        Returns:
            SelfHostedAuthContext

        Raises:
            AuthenticationError: If authentication fails
        """
        # Extract token from Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise AuthenticationError("Missing or invalid Authorization header")

        token = auth_header.removeprefix("Bearer ").strip()
        if not token:
            raise AuthenticationError("Empty token")

        # Get unverified header to check algorithm
        try:
            unverified_header = pyjwt.get_unverified_header(token)
        except pyjwt.exceptions.DecodeError as e:
            raise AuthenticationError(f"Invalid token format: {e}")

        # Reject disallowed algorithms (including 'none')
        alg = unverified_header.get("alg", "")
        if alg not in self.config.allowed_algorithms:
            raise AuthenticationError(f"Algorithm not allowed: {alg}")

        # Fetch public key and validate
        try:
            public_key = await self._get_public_key(token)
        except Exception as e:
            raise AuthenticationError(f"Failed to fetch signing key: {e}")

        try:
            payload = pyjwt.decode(
                token,
                public_key,
                algorithms=self.config.allowed_algorithms,
                issuer=self.config.issuer,
                audience=self.config.audience,
                leeway=self.config.max_clock_skew_seconds,
            )
        except pyjwt.ExpiredSignatureError:
            raise AuthenticationError("Token expired")
        except pyjwt.InvalidIssuerError:
            raise AuthenticationError("Invalid issuer")
        except pyjwt.InvalidAudienceError:
            raise AuthenticationError("Invalid audience")
        except pyjwt.PyJWTError as e:
            raise AuthenticationError(f"Token validation failed: {e}")

        # Extract claims
        silo_id = payload.get(self.config.claims.silo_id)
        if not silo_id:
            raise AuthenticationError(
                f"Missing required claim: {self.config.claims.silo_id}"
            )

        # Parse scopes (space-separated string or list)
        scopes_claim = payload.get(self.config.claims.scopes, "read write")
        if isinstance(scopes_claim, list):
            scopes = set(scopes_claim)
        else:
            scopes = {s.strip() for s in str(scopes_claim).split()}

        return SelfHostedAuthContext(
            silo_id=silo_id,
            user_id=payload.get("sub"),
            scopes=scopes,
            strategy="jwt",
        )
```

- [ ] **Step 4: Update auth module exports**

In `src/context_service/api/auth/__init__.py`, add:

```python
from context_service.api.auth.jwt import JWTAuthStrategy
```

And update `__all__` to include `"JWTAuthStrategy"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/auth/test_jwt.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/api/auth/ tests/api/auth/test_jwt.py
git commit -m "feat(auth): add JWT authentication strategy"
```

---

## Task 5: API Key Auth Strategy

**Files:**
- Create: `src/context_service/api/auth/api_key.py`
- Test: `tests/api/auth/test_api_key.py`

- [ ] **Step 1: Write failing test for API key strategy**

```python
# tests/api/auth/test_api_key.py
"""Tests for API key auth strategy."""

from __future__ import annotations

import hashlib
import pytest


def make_request(token: str | None):
    """Create mock request with Authorization header."""
    from fastapi import Request
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    scope = {
        "type": "http",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


@pytest.fixture
def api_key_config():
    from context_service.api.auth.config import APIKeyConfig, APIKeyEntry
    
    # Hash of "secret123"
    secret_hash = "sha256:" + hashlib.sha256(b"secret123").hexdigest()
    
    return APIKeyConfig(
        keys=[
            APIKeyEntry(
                id="svc_etl",
                secret_hash=secret_hash,
                silo_id="engineering",
                scopes=["read", "write"],
            ),
            APIKeyEntry(
                id="svc_admin",
                secret_hash="sha256:" + hashlib.sha256(b"admin456").hexdigest(),
                silo_id="engineering",
                scopes=["read", "write", "admin"],
            ),
        ]
    )


async def test_api_key_validates(api_key_config) -> None:
    """API key strategy validates correct key."""
    from context_service.api.auth.api_key import APIKeyAuthStrategy
    
    strategy = APIKeyAuthStrategy(api_key_config)
    # Token format: key_id:secret
    request = make_request("svc_etl:secret123")
    
    ctx = await strategy.authenticate(request)
    
    assert ctx.silo_id == "engineering"
    assert ctx.scopes == {"read", "write"}
    assert ctx.strategy == "api_key"


async def test_api_key_wrong_secret_raises(api_key_config) -> None:
    """Wrong secret raises 401."""
    from context_service.api.auth.api_key import APIKeyAuthStrategy
    from context_service.api.auth.proxy import AuthenticationError
    
    strategy = APIKeyAuthStrategy(api_key_config)
    request = make_request("svc_etl:wrongsecret")
    
    with pytest.raises(AuthenticationError, match="Invalid"):
        await strategy.authenticate(request)


async def test_api_key_unknown_id_raises(api_key_config) -> None:
    """Unknown key ID raises 401."""
    from context_service.api.auth.api_key import APIKeyAuthStrategy
    from context_service.api.auth.proxy import AuthenticationError
    
    strategy = APIKeyAuthStrategy(api_key_config)
    request = make_request("unknown_key:secret123")
    
    with pytest.raises(AuthenticationError, match="Unknown"):
        await strategy.authenticate(request)


async def test_api_key_missing_header_raises(api_key_config) -> None:
    """Missing Authorization header raises 401."""
    from context_service.api.auth.api_key import APIKeyAuthStrategy
    from context_service.api.auth.proxy import AuthenticationError
    
    strategy = APIKeyAuthStrategy(api_key_config)
    request = make_request(None)
    
    with pytest.raises(AuthenticationError, match="Missing"):
        await strategy.authenticate(request)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/auth/test_api_key.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement API key strategy**

```python
# src/context_service/api/auth/api_key.py
"""API key authentication strategy."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, UTC
from typing import TYPE_CHECKING

from context_service.api.auth.config import APIKeyConfig
from context_service.api.auth.context import SelfHostedAuthContext
from context_service.api.auth.proxy import AuthenticationError

if TYPE_CHECKING:
    from fastapi import Request


class APIKeyAuthStrategy:
    """Authenticate via API keys."""

    def __init__(self, config: APIKeyConfig):
        self.config = config
        # Build lookup table: key_id -> entry
        self._keys = {entry.id: entry for entry in config.keys}

    def _verify_hash(self, secret: str, stored_hash: str) -> bool:
        """Verify secret against stored hash."""
        if stored_hash.startswith("sha256:"):
            expected = stored_hash.removeprefix("sha256:")
            actual = hashlib.sha256(secret.encode()).hexdigest()
            return hmac.compare_digest(expected, actual)
        return False

    async def authenticate(self, request: Request) -> SelfHostedAuthContext:
        """Validate API key and extract auth context.

        Token format: key_id:secret

        Args:
            request: FastAPI request

        Returns:
            SelfHostedAuthContext

        Raises:
            AuthenticationError: If authentication fails
        """
        # Extract token from Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise AuthenticationError("Missing or invalid Authorization header")

        token = auth_header.removeprefix("Bearer ").strip()
        if not token:
            raise AuthenticationError("Empty token")

        # Parse key_id:secret
        if ":" not in token:
            raise AuthenticationError("Invalid API key format (expected id:secret)")

        key_id, secret = token.split(":", 1)

        # Look up key
        entry = self._keys.get(key_id)
        if entry is None:
            raise AuthenticationError(f"Unknown API key: {key_id}")

        # Check expiry
        if entry.expires_at:
            try:
                expires = datetime.fromisoformat(entry.expires_at.replace("Z", "+00:00"))
                if datetime.now(UTC) > expires:
                    raise AuthenticationError("API key expired")
            except ValueError:
                pass  # Invalid date format, skip check

        # Verify secret
        if not self._verify_hash(secret, entry.secret_hash):
            raise AuthenticationError("Invalid API key")

        return SelfHostedAuthContext(
            silo_id=entry.silo_id,
            user_id=key_id,
            scopes=set(entry.scopes),
            strategy="api_key",
        )
```

- [ ] **Step 4: Update auth module exports**

In `src/context_service/api/auth/__init__.py`, add:

```python
from context_service.api.auth.api_key import APIKeyAuthStrategy
```

And update `__all__` to include `"APIKeyAuthStrategy"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/auth/test_api_key.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/api/auth/ tests/api/auth/test_api_key.py
git commit -m "feat(auth): add API key authentication strategy"
```

---

## Task 6: Integrate Self-Hosted Auth into deps.py

**Files:**
- Modify: `src/context_service/api/deps.py`
- Modify: `src/context_service/api/auth/__init__.py`
- Test: `tests/api/test_deps.py`

- [ ] **Step 1: Write failing test for self-hosted auth resolution**

```python
# tests/api/test_deps.py (append or create)
"""Tests for auth dependency resolution."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def self_hosted_app():
    """Create app with self-hosted auth enabled."""
    yaml_content = """
strategy: proxy
proxy:
  headers:
    silo_id: X-Silo-Id
    user_id: X-User-Id
    scopes: X-Auth-Scopes
  require_https: false
  trusted_source_ips: []
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        
        with patch.dict("os.environ", {
            "SELF_HOSTED_AUTH": "true",
            "AUTH_CONFIG_PATH": f.name,
            "AUTH_ENABLED": "true",
        }):
            from context_service.config.settings import Settings
            # Force reload settings
            with patch("context_service.api.deps.get_settings") as mock_settings:
                settings = Settings()
                settings.self_hosted_auth = True
                settings.auth_config_path = f.name
                settings.auth_enabled = True
                mock_settings.return_value = settings
                
                app = FastAPI()
                
                from context_service.api.deps import get_auth_context
                
                @app.get("/test")
                async def test_endpoint(auth=Depends(get_auth_context)):
                    return {"silo_id": auth.silo_id}
                
                yield TestClient(app)


def test_self_hosted_proxy_auth(self_hosted_app) -> None:
    """Self-hosted proxy auth extracts silo from header."""
    response = self_hosted_app.get(
        "/test",
        headers={"X-Silo-Id": "engineering"},
    )
    assert response.status_code == 200
    assert response.json()["silo_id"] == "engineering"


def test_self_hosted_missing_silo_returns_401(self_hosted_app) -> None:
    """Missing silo header returns 401."""
    response = self_hosted_app.get("/test")
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_deps.py -v`
Expected: FAIL (no self-hosted auth path in deps.py)

- [ ] **Step 3: Create auth resolver factory**

```python
# src/context_service/api/auth/__init__.py (replace content)
"""Self-hosted authentication strategies."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from context_service.api.auth.api_key import APIKeyAuthStrategy
from context_service.api.auth.config import AuthConfig, load_auth_config
from context_service.api.auth.context import SelfHostedAuthContext
from context_service.api.auth.jwt import JWTAuthStrategy
from context_service.api.auth.proxy import AuthenticationError, ProxyAuthStrategy

if TYPE_CHECKING:
    from fastapi import Request

__all__ = [
    "APIKeyAuthStrategy",
    "AuthConfig",
    "AuthenticationError",
    "JWTAuthStrategy",
    "load_auth_config",
    "ProxyAuthStrategy",
    "SelfHostedAuthContext",
    "get_auth_resolver",
]


from functools import lru_cache


@lru_cache(maxsize=1)
def _build_resolver(config_path: str) -> "AuthResolver":
    """Build auth resolver from config file (cached)."""
    config = load_auth_config(Path(config_path))

    if config.strategy == "proxy" and config.proxy:
        strategy = ProxyAuthStrategy(config.proxy)
    elif config.strategy == "jwt" and config.jwt:
        strategy = JWTAuthStrategy(config.jwt)
    elif config.strategy == "api_key" and config.api_key:
        strategy = APIKeyAuthStrategy(config.api_key)
    else:
        raise ValueError(f"Invalid auth config: strategy={config.strategy}")

    return AuthResolver(strategy)


def get_auth_resolver(config_path: str) -> "AuthResolver":
    """Get auth resolver (uses lru_cache internally)."""
    return _build_resolver(config_path)


class AuthResolver:
    """Resolves auth context from request."""

    def __init__(self, strategy: ProxyAuthStrategy | JWTAuthStrategy | APIKeyAuthStrategy):
        self.strategy = strategy

    async def resolve(self, request: Request) -> SelfHostedAuthContext:
        """Resolve auth context from request."""
        return await self.strategy.authenticate(request)
```

- [ ] **Step 4: Update deps.py with self-hosted auth path**

In `src/context_service/api/deps.py`, add imports and update the function:

```python
# Add imports at top (after existing imports)
from context_service.api.auth import AuthenticationError, SelfHostedAuthContext, get_auth_resolver
from context_service.config.settings import get_settings

# Add module-level variable (if not already present)
_dev_bypass_logged = False

# Update get_auth_context function
async def get_auth_context(request: Request) -> AuthContext | SelfHostedAuthContext:
    """Resolve the auth context for a request.

    Returns a dev AuthContext when AUTH_ENABLED=false.
    Uses self-hosted auth when SELF_HOSTED_AUTH=true.
    Otherwise validates the Bearer token via WorkOS.
    """
    global _dev_bypass_logged

    settings = get_settings()

    if not settings.auth_enabled:
        if not _dev_bypass_logged:
            logger.info("auth.dev_bypass_active", reason="AUTH_ENABLED=false")
            _dev_bypass_logged = True
        return AuthContext(
            org_id=settings.dev_org_id,
            user_id=settings.dev_user_id,
            email=None,
            is_dev=True,
        )

    # Self-hosted auth path
    if settings.self_hosted_auth:
        try:
            resolver = get_auth_resolver(settings.auth_config_path)
            return await resolver.resolve(request)
        except AuthenticationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        except FileNotFoundError as exc:
            logger.error("auth.config_not_found", path=settings.auth_config_path)
            raise HTTPException(status_code=503, detail="Auth config not found") from exc

    # WorkOS auth path (existing)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing or malformed Authorization header")

    token = auth_header.removeprefix("Bearer ")

    from context_service.auth import workos_client

    try:
        return await workos_client.verify_session(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_deps.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/api/auth/ src/context_service/api/deps.py tests/api/test_deps.py
git commit -m "feat(auth): integrate self-hosted auth into request pipeline"
```

---

## Task 7: Response Envelope Models

**Files:**
- Create: `src/context_service/api/v1/__init__.py`
- Create: `src/context_service/api/v1/schemas.py`
- Test: `tests/api/v1/test_schemas.py`

- [ ] **Step 1: Create v1 module**

```python
# src/context_service/api/v1/__init__.py
"""v1 REST API."""
```

- [ ] **Step 2: Write failing test for envelope schemas**

```python
# tests/api/v1/test_schemas.py
"""Tests for v1 API schemas."""

from __future__ import annotations


def test_success_envelope() -> None:
    """Success envelope wraps data with meta."""
    from context_service.api.v1.schemas import SuccessEnvelope, ResponseMeta
    
    envelope = SuccessEnvelope(
        data={"node_id": "abc123"},
        meta=ResponseMeta(request_id="req_xyz", took_ms=42),
    )
    
    dumped = envelope.model_dump()
    assert dumped["data"]["node_id"] == "abc123"
    assert dumped["meta"]["request_id"] == "req_xyz"
    assert dumped["meta"]["took_ms"] == 42


def test_list_envelope_with_pagination() -> None:
    """List envelope includes pagination."""
    from context_service.api.v1.schemas import ListEnvelope, ResponseMeta, Pagination
    
    envelope = ListEnvelope(
        data=[{"node_id": "a"}, {"node_id": "b"}],
        meta=ResponseMeta(
            request_id="req_xyz",
            took_ms=100,
            pagination=Pagination(cursor="abc", has_more=True),
        ),
    )
    
    dumped = envelope.model_dump()
    assert len(dumped["data"]) == 2
    assert dumped["meta"]["pagination"]["cursor"] == "abc"
    assert dumped["meta"]["pagination"]["has_more"] is True


def test_error_envelope() -> None:
    """Error envelope with code and details."""
    from context_service.api.v1.schemas import ErrorEnvelope, ErrorBody, ResponseMeta
    
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code="validation_error",
            message="evidence is required",
            details={"field": "evidence"},
        ),
        meta=ResponseMeta(request_id="req_xyz", took_ms=5),
    )
    
    dumped = envelope.model_dump()
    assert dumped["error"]["code"] == "validation_error"
    assert dumped["error"]["details"]["field"] == "evidence"


def test_batch_envelope() -> None:
    """Batch response with succeeded and failed."""
    from context_service.api.v1.schemas import (
        BatchEnvelope,
        BatchResult,
        BatchSuccess,
        BatchFailure,
        ErrorBody,
        ResponseMeta,
    )
    
    envelope = BatchEnvelope(
        data=BatchResult(
            succeeded=[BatchSuccess(index=0, node_id="abc")],
            failed=[
                BatchFailure(
                    index=1,
                    error=ErrorBody(code="validation_error", message="bad"),
                )
            ],
        ),
        meta=ResponseMeta(request_id="req_xyz", took_ms=200),
    )
    
    dumped = envelope.model_dump()
    assert dumped["data"]["succeeded"][0]["node_id"] == "abc"
    assert dumped["data"]["failed"][0]["index"] == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/api/v1/test_schemas.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 4: Implement envelope schemas**

```python
# src/context_service/api/v1/schemas.py
"""Shared request/response schemas for v1 API."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Pagination(BaseModel):
    """Cursor-based pagination info."""

    cursor: str | None = None
    has_more: bool = False


class ResponseMeta(BaseModel):
    """Response metadata."""

    request_id: str
    took_ms: int
    pagination: Pagination | None = None


class SuccessEnvelope(BaseModel, Generic[T]):
    """Standard success response envelope."""

    data: T
    meta: ResponseMeta


class ListEnvelope(BaseModel, Generic[T]):
    """List response envelope with pagination."""

    data: list[T]
    meta: ResponseMeta


class ErrorBody(BaseModel):
    """Error details."""

    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(BaseModel):
    """Error response envelope."""

    error: ErrorBody
    meta: ResponseMeta


class BatchSuccess(BaseModel):
    """Single successful item in batch."""

    index: int
    node_id: str


class BatchFailure(BaseModel):
    """Single failed item in batch."""

    index: int
    error: ErrorBody


class BatchResult(BaseModel):
    """Batch operation result."""

    succeeded: list[BatchSuccess] = Field(default_factory=list)
    failed: list[BatchFailure] = Field(default_factory=list)


class BatchEnvelope(BaseModel):
    """Batch response envelope."""

    data: BatchResult
    meta: ResponseMeta


# --- Request schemas ---


class RememberRequest(BaseModel):
    """Request to store an observation (memory layer)."""

    content: str = Field(..., min_length=1, max_length=100000)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LearnRequest(BaseModel):
    """Request to store a claim with evidence (knowledge layer)."""

    content: str = Field(..., min_length=1, max_length=100000)
    evidence: list[str] = Field(..., min_length=1, description="Evidence URIs or node IDs")
    source_tier: str | None = Field(
        default=None,
        pattern="^(authoritative|validated|community)$",
    )
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchRememberRequest(BaseModel):
    """Batch remember request."""

    items: list[RememberRequest] = Field(..., min_length=1, max_length=1000)


class BatchLearnRequest(BaseModel):
    """Batch learn request."""

    items: list[LearnRequest] = Field(..., min_length=1, max_length=1000)


class BatchGetRequest(BaseModel):
    """Request to fetch multiple nodes by ID."""

    node_ids: list[str] = Field(..., min_length=1, max_length=1000)


# --- Response schemas ---


class NodeResponse(BaseModel):
    """Single node in response."""

    node_id: str
    layer: str
    content: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    valid_from: str | None = None
    valid_to: str | None = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/v1/test_schemas.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/api/v1/ tests/api/v1/
git commit -m "feat(api): add v1 response envelope schemas"
```

---

## Task 8: Memory Layer Endpoints

**Files:**
- Create: `src/context_service/api/v1/memory.py`
- Test: `tests/api/v1/test_memory.py`

- [ ] **Step 1: Write failing test for memory endpoints**

```python
# tests/api/v1/test_memory.py
"""Tests for memory layer endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create test app with memory router."""
    from context_service.api.v1.memory import router
    from context_service.api.v1.schemas import SuccessEnvelope, NodeResponse
    
    app = FastAPI()
    app.include_router(router, prefix="/v1/memory")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def mock_auth():
    """Mock auth context."""
    from context_service.api.auth.context import SelfHostedAuthContext
    ctx = SelfHostedAuthContext(
        silo_id="test-silo",
        scopes={"read", "write"},
        strategy="proxy",
    )
    with patch("context_service.api.v1.memory.get_auth_context", return_value=ctx):
        yield ctx


@pytest.fixture
def mock_store():
    """Mock graph store."""
    store = AsyncMock()
    with patch("context_service.api.v1.memory.get_store", return_value=store):
        yield store


def test_remember_creates_node(client, mock_auth, mock_store) -> None:
    """POST /v1/memory/ creates observation node."""
    import uuid
    node_id = uuid.uuid4()
    mock_store.upsert_node = AsyncMock(return_value=None)
    
    with patch("uuid.uuid4", return_value=node_id):
        response = client.post(
            "/v1/memory/",
            json={"content": "Test observation", "tags": ["test"]},
            headers={"X-Silo-Id": "test-silo"},
        )
    
    assert response.status_code == 201
    data = response.json()
    assert data["data"]["node_id"] == str(node_id)
    assert data["data"]["layer"] == "memory"
    assert "meta" in data


def test_remember_requires_write_scope(client, mock_store) -> None:
    """POST /v1/memory/ requires write scope."""
    from context_service.api.auth.context import SelfHostedAuthContext
    ctx = SelfHostedAuthContext(
        silo_id="test-silo",
        scopes={"read"},  # No write scope
        strategy="proxy",
    )
    with patch("context_service.api.v1.memory.get_auth_context", return_value=ctx):
        response = client.post(
            "/v1/memory/",
            json={"content": "Test"},
            headers={"X-Silo-Id": "test-silo"},
        )
    
    assert response.status_code == 403


def test_get_memory_by_id(client, mock_auth, mock_store) -> None:
    """GET /v1/memory/{node_id} returns node."""
    from context_service.engine.models import Node
    from datetime import datetime, UTC
    import uuid
    
    node_id = uuid.uuid4()
    mock_store.get_node = AsyncMock(return_value=Node(
        node_id=node_id,
        silo_id="test-silo",
        layer="memory",
        node_type="Observation",
        content="Test content",
        created_at=datetime.now(UTC),
        valid_from=datetime.now(UTC),
    ))
    
    response = client.get(
        f"/v1/memory/{node_id}",
        headers={"X-Silo-Id": "test-silo"},
    )
    
    assert response.status_code == 200
    assert response.json()["data"]["content"] == "Test content"


def test_get_memory_not_found(client, mock_auth, mock_store) -> None:
    """GET /v1/memory/{node_id} returns 404 if not found."""
    import uuid
    mock_store.get_node = AsyncMock(return_value=None)
    
    response = client.get(
        f"/v1/memory/{uuid.uuid4()}",
        headers={"X-Silo-Id": "test-silo"},
    )
    
    assert response.status_code == 404


def test_delete_memory_soft_deletes(client, mock_auth, mock_store) -> None:
    """DELETE /v1/memory/{node_id} soft-deletes node."""
    import uuid
    node_id = uuid.uuid4()
    mock_store.delete_node = AsyncMock(return_value=True)
    
    response = client.delete(
        f"/v1/memory/{node_id}",
        headers={"X-Silo-Id": "test-silo"},
    )
    
    assert response.status_code == 200
    mock_store.delete_node.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/v1/test_memory.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement memory endpoints**

```python
# src/context_service/api/v1/memory.py
"""Memory layer REST endpoints."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from context_service.api.auth.context import SelfHostedAuthContext
from context_service.api.v1.schemas import (
    BatchEnvelope,
    BatchFailure,
    BatchGetRequest,
    BatchRememberRequest,
    BatchResult,
    BatchSuccess,
    ErrorBody,
    NodeResponse,
    RememberRequest,
    ResponseMeta,
    SuccessEnvelope,
)

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["memory"])


def _generate_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


async def get_auth_context(request: Request) -> SelfHostedAuthContext:
    """Dependency to get auth context."""
    from context_service.api.deps import get_auth_context as _get_auth
    return await _get_auth(request)


async def get_store(request: Request) -> "HyperGraphStore":
    """Dependency to get graph store."""
    return request.app.state.memgraph


def require_scope(scope: str):
    """Dependency factory to require a scope."""
    async def _check(auth: SelfHostedAuthContext = Depends(get_auth_context)):
        if not auth.has_scope(scope):
            raise HTTPException(
                status_code=403,
                detail=f"Missing required scope: {scope}",
            )
        return auth
    return _check


@router.post(
    "/",
    response_model=SuccessEnvelope[NodeResponse],
    status_code=201,
)
async def remember(
    body: RememberRequest,
    request: Request,
    auth: Annotated[SelfHostedAuthContext, Depends(require_scope("write"))],
    store: Annotated["HyperGraphStore", Depends(get_store)],
) -> SuccessEnvelope[NodeResponse]:
    """Store an observation (memory layer)."""
    start = time.monotonic()
    request_id = _generate_request_id()

    from context_service.engine.models import Node

    node_id = uuid.uuid4()
    now = datetime.now(UTC)

    # Store layer, tags, metadata in properties dict (actual Node model structure)
    properties = {
        "layer": "memory",
        "tags": body.tags,
        **body.metadata,
    }

    node = Node(
        id=node_id,
        silo_id=uuid.UUID(auth.silo_id) if isinstance(auth.silo_id, str) else auth.silo_id,
        type="Observation",
        content=body.content,
        properties=properties,
        created_at=now,
        valid_from=now,
    )

    await store.upsert_node(node)

    logger.info(
        "memory.remember",
        node_id=str(node_id),
        silo_id=auth.silo_id,
        request_id=request_id,
    )

    took_ms = int((time.monotonic() - start) * 1000)

    return SuccessEnvelope(
        data=NodeResponse(
            node_id=str(node_id),
            layer="memory",
            content=body.content,
            tags=body.tags,
            metadata=body.metadata,
            created_at=now.isoformat(),
            valid_from=now.isoformat(),
        ),
        meta=ResponseMeta(request_id=request_id, took_ms=took_ms),
    )


@router.get(
    "/{node_id}",
    response_model=SuccessEnvelope[NodeResponse],
)
async def get_memory(
    node_id: uuid.UUID,
    request: Request,
    auth: Annotated[SelfHostedAuthContext, Depends(require_scope("read"))],
    store: Annotated["HyperGraphStore", Depends(get_store)],
) -> SuccessEnvelope[NodeResponse]:
    """Fetch a memory node by ID."""
    start = time.monotonic()
    request_id = _generate_request_id()

    node = await store.get_node(node_id, auth.silo_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    took_ms = int((time.monotonic() - start) * 1000)

    return SuccessEnvelope(
        data=NodeResponse(
            node_id=str(node.node_id),
            layer=node.layer,
            content=node.content,
            tags=node.tags or [],
            metadata=node.metadata or {},
            created_at=node.created_at.isoformat(),
            valid_from=node.valid_from.isoformat() if node.valid_from else None,
            valid_to=node.valid_to.isoformat() if node.valid_to else None,
        ),
        meta=ResponseMeta(request_id=request_id, took_ms=took_ms),
    )


@router.delete(
    "/{node_id}",
    response_model=SuccessEnvelope[dict],
)
async def delete_memory(
    node_id: uuid.UUID,
    request: Request,
    auth: Annotated[SelfHostedAuthContext, Depends(require_scope("write"))],
    store: Annotated["HyperGraphStore", Depends(get_store)],
) -> SuccessEnvelope[dict]:
    """Soft-delete a memory node."""
    start = time.monotonic()
    request_id = _generate_request_id()

    deleted = await store.delete_node(node_id, auth.silo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Node not found")

    logger.info(
        "memory.delete",
        node_id=str(node_id),
        silo_id=auth.silo_id,
        request_id=request_id,
    )

    took_ms = int((time.monotonic() - start) * 1000)

    return SuccessEnvelope(
        data={"deleted": True, "node_id": str(node_id)},
        meta=ResponseMeta(request_id=request_id, took_ms=took_ms),
    )


@router.post(
    "/batch",
    response_model=BatchEnvelope,
    status_code=201,
)
async def batch_remember(
    body: BatchRememberRequest,
    request: Request,
    auth: Annotated[SelfHostedAuthContext, Depends(require_scope("write"))],
    store: Annotated["HyperGraphStore", Depends(get_store)],
) -> BatchEnvelope:
    """Batch store observations."""
    start = time.monotonic()
    request_id = _generate_request_id()

    from context_service.engine.models import Node

    succeeded = []
    failed = []
    now = datetime.now(UTC)

    for idx, item in enumerate(body.items):
        try:
            node_id = uuid.uuid4()
            node = Node(
                node_id=node_id,
                silo_id=auth.silo_id,
                layer="memory",
                node_type="Observation",
                content=item.content,
                tags=item.tags,
                metadata=item.metadata,
                created_at=now,
                valid_from=now,
            )
            await store.upsert_node(node)
            succeeded.append(BatchSuccess(index=idx, node_id=str(node_id)))
        except Exception as e:
            failed.append(BatchFailure(
                index=idx,
                error=ErrorBody(code="internal_error", message=str(e)),
            ))

    took_ms = int((time.monotonic() - start) * 1000)

    return BatchEnvelope(
        data=BatchResult(succeeded=succeeded, failed=failed),
        meta=ResponseMeta(request_id=request_id, took_ms=took_ms),
    )


@router.post(
    "/batch-get",
    response_model=SuccessEnvelope[list[NodeResponse]],
)
async def batch_get_memory(
    body: BatchGetRequest,
    request: Request,
    auth: Annotated[SelfHostedAuthContext, Depends(require_scope("read"))],
    store: Annotated["HyperGraphStore", Depends(get_store)],
) -> SuccessEnvelope[list[NodeResponse]]:
    """Fetch multiple memory nodes by ID."""
    start = time.monotonic()
    request_id = _generate_request_id()

    node_ids = [uuid.UUID(nid) for nid in body.node_ids]
    nodes = await store.batch_get_nodes(node_ids, auth.silo_id)

    responses = []
    for node in nodes.values():
        responses.append(NodeResponse(
            node_id=str(node.node_id),
            layer=node.layer,
            content=node.content,
            tags=node.tags or [],
            metadata=node.metadata or {},
            created_at=node.created_at.isoformat(),
            valid_from=node.valid_from.isoformat() if node.valid_from else None,
            valid_to=node.valid_to.isoformat() if node.valid_to else None,
        ))

    took_ms = int((time.monotonic() - start) * 1000)

    return SuccessEnvelope(
        data=responses,
        meta=ResponseMeta(request_id=request_id, took_ms=took_ms),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/v1/test_memory.py -v`
Expected: PASS (some tests may need mock adjustments)

- [ ] **Step 5: Commit**

```bash
git add src/context_service/api/v1/memory.py tests/api/v1/test_memory.py
git commit -m "feat(api): add memory layer REST endpoints"
```

---

## Task 9: Knowledge Layer Endpoints

**Files:**
- Create: `src/context_service/api/v1/knowledge.py`
- Test: `tests/api/v1/test_knowledge.py`

- [ ] **Step 1: Write failing test for knowledge endpoints**

```python
# tests/api/v1/test_knowledge.py
"""Tests for knowledge layer endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    from context_service.api.v1.knowledge import router
    app = FastAPI()
    app.include_router(router, prefix="/v1/knowledge")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def mock_auth():
    from context_service.api.auth.context import SelfHostedAuthContext
    ctx = SelfHostedAuthContext(
        silo_id="test-silo",
        scopes={"read", "write"},
        strategy="proxy",
    )
    with patch("context_service.api.v1.knowledge.get_auth_context", return_value=ctx):
        yield ctx


@pytest.fixture
def mock_store():
    store = AsyncMock()
    with patch("context_service.api.v1.knowledge.get_store", return_value=store):
        yield store


def test_learn_creates_claim(client, mock_auth, mock_store) -> None:
    """POST /v1/knowledge/ creates claim with evidence."""
    import uuid
    node_id = uuid.uuid4()
    mock_store.upsert_node = AsyncMock(return_value=None)
    
    with patch("uuid.uuid4", return_value=node_id):
        response = client.post(
            "/v1/knowledge/",
            json={
                "content": "Python is a programming language",
                "evidence": ["https://python.org"],
                "source_tier": "authoritative",
            },
            headers={"X-Silo-Id": "test-silo"},
        )
    
    assert response.status_code == 201
    data = response.json()
    assert data["data"]["layer"] == "knowledge"


def test_learn_requires_evidence(client, mock_auth, mock_store) -> None:
    """POST /v1/knowledge/ requires evidence field."""
    response = client.post(
        "/v1/knowledge/",
        json={"content": "Test claim"},  # Missing evidence
        headers={"X-Silo-Id": "test-silo"},
    )
    
    assert response.status_code == 422  # Validation error


def test_learn_validates_source_tier(client, mock_auth, mock_store) -> None:
    """POST /v1/knowledge/ validates source_tier enum."""
    response = client.post(
        "/v1/knowledge/",
        json={
            "content": "Test claim",
            "evidence": ["http://example.com"],
            "source_tier": "invalid_tier",
        },
        headers={"X-Silo-Id": "test-silo"},
    )
    
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/v1/test_knowledge.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement knowledge endpoints**

```python
# src/context_service/api/v1/knowledge.py
"""Knowledge layer REST endpoints."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from context_service.api.auth.context import SelfHostedAuthContext
from context_service.api.v1.schemas import (
    BatchEnvelope,
    BatchFailure,
    BatchGetRequest,
    BatchLearnRequest,
    BatchResult,
    BatchSuccess,
    ErrorBody,
    LearnRequest,
    NodeResponse,
    ResponseMeta,
    SuccessEnvelope,
)

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["knowledge"])


def _generate_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


async def get_auth_context(request: Request) -> SelfHostedAuthContext:
    from context_service.api.deps import get_auth_context as _get_auth
    return await _get_auth(request)


async def get_store(request: Request) -> "HyperGraphStore":
    return request.app.state.memgraph


def require_scope(scope: str):
    async def _check(auth: SelfHostedAuthContext = Depends(get_auth_context)):
        if not auth.has_scope(scope):
            raise HTTPException(status_code=403, detail=f"Missing required scope: {scope}")
        return auth
    return _check


@router.post(
    "/",
    response_model=SuccessEnvelope[NodeResponse],
    status_code=201,
)
async def learn(
    body: LearnRequest,
    request: Request,
    auth: Annotated[SelfHostedAuthContext, Depends(require_scope("write"))],
    store: Annotated["HyperGraphStore", Depends(get_store)],
) -> SuccessEnvelope[NodeResponse]:
    """Store a claim with evidence (knowledge layer)."""
    start = time.monotonic()
    request_id = _generate_request_id()

    from context_service.engine.models import Node

    node_id = uuid.uuid4()
    now = datetime.now(UTC)

    # Include evidence and source_tier in metadata
    metadata = body.metadata.copy()
    metadata["evidence"] = body.evidence
    if body.source_tier:
        metadata["source_tier"] = body.source_tier

    node = Node(
        node_id=node_id,
        silo_id=auth.silo_id,
        layer="knowledge",
        node_type="Claim",
        content=body.content,
        tags=body.tags,
        metadata=metadata,
        created_at=now,
        valid_from=now,
    )

    await store.upsert_node(node)

    logger.info(
        "knowledge.learn",
        node_id=str(node_id),
        silo_id=auth.silo_id,
        evidence_count=len(body.evidence),
        source_tier=body.source_tier,
        request_id=request_id,
    )

    took_ms = int((time.monotonic() - start) * 1000)

    return SuccessEnvelope(
        data=NodeResponse(
            node_id=str(node_id),
            layer="knowledge",
            content=body.content,
            tags=body.tags,
            metadata=metadata,
            created_at=now.isoformat(),
            valid_from=now.isoformat(),
        ),
        meta=ResponseMeta(request_id=request_id, took_ms=took_ms),
    )


@router.get(
    "/{node_id}",
    response_model=SuccessEnvelope[NodeResponse],
)
async def get_knowledge(
    node_id: uuid.UUID,
    request: Request,
    auth: Annotated[SelfHostedAuthContext, Depends(require_scope("read"))],
    store: Annotated["HyperGraphStore", Depends(get_store)],
) -> SuccessEnvelope[NodeResponse]:
    """Fetch a knowledge node by ID."""
    start = time.monotonic()
    request_id = _generate_request_id()

    node = await store.get_node(node_id, auth.silo_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    took_ms = int((time.monotonic() - start) * 1000)

    return SuccessEnvelope(
        data=NodeResponse(
            node_id=str(node.node_id),
            layer=node.layer,
            content=node.content,
            tags=node.tags or [],
            metadata=node.metadata or {},
            created_at=node.created_at.isoformat(),
            valid_from=node.valid_from.isoformat() if node.valid_from else None,
            valid_to=node.valid_to.isoformat() if node.valid_to else None,
        ),
        meta=ResponseMeta(request_id=request_id, took_ms=took_ms),
    )


@router.delete(
    "/{node_id}",
    response_model=SuccessEnvelope[dict],
)
async def delete_knowledge(
    node_id: uuid.UUID,
    request: Request,
    auth: Annotated[SelfHostedAuthContext, Depends(require_scope("write"))],
    store: Annotated["HyperGraphStore", Depends(get_store)],
) -> SuccessEnvelope[dict]:
    """Soft-delete a knowledge node."""
    start = time.monotonic()
    request_id = _generate_request_id()

    deleted = await store.delete_node(node_id, auth.silo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Node not found")

    logger.info(
        "knowledge.delete",
        node_id=str(node_id),
        silo_id=auth.silo_id,
        request_id=request_id,
    )

    took_ms = int((time.monotonic() - start) * 1000)

    return SuccessEnvelope(
        data={"deleted": True, "node_id": str(node_id)},
        meta=ResponseMeta(request_id=request_id, took_ms=took_ms),
    )


@router.post(
    "/batch",
    response_model=BatchEnvelope,
    status_code=201,
)
async def batch_learn(
    body: BatchLearnRequest,
    request: Request,
    auth: Annotated[SelfHostedAuthContext, Depends(require_scope("write"))],
    store: Annotated["HyperGraphStore", Depends(get_store)],
) -> BatchEnvelope:
    """Batch store claims with evidence."""
    start = time.monotonic()
    request_id = _generate_request_id()

    from context_service.engine.models import Node

    succeeded = []
    failed = []
    now = datetime.now(UTC)

    for idx, item in enumerate(body.items):
        try:
            node_id = uuid.uuid4()
            metadata = item.metadata.copy()
            metadata["evidence"] = item.evidence
            if item.source_tier:
                metadata["source_tier"] = item.source_tier

            node = Node(
                node_id=node_id,
                silo_id=auth.silo_id,
                layer="knowledge",
                node_type="Claim",
                content=item.content,
                tags=item.tags,
                metadata=metadata,
                created_at=now,
                valid_from=now,
            )
            await store.upsert_node(node)
            succeeded.append(BatchSuccess(index=idx, node_id=str(node_id)))
        except Exception as e:
            failed.append(BatchFailure(
                index=idx,
                error=ErrorBody(code="internal_error", message=str(e)),
            ))

    took_ms = int((time.monotonic() - start) * 1000)

    return BatchEnvelope(
        data=BatchResult(succeeded=succeeded, failed=failed),
        meta=ResponseMeta(request_id=request_id, took_ms=took_ms),
    )


@router.post(
    "/batch-get",
    response_model=SuccessEnvelope[list[NodeResponse]],
)
async def batch_get_knowledge(
    body: BatchGetRequest,
    request: Request,
    auth: Annotated[SelfHostedAuthContext, Depends(require_scope("read"))],
    store: Annotated["HyperGraphStore", Depends(get_store)],
) -> SuccessEnvelope[list[NodeResponse]]:
    """Fetch multiple knowledge nodes by ID."""
    start = time.monotonic()
    request_id = _generate_request_id()

    node_ids = [uuid.UUID(nid) for nid in body.node_ids]
    nodes = await store.batch_get_nodes(node_ids, auth.silo_id)

    responses = []
    for node in nodes.values():
        responses.append(NodeResponse(
            node_id=str(node.node_id),
            layer=node.layer,
            content=node.content,
            tags=node.tags or [],
            metadata=node.metadata or {},
            created_at=node.created_at.isoformat(),
            valid_from=node.valid_from.isoformat() if node.valid_from else None,
            valid_to=node.valid_to.isoformat() if node.valid_to else None,
        ))

    took_ms = int((time.monotonic() - start) * 1000)

    return SuccessEnvelope(
        data=responses,
        meta=ResponseMeta(request_id=request_id, took_ms=took_ms),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/v1/test_knowledge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/api/v1/knowledge.py tests/api/v1/test_knowledge.py
git commit -m "feat(api): add knowledge layer REST endpoints"
```

---

## Task 10: Mount v1 Router in App

**Files:**
- Modify: `src/context_service/api/app.py`
- Test: Integration test

- [ ] **Step 1: Create v1 router aggregator**

```python
# src/context_service/api/v1/__init__.py (update)
"""v1 REST API."""

from fastapi import APIRouter

from context_service.api.v1.memory import router as memory_router
from context_service.api.v1.knowledge import router as knowledge_router

router = APIRouter(prefix="/v1")
router.include_router(memory_router, prefix="/memory")
router.include_router(knowledge_router, prefix="/knowledge")
```

- [ ] **Step 2: Mount in app.py**

In `src/context_service/api/app.py`, add after the existing router includes:

```python
# Add import at top
from context_service.api.v1 import router as v1_router

# Add after other router includes (around line 265)
app.include_router(v1_router)
logger.info("v1_api_mounted", prefix="/v1")
```

- [ ] **Step 3: Run type check**

Run: `uv run mypy src/context_service/api/v1/`
Expected: PASS (no errors)

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/api/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/api/v1/__init__.py src/context_service/api/app.py
git commit -m "feat(api): mount v1 REST router"
```

---

## Summary

This plan implements Phase 1 of the self-hosted REST API:

| Task | Component | Status |
|------|-----------|--------|
| 1 | SELF_HOSTED_AUTH setting | |
| 2 | Auth config loader | |
| 3 | Proxy auth strategy | |
| 4 | JWT auth strategy | |
| 5 | API key auth strategy | |
| 6 | Integrate into deps.py | |
| 7 | Response envelope schemas | |
| 8 | Memory layer endpoints | |
| 9 | Knowledge layer endpoints | |
| 10 | Mount v1 router | |

## Next Phases

- **Phase 2:** Wisdom layer (beliefs, hypotheses lifecycle), Intelligence layer
- **Phase 3:** Graph operations (links, trace), Search (recall)
- **Phase 4:** Admin API (license, silos, config, jobs)
- **Phase 5:** Export/Import, Audit logs, Metrics
- **Phase 6:** Streaming, OpenAPI generation
