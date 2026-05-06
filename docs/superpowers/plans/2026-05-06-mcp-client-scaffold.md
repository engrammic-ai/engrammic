# MCP Client Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the delta-prime/mcp-client repo as a thin MCP proxy to the Delta Prime cloud backend.

**Architecture:** FastMCP server exposing 4 tools (store, recall, link, admin) that forward requests to the backend REST API. Singleton HTTP client with connection pooling, automatic token refresh on 401, and error sanitization. Secure credential storage with file permission checks.

**Tech Stack:** Python 3.12+, FastMCP, httpx, pydantic-settings

---

## File Structure

```
delta-prime/mcp-client/
├── src/
│   └── delta_prime_mcp/
│       ├── __init__.py           # Package metadata, version
│       ├── __main__.py           # Entry point: python -m delta_prime_mcp
│       ├── server.py             # FastMCP server creation and tool registration
│       ├── client.py             # DeltaPrimeClient with singleton httpx, token refresh
│       ├── config.py             # Settings from env vars
│       ├── credentials.py        # Secure credential storage (chmod 600)
│       ├── errors.py             # DeltaPrimeError, error sanitization
│       └── tools/
│           ├── __init__.py       # Tool registration helper
│           ├── context_store.py  # store tool proxy
│           ├── context_recall.py # recall tool proxy
│           ├── context_link.py   # link tool proxy
│           └── context_admin.py  # admin tool proxy
├── tests/
│   ├── __init__.py
│   ├── conftest.py               # Fixtures: mock backend, temp credentials
│   ├── test_client.py            # HTTP client tests
│   ├── test_credentials.py       # Credential storage tests
│   ├── test_errors.py            # Error sanitization tests
│   └── test_tools.py             # Tool proxy integration tests
├── .env.example
├── .gitignore
├── pyproject.toml
├── README.md
└── LICENSE
```

---

### Task 1: Initialize Repository

**Files:**
- Create: `../mcp-client/.gitignore`
- Create: `../mcp-client/pyproject.toml`
- Create: `../mcp-client/README.md`
- Create: `../mcp-client/LICENSE`
- Create: `../mcp-client/.env.example`

- [ ] **Step 1: Create directory and initialize git**

```bash
mkdir -p /home/novusedge/Projects/delta-prime/mcp-client
cd /home/novusedge/Projects/delta-prime/mcp-client
git init
```

- [ ] **Step 2: Create .gitignore**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
.venv/
venv/
ENV/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/
.nox/

# Type checking
.mypy_cache/

# Environment
.env
.env.local

# Credentials (never commit)
credentials.json
```

- [ ] **Step 3: Create pyproject.toml**

```toml
[project]
name = "delta-prime-mcp"
version = "0.1.0"
description = "MCP server for Delta Prime context management"
readme = "README.md"
license = { text = "Apache-2.0" }
requires-python = ">=3.12"
authors = [{ name = "Delta Prime", email = "hello@deltaprime.ai" }]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3.12",
]
dependencies = [
    "fastmcp>=0.1.0",
    "httpx>=0.27.0",
    "pydantic-settings>=2.0.0",
    "structlog>=24.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-httpx>=0.30.0",
    "ruff>=0.4.0",
    "mypy>=1.10.0",
]

[project.scripts]
delta-prime-mcp = "delta_prime_mcp.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/delta_prime_mcp"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100
select = ["E", "F", "I", "UP", "B", "SIM", "ARG"]

[tool.mypy]
python_version = "3.12"
strict = true
```

- [ ] **Step 4: Create README.md**

```markdown
# Delta Prime MCP Server

MCP server for [Delta Prime](https://deltaprime.ai) context management. Connects AI agents to your Delta Prime workspace.

## Installation

```bash
pip install delta-prime-mcp
```

## Configuration

Set your API key:

```bash
export DELTA_PRIME_API_KEY=dp_xxx
```

Or use OAuth (opens browser on first use):

```bash
delta-prime-mcp login
```

## Usage with Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "delta-prime": {
      "command": "delta-prime-mcp",
      "env": {
        "DELTA_PRIME_API_KEY": "dp_xxx"
      }
    }
  }
}
```

## Self-Hosting

Point to your own backend:

```bash
export DELTA_PRIME_BACKEND_URL=http://localhost:8000
```

## License

Apache 2.0
```

- [ ] **Step 5: Create LICENSE**

```
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
```

- [ ] **Step 6: Create .env.example**

```
# Delta Prime MCP Configuration

# Backend URL (default: Delta Prime Cloud)
DELTA_PRIME_BACKEND_URL=https://api.deltaprime.ai

# API Key (alternative to OAuth)
DELTA_PRIME_API_KEY=

# Credentials file location (default: ~/.delta-prime/credentials.json)
# DELTA_PRIME_CREDENTIALS_PATH=
```

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "chore: initialize mcp-client repository"
```

---

### Task 2: Config Module

**Files:**
- Create: `../mcp-client/src/delta_prime_mcp/__init__.py`
- Create: `../mcp-client/src/delta_prime_mcp/config.py`
- Create: `../mcp-client/tests/__init__.py`
- Create: `../mcp-client/tests/conftest.py`

- [ ] **Step 1: Create package structure**

```bash
mkdir -p /home/novusedge/Projects/delta-prime/mcp-client/src/delta_prime_mcp/tools
mkdir -p /home/novusedge/Projects/delta-prime/mcp-client/tests
```

- [ ] **Step 2: Create src/delta_prime_mcp/__init__.py**

```python
"""Delta Prime MCP Server."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Create src/delta_prime_mcp/config.py**

```python
"""Configuration from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Delta Prime MCP settings."""

    backend_url: str = "https://api.deltaprime.ai"
    api_key: str | None = None
    credentials_path: Path = Path.home() / ".delta-prime" / "credentials.json"

    model_config = SettingsConfigDict(
        env_prefix="DELTA_PRIME_",
        env_file=".env",
        env_file_encoding="utf-8",
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
```

- [ ] **Step 4: Create tests/__init__.py**

```python
"""Tests for delta-prime-mcp."""
```

- [ ] **Step 5: Create tests/conftest.py**

```python
"""Pytest fixtures for delta-prime-mcp tests."""

import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_credentials_dir() -> Generator[Path, None, None]:
    """Temporary directory for credential storage tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_settings(temp_credentials_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure settings to use temp directory."""
    monkeypatch.setenv("DELTA_PRIME_BACKEND_URL", "http://localhost:8000")
    monkeypatch.setenv("DELTA_PRIME_CREDENTIALS_PATH", str(temp_credentials_dir / "creds.json"))
    
    from delta_prime_mcp import config
    config._settings = None
```

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat: add config module with pydantic-settings"
```

---

### Task 3: Error Handling Module

**Files:**
- Create: `../mcp-client/src/delta_prime_mcp/errors.py`
- Create: `../mcp-client/tests/test_errors.py`

- [ ] **Step 1: Write test for error sanitization**

```python
# tests/test_errors.py
"""Tests for error handling and sanitization."""

import pytest

from delta_prime_mcp.errors import (
    DeltaPrimeError,
    sanitize_error_message,
    status_to_error_code,
)


class TestStatusToErrorCode:
    def test_known_status_codes(self) -> None:
        assert status_to_error_code(400) == "invalid_request"
        assert status_to_error_code(401) == "unauthorized"
        assert status_to_error_code(403) == "forbidden"
        assert status_to_error_code(404) == "not_found"
        assert status_to_error_code(429) == "rate_limited"

    def test_unknown_status_code(self) -> None:
        assert status_to_error_code(500) == "internal_error"
        assert status_to_error_code(502) == "internal_error"


class TestSanitizeErrorMessage:
    def test_safe_message_passed_through(self) -> None:
        assert sanitize_error_message(400, "Invalid intent parameter") == "Invalid intent parameter"

    def test_traceback_filtered(self) -> None:
        msg = "Traceback (most recent call last):\n  File \"/app/main.py\""
        result = sanitize_error_message(500, msg)
        assert "Traceback" not in result
        assert result == "An unexpected error occurred"

    def test_internal_paths_filtered(self) -> None:
        msg = "Error in memgraph_store.py line 123"
        result = sanitize_error_message(500, msg)
        assert "memgraph" not in result

    def test_silo_id_filtered(self) -> None:
        msg = "silo_abc123 not found"
        result = sanitize_error_message(404, msg)
        assert "silo_" not in result

    def test_fallback_by_status(self) -> None:
        assert sanitize_error_message(401, None) == "Authentication failed - try logging in again"
        assert sanitize_error_message(429, None) == "Rate limit exceeded - please slow down"


class TestDeltaPrimeError:
    def test_to_dict(self) -> None:
        err = DeltaPrimeError(
            code="invalid_request",
            message="Bad input",
            request_id="req-123",
        )
        assert err.to_dict() == {
            "error": "invalid_request",
            "message": "Bad input",
            "request_id": "req-123",
        }
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/novusedge/Projects/delta-prime/mcp-client
uv run pytest tests/test_errors.py -v
```

Expected: FAIL with import errors

- [ ] **Step 3: Implement errors module**

```python
# src/delta_prime_mcp/errors.py
"""Error handling and sanitization for Delta Prime MCP."""

from typing import Any


class DeltaPrimeError(Exception):
    """Error from Delta Prime backend, sanitized for agent consumption."""

    def __init__(self, code: str, message: str, request_id: str) -> None:
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Return error as dictionary for MCP response."""
        return {
            "error": self.code,
            "message": self.message,
            "request_id": self.request_id,
        }


def status_to_error_code(status: int) -> str:
    """Map HTTP status code to error code."""
    return {
        400: "invalid_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        429: "rate_limited",
    }.get(status, "internal_error")


_FALLBACK_MESSAGES: dict[int, str] = {
    400: "Invalid request parameters",
    401: "Authentication failed - try logging in again",
    403: "Access denied",
    404: "Resource not found",
    429: "Rate limit exceeded - please slow down",
}


_INTERNAL_PATTERNS = [
    "traceback",
    "file \"",
    "line ",
    "memgraph",
    "qdrant",
    "silo_",
    "redis",
    "postgres",
]


def _contains_internal_details(msg: str) -> bool:
    """Check if message contains internal implementation details."""
    lower = msg.lower()
    return any(p in lower for p in _INTERNAL_PATTERNS)


def sanitize_error_message(status: int, message: str | None) -> str:
    """Return a safe error message, stripping internal details."""
    if message and not _contains_internal_details(message):
        return message
    return _FALLBACK_MESSAGES.get(status, "An unexpected error occurred")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_errors.py -v
```

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: add error handling with sanitization"
```

---

### Task 4: Credential Storage Module

**Files:**
- Create: `../mcp-client/src/delta_prime_mcp/credentials.py`
- Create: `../mcp-client/tests/test_credentials.py`

- [ ] **Step 1: Write tests for credential storage**

```python
# tests/test_credentials.py
"""Tests for secure credential storage."""

import json
import stat
from pathlib import Path

import pytest

from delta_prime_mcp.credentials import load_credentials, store_credentials


class TestStoreCredentials:
    def test_creates_parent_directory(self, temp_credentials_dir: Path) -> None:
        creds_path = temp_credentials_dir / "subdir" / "creds.json"
        store_credentials(
            access_token="tok_123",
            refresh_token="ref_456",
            path=creds_path,
        )
        assert creds_path.exists()

    def test_stores_tokens(self, temp_credentials_dir: Path) -> None:
        creds_path = temp_credentials_dir / "creds.json"
        store_credentials(
            access_token="tok_123",
            refresh_token="ref_456",
            path=creds_path,
        )
        data = json.loads(creds_path.read_text())
        assert data["access_token"] == "tok_123"
        assert data["refresh_token"] == "ref_456"
        assert "stored_at" in data

    def test_sets_secure_permissions(self, temp_credentials_dir: Path) -> None:
        creds_path = temp_credentials_dir / "creds.json"
        store_credentials(
            access_token="tok_123",
            refresh_token="ref_456",
            path=creds_path,
        )
        mode = creds_path.stat().st_mode
        assert mode & stat.S_IRWXG == 0  # no group permissions
        assert mode & stat.S_IRWXO == 0  # no other permissions


class TestLoadCredentials:
    def test_returns_none_if_missing(self, temp_credentials_dir: Path) -> None:
        creds_path = temp_credentials_dir / "nonexistent.json"
        result = load_credentials(creds_path)
        assert result is None

    def test_loads_stored_credentials(self, temp_credentials_dir: Path) -> None:
        creds_path = temp_credentials_dir / "creds.json"
        store_credentials("tok_123", "ref_456", creds_path)
        result = load_credentials(creds_path)
        assert result is not None
        assert result["access_token"] == "tok_123"
        assert result["refresh_token"] == "ref_456"

    def test_refuses_insecure_permissions(self, temp_credentials_dir: Path) -> None:
        creds_path = temp_credentials_dir / "creds.json"
        creds_path.write_text('{"access_token": "tok"}')
        creds_path.chmod(0o644)  # world-readable
        result = load_credentials(creds_path)
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_credentials.py -v
```

Expected: FAIL with import errors

- [ ] **Step 3: Implement credentials module**

```python
# src/delta_prime_mcp/credentials.py
"""Secure credential storage for OAuth tokens."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def store_credentials(
    access_token: str,
    refresh_token: str,
    path: Path,
) -> None:
    """Store OAuth credentials securely.

    Creates parent directories if needed. Sets file permissions to 600
    (owner read/write only) to protect tokens.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "stored_at": datetime.now(UTC).isoformat(),
    }

    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)

    logger.info("Credentials stored", path=str(path))


def load_credentials(path: Path) -> dict[str, Any] | None:
    """Load stored credentials if they exist and have secure permissions.

    Returns None if:
    - File doesn't exist
    - File has insecure permissions (group or world readable)
    - File is not valid JSON
    """
    if not path.exists():
        return None

    mode = path.stat().st_mode
    if mode & 0o077:
        logger.warning(
            "Credentials file has insecure permissions, refusing to read",
            path=str(path),
            mode=oct(mode),
        )
        return None

    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load credentials", path=str(path), error=str(e))
        return None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_credentials.py -v
```

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: add secure credential storage with permission checks"
```

---

### Task 5: HTTP Client Module

**Files:**
- Create: `../mcp-client/src/delta_prime_mcp/client.py`
- Create: `../mcp-client/tests/test_client.py`

- [ ] **Step 1: Write tests for HTTP client**

```python
# tests/test_client.py
"""Tests for Delta Prime HTTP client."""

import pytest
from pytest_httpx import HTTPXMock

from delta_prime_mcp.client import DeltaPrimeClient, get_http_client, reset_http_client
from delta_prime_mcp.config import Settings
from delta_prime_mcp.errors import DeltaPrimeError


@pytest.fixture(autouse=True)
def reset_client() -> None:
    """Reset singleton client between tests."""
    reset_http_client()


@pytest.fixture
def settings(temp_credentials_dir) -> Settings:
    return Settings(
        backend_url="https://api.test.com",
        api_key="test_key",
        credentials_path=temp_credentials_dir / "creds.json",
    )


class TestGetHttpClient:
    def test_returns_singleton(self) -> None:
        client1 = get_http_client()
        client2 = get_http_client()
        assert client1 is client2


class TestDeltaPrimeClient:
    async def test_post_success(self, settings: Settings, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="https://api.test.com/v1/context/store",
            json={"node_id": "abc123"},
        )
        client = DeltaPrimeClient(settings)
        result = await client.post("/v1/context/store", {"content": "test"})
        assert result == {"node_id": "abc123"}

    async def test_includes_auth_header(self, settings: Settings, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json={})
        client = DeltaPrimeClient(settings)
        await client.post("/v1/test", {})

        request = httpx_mock.get_request()
        assert request is not None
        assert request.headers["authorization"] == "Bearer test_key"

    async def test_includes_request_id(self, settings: Settings, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json={})
        client = DeltaPrimeClient(settings)
        await client.post("/v1/test", {})

        request = httpx_mock.get_request()
        assert request is not None
        assert "x-request-id" in request.headers

    async def test_raises_sanitized_error_on_failure(
        self, settings: Settings, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            status_code=500,
            json={"message": "Traceback: internal error in memgraph"},
        )
        client = DeltaPrimeClient(settings)

        with pytest.raises(DeltaPrimeError) as exc_info:
            await client.post("/v1/test", {})

        assert exc_info.value.code == "internal_error"
        assert "Traceback" not in exc_info.value.message
        assert "memgraph" not in exc_info.value.message

    async def test_retries_on_401_with_refresh(
        self, settings: Settings, httpx_mock: HTTPXMock, temp_credentials_dir
    ) -> None:
        from delta_prime_mcp.credentials import store_credentials

        store_credentials("old_token", "refresh_123", settings.credentials_path)

        settings_no_key = Settings(
            backend_url="https://api.test.com",
            api_key=None,
            credentials_path=settings.credentials_path,
        )

        httpx_mock.add_response(
            url="https://api.test.com/v1/test",
            status_code=401,
        )
        httpx_mock.add_response(
            url="https://api.test.com/v1/auth/token/refresh",
            json={"access_token": "new_token", "refresh_token": "refresh_456"},
        )
        httpx_mock.add_response(
            url="https://api.test.com/v1/test",
            json={"success": True},
        )

        client = DeltaPrimeClient(settings_no_key)
        result = await client.post("/v1/test", {})

        assert result == {"success": True}
        assert len(httpx_mock.get_requests()) == 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_client.py -v
```

Expected: FAIL with import errors

- [ ] **Step 3: Implement client module**

```python
# src/delta_prime_mcp/client.py
"""HTTP client for Delta Prime backend communication."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import structlog

from delta_prime_mcp.config import Settings
from delta_prime_mcp.credentials import load_credentials, store_credentials
from delta_prime_mcp.errors import (
    DeltaPrimeError,
    sanitize_error_message,
    status_to_error_code,
)

logger = structlog.get_logger(__name__)

_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return singleton HTTP client for connection reuse."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            http2=True,
        )
    return _http_client


def reset_http_client() -> None:
    """Reset the singleton client. For testing only."""
    global _http_client
    _http_client = None


class DeltaPrimeClient:
    """Client for Delta Prime backend API."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.backend_url.rstrip("/")
        self.settings = settings
        self._token: str | None = settings.api_key
        self._refresh_token: str | None = None

        if not self._token:
            self._load_oauth_credentials()

    def _load_oauth_credentials(self) -> None:
        """Load OAuth tokens from credential storage."""
        creds = load_credentials(self.settings.credentials_path)
        if creds:
            self._token = creds.get("access_token")
            self._refresh_token = creds.get("refresh_token")
            logger.debug("Loaded OAuth credentials from storage")

    async def post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """POST request to backend."""
        return await self._request("POST", path, data)

    async def get(self, path: str) -> dict[str, Any]:
        """GET request to backend."""
        return await self._request("GET", path)

    async def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute HTTP request with auth, retry on 401, and error handling."""
        client = get_http_client()
        request_id = str(uuid.uuid4())

        headers = {
            "X-Request-ID": request_id,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        url = f"{self.base_url}{path}"

        resp = await client.request(
            method,
            url,
            json=data if method != "GET" else None,
            headers=headers,
        )

        if resp.status_code == 401 and self._refresh_token:
            logger.debug("Got 401, attempting token refresh")
            if await self._refresh_access_token():
                headers["Authorization"] = f"Bearer {self._token}"
                resp = await client.request(
                    method,
                    url,
                    json=data if method != "GET" else None,
                    headers=headers,
                )

        return self._handle_response(resp, request_id)

    async def _refresh_access_token(self) -> bool:
        """Attempt to refresh the access token. Returns True on success."""
        try:
            client = get_http_client()
            resp = await client.post(
                f"{self.base_url}/v1/auth/token/refresh",
                json={"refresh_token": self._refresh_token},
            )
            if resp.status_code == 200:
                data = resp.json()
                self._token = data["access_token"]
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                store_credentials(
                    self._token,
                    self._refresh_token or "",
                    self.settings.credentials_path,
                )
                logger.info("Successfully refreshed access token")
                return True
        except Exception as e:
            logger.warning("Failed to refresh token", error=str(e))
        return False

    def _handle_response(self, resp: httpx.Response, request_id: str) -> dict[str, Any]:
        """Handle response, sanitizing errors before returning."""
        if resp.status_code >= 400:
            try:
                body = resp.json()
                raw_message = body.get("message")
            except Exception:
                raw_message = resp.text[:500] if resp.text else None

            logger.error(
                "Backend error",
                status=resp.status_code,
                request_id=request_id,
                raw_message=raw_message,
            )

            raise DeltaPrimeError(
                code=status_to_error_code(resp.status_code),
                message=sanitize_error_message(resp.status_code, raw_message),
                request_id=request_id,
            )

        return resp.json()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_client.py -v
```

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: add HTTP client with connection pooling and token refresh"
```

---

### Task 6: MCP Tools

**Files:**
- Create: `../mcp-client/src/delta_prime_mcp/tools/__init__.py`
- Create: `../mcp-client/src/delta_prime_mcp/tools/context_store.py`
- Create: `../mcp-client/src/delta_prime_mcp/tools/context_recall.py`
- Create: `../mcp-client/src/delta_prime_mcp/tools/context_link.py`
- Create: `../mcp-client/src/delta_prime_mcp/tools/context_admin.py`
- Create: `../mcp-client/tests/test_tools.py`

- [ ] **Step 1: Write tests for tools**

```python
# tests/test_tools.py
"""Tests for MCP tool implementations."""

import pytest
from pytest_httpx import HTTPXMock

from delta_prime_mcp.client import reset_http_client
from delta_prime_mcp.config import Settings
from delta_prime_mcp.tools import context_admin, context_link, context_recall, context_store


@pytest.fixture(autouse=True)
def reset_client() -> None:
    reset_http_client()


@pytest.fixture
def settings(temp_credentials_dir, monkeypatch) -> Settings:
    s = Settings(
        backend_url="https://api.test.com",
        api_key="test_key",
        credentials_path=temp_credentials_dir / "creds.json",
    )
    monkeypatch.setattr("delta_prime_mcp.tools.context_store.get_settings", lambda: s)
    monkeypatch.setattr("delta_prime_mcp.tools.context_recall.get_settings", lambda: s)
    monkeypatch.setattr("delta_prime_mcp.tools.context_link.get_settings", lambda: s)
    monkeypatch.setattr("delta_prime_mcp.tools.context_admin.get_settings", lambda: s)
    return s


class TestContextStore:
    async def test_remember(self, settings: Settings, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="https://api.test.com/v1/context/store",
            json={"node_id": "abc123", "layer": "memory"},
        )
        result = await context_store.store(
            intent="remember",
            content="User prefers dark mode",
        )
        assert result["node_id"] == "abc123"
        assert result["layer"] == "memory"

    async def test_assert_with_claims(self, settings: Settings, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="https://api.test.com/v1/context/store",
            json={"node_id": "def456", "layer": "knowledge"},
        )
        result = await context_store.store(
            intent="assert",
            content="The sky is blue",
            claims=[{"subject": "sky", "predicate": "has_color", "object": "blue"}],
        )
        assert result["layer"] == "knowledge"


class TestContextRecall:
    async def test_query(self, settings: Settings, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="https://api.test.com/v1/context/recall",
            json={"nodes": [{"node_id": "abc", "content": "test"}]},
        )
        result = await context_recall.recall(query="dark mode preference")
        assert len(result["nodes"]) == 1

    async def test_fetch_by_ids(self, settings: Settings, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="https://api.test.com/v1/context/recall",
            json={"nodes": [{"node_id": "abc123"}]},
        )
        result = await context_recall.recall(node_ids=["abc123"])
        assert result["nodes"][0]["node_id"] == "abc123"


class TestContextLink:
    async def test_link_nodes(self, settings: Settings, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="https://api.test.com/v1/context/link",
            json={"edge_id": "edge123"},
        )
        result = await context_link.link(
            source_id="node1",
            target_id="node2",
            relation="RELATES_TO",
        )
        assert result["edge_id"] == "edge123"


class TestContextAdmin:
    async def test_whoami(self, settings: Settings, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="https://api.test.com/v1/context/admin",
            json={"org_id": "org123", "user_id": "user456"},
        )
        result = await context_admin.admin(action="whoami")
        assert result["org_id"] == "org123"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tools.py -v
```

Expected: FAIL with import errors

- [ ] **Step 3: Create tools/__init__.py**

```python
# src/delta_prime_mcp/tools/__init__.py
"""MCP tool implementations for Delta Prime."""

from delta_prime_mcp.tools import (
    context_admin,
    context_link,
    context_recall,
    context_store,
)

__all__ = [
    "context_admin",
    "context_link",
    "context_recall",
    "context_store",
]
```

- [ ] **Step 4: Create tools/context_store.py**

```python
# src/delta_prime_mcp/tools/context_store.py
"""MCP tool: context_store - Write to Delta Prime context layers."""

from typing import Any, Literal

from delta_prime_mcp.client import DeltaPrimeClient
from delta_prime_mcp.config import get_settings

_client: DeltaPrimeClient | None = None


def _get_client() -> DeltaPrimeClient:
    global _client
    if _client is None:
        _client = DeltaPrimeClient(get_settings())
    return _client


async def store(
    intent: Literal["remember", "assert", "commit", "reflect"],
    content: str,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    decay_class: str = "standard",
    claims: list[dict[str, Any]] | None = None,
    steps: list[dict[str, Any]] | None = None,
    observation_type: str | None = None,
) -> dict[str, Any]:
    """Store context to Delta Prime.

    Args:
        intent: Type of storage operation
            - remember: Store to memory layer (documents, observations)
            - assert: Store to knowledge layer (claims, facts)
            - commit: Store to wisdom layer (commitments, decisions)
            - reflect: Store to intelligence layer (reasoning chains)
        content: The content to store
        tags: Optional tags for categorization
        metadata: Optional key-value metadata
        decay_class: How quickly content decays (ephemeral, standard, persistent)
        claims: For assert intent, list of SPO claims
        steps: For reflect intent, reasoning chain steps
        observation_type: For remember, type of observation
    """
    client = _get_client()
    payload: dict[str, Any] = {
        "intent": intent,
        "content": content,
    }

    if tags:
        payload["tags"] = tags
    if metadata:
        payload["metadata"] = metadata
    if decay_class != "standard":
        payload["decay_class"] = decay_class
    if claims:
        payload["claims"] = claims
    if steps:
        payload["steps"] = steps
    if observation_type:
        payload["observation_type"] = observation_type

    return await client.post("/v1/context/store", payload)
```

- [ ] **Step 5: Create tools/context_recall.py**

```python
# src/delta_prime_mcp/tools/context_recall.py
"""MCP tool: context_recall - Read from Delta Prime context layers."""

from typing import Any

from delta_prime_mcp.client import DeltaPrimeClient
from delta_prime_mcp.config import get_settings

_client: DeltaPrimeClient | None = None


def _get_client() -> DeltaPrimeClient:
    global _client
    if _client is None:
        _client = DeltaPrimeClient(get_settings())
    return _client


async def recall(
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int = 10,
    as_of: str | None = None,
    include_reflections: bool = False,
    include_steps: bool = False,
) -> dict[str, Any]:
    """Recall context from Delta Prime.

    Args:
        query: Semantic search query (required if node_ids not provided)
        node_ids: Specific node IDs to fetch (required if query not provided)
        depth: Graph traversal depth (0 = no traversal)
        layers: Filter to specific layers (memory, knowledge, wisdom, intelligence)
        top_k: Max results for semantic search
        as_of: ISO timestamp for time-travel queries
        include_reflections: Include meta-observations about nodes
        include_steps: For intelligence layer, include reasoning steps
    """
    client = _get_client()
    payload: dict[str, Any] = {}

    if query:
        payload["query"] = query
    if node_ids:
        payload["node_ids"] = node_ids
    if depth > 0:
        payload["depth"] = depth
    if layers:
        payload["layers"] = layers
    if top_k != 10:
        payload["top_k"] = top_k
    if as_of:
        payload["as_of"] = as_of
    if include_reflections:
        payload["include_reflections"] = include_reflections
    if include_steps:
        payload["include_steps"] = include_steps

    return await client.post("/v1/context/recall", payload)
```

- [ ] **Step 6: Create tools/context_link.py**

```python
# src/delta_prime_mcp/tools/context_link.py
"""MCP tool: context_link - Create relationships between nodes."""

from typing import Any

from delta_prime_mcp.client import DeltaPrimeClient
from delta_prime_mcp.config import get_settings

_client: DeltaPrimeClient | None = None


def _get_client() -> DeltaPrimeClient:
    global _client
    if _client is None:
        _client = DeltaPrimeClient(get_settings())
    return _client


async def link(
    source_id: str,
    target_id: str,
    relation: str,
    metadata: dict[str, Any] | None = None,
    weight: float | None = None,
) -> dict[str, Any]:
    """Create a typed relationship between two nodes.

    Args:
        source_id: Source node ID
        target_id: Target node ID
        relation: Relationship type (e.g., RELATES_TO, SUPPORTS, CONTRADICTS)
        metadata: Optional edge metadata
        weight: Optional relationship strength (0.0-1.0)
    """
    client = _get_client()
    payload: dict[str, Any] = {
        "source_id": source_id,
        "target_id": target_id,
        "relation": relation,
    }

    if metadata:
        payload["metadata"] = metadata
    if weight is not None:
        payload["weight"] = weight

    return await client.post("/v1/context/link", payload)
```

- [ ] **Step 7: Create tools/context_admin.py**

```python
# src/delta_prime_mcp/tools/context_admin.py
"""MCP tool: context_admin - Administrative operations."""

from typing import Any, Literal

from delta_prime_mcp.client import DeltaPrimeClient
from delta_prime_mcp.config import get_settings

_client: DeltaPrimeClient | None = None


def _get_client() -> DeltaPrimeClient:
    global _client
    if _client is None:
        _client = DeltaPrimeClient(get_settings())
    return _client


async def admin(
    action: Literal["whoami", "usage", "provenance", "history"],
    node_id: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Administrative operations for Delta Prime.

    Args:
        action: Operation to perform
            - whoami: Get current user/org info
            - usage: Get usage statistics
            - provenance: Get node provenance (requires node_id)
            - history: Get node edit history (requires node_id)
        node_id: Required for provenance/history actions
        since: ISO timestamp filter for history
    """
    client = _get_client()
    payload: dict[str, Any] = {
        "action": action,
    }

    if node_id:
        payload["node_id"] = node_id
    if since:
        payload["since"] = since

    return await client.post("/v1/context/admin", payload)
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
uv run pytest tests/test_tools.py -v
```

Expected: All tests pass

- [ ] **Step 9: Commit**

```bash
git add .
git commit -m "feat: add MCP tool implementations (store, recall, link, admin)"
```

---

### Task 7: FastMCP Server

**Files:**
- Create: `../mcp-client/src/delta_prime_mcp/server.py`
- Create: `../mcp-client/src/delta_prime_mcp/__main__.py`

- [ ] **Step 1: Create server.py**

```python
# src/delta_prime_mcp/server.py
"""FastMCP server for Delta Prime."""

from typing import Any, Literal

from fastmcp import FastMCP

from delta_prime_mcp.tools import context_admin, context_link, context_recall, context_store


def create_server() -> FastMCP:
    """Create and configure the Delta Prime MCP server."""
    mcp = FastMCP(
        name="delta-prime",
        instructions=(
            "Delta Prime context management for AI agents. "
            "Use context_store to save memories, knowledge, decisions, and reasoning. "
            "Use context_recall to search and retrieve context. "
            "Use context_link to connect related concepts. "
            "Use context_admin for usage info and provenance."
        ),
    )

    @mcp.tool()
    async def context_store_tool(
        intent: Literal["remember", "assert", "commit", "reflect"],
        content: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        decay_class: str = "standard",
        claims: list[dict[str, Any]] | None = None,
        steps: list[dict[str, Any]] | None = None,
        observation_type: str | None = None,
    ) -> dict[str, Any]:
        """Store context to Delta Prime.

        intent options:
        - remember: Store observations and documents (memory layer)
        - assert: Store claims and facts (knowledge layer)
        - commit: Store decisions and commitments (wisdom layer)
        - reflect: Store reasoning chains (intelligence layer)
        """
        return await context_store.store(
            intent=intent,
            content=content,
            tags=tags,
            metadata=metadata,
            decay_class=decay_class,
            claims=claims,
            steps=steps,
            observation_type=observation_type,
        )

    @mcp.tool()
    async def context_recall_tool(
        query: str | None = None,
        node_ids: list[str] | None = None,
        depth: int = 0,
        layers: list[str] | None = None,
        top_k: int = 10,
        as_of: str | None = None,
        include_reflections: bool = False,
        include_steps: bool = False,
    ) -> dict[str, Any]:
        """Recall context from Delta Prime.

        Provide either query (semantic search) or node_ids (direct fetch).
        Use depth > 0 to traverse graph relationships.
        Use as_of for time-travel queries.
        """
        return await context_recall.recall(
            query=query,
            node_ids=node_ids,
            depth=depth,
            layers=layers,
            top_k=top_k,
            as_of=as_of,
            include_reflections=include_reflections,
            include_steps=include_steps,
        )

    @mcp.tool()
    async def context_link_tool(
        source_id: str,
        target_id: str,
        relation: str,
        metadata: dict[str, Any] | None = None,
        weight: float | None = None,
    ) -> dict[str, Any]:
        """Create a relationship between two context nodes.

        Common relations: RELATES_TO, SUPPORTS, CONTRADICTS, DERIVED_FROM, SUPERSEDES
        """
        return await context_link.link(
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            metadata=metadata,
            weight=weight,
        )

    @mcp.tool()
    async def context_admin_tool(
        action: Literal["whoami", "usage", "provenance", "history"],
        node_id: str | None = None,
        since: str | None = None,
    ) -> dict[str, Any]:
        """Administrative operations.

        Actions:
        - whoami: Get current user and organization info
        - usage: Get usage statistics for current period
        - provenance: Get creation history for a node (requires node_id)
        - history: Get edit history for a node (requires node_id)
        """
        return await context_admin.admin(
            action=action,
            node_id=node_id,
            since=since,
        )

    return mcp
```

- [ ] **Step 2: Create __main__.py**

```python
# src/delta_prime_mcp/__main__.py
"""Entry point for Delta Prime MCP server."""

import sys

import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
)


def main() -> None:
    """Run the Delta Prime MCP server."""
    from delta_prime_mcp.server import create_server

    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify server can be imported**

```bash
cd /home/novusedge/Projects/delta-prime/mcp-client
uv run python -c "from delta_prime_mcp.server import create_server; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "feat: add FastMCP server with tool registration"
```

---

### Task 8: Final Verification

**Files:**
- All files created in previous tasks

- [ ] **Step 1: Install dev dependencies**

```bash
cd /home/novusedge/Projects/delta-prime/mcp-client
uv sync --all-extras
```

- [ ] **Step 2: Run all tests**

```bash
uv run pytest -v
```

Expected: All tests pass

- [ ] **Step 3: Run type checker**

```bash
uv run mypy src
```

Expected: No errors (or only minor ones to fix)

- [ ] **Step 4: Run linter**

```bash
uv run ruff check src tests
```

Expected: No errors

- [ ] **Step 5: Verify CLI entry point**

```bash
uv run delta-prime-mcp --help || uv run python -m delta_prime_mcp --help
```

Expected: Shows help or starts server

- [ ] **Step 6: Final commit with any fixes**

```bash
git add .
git commit -m "chore: final cleanup and verification"
```

- [ ] **Step 7: Tag initial version**

```bash
git tag v0.1.0
```
