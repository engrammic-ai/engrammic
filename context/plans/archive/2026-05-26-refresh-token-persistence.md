# Refresh Token Persistence

**Status**: Ready for implementation  
**Target**: `engrammic-ai/mcp` client repo  
**Goal**: Eliminate re-auth on IDE restart by persisting and auto-refreshing OAuth tokens

## Problem

When IDE tools (Cursor, VS Code, etc.) restart, the WorkOS sealed session is gone. Users see:
```
Error calling tool 'recall': Bearer token rejected by WorkOS: 
WorkOS session not authenticated: INVALID_SESSION_COOKIE
```

The backend already supports OAuth tokens with refresh - the MCP client just needs to use them.

## Current State (in mcp repo)

- `credentials.py`: Stores `access_token` + `refresh_token` in `~/.engrammic/credentials.json` (0600 perms)
- `client.py`: Has 401 retry with refresh, but:
  - Posts JSON to `/v1/oauth/token` - backend expects form data at `/oauth/token`
  - No `expires_at` tracking (waits for 401 instead of proactive refresh)
  - No concurrent refresh protection (mutex)
  - No clock skew buffer

## Tasks

### 1. Fix refresh endpoint format

**File**: `src/engrammic_mcp/client.py`

The backend expects form-encoded data per OAuth spec:
```python
# Current (broken)
resp = await client.post(
    f"{self.base_url}/v1/oauth/token",
    json={"refresh_token": self._refresh_token},
)

# Fixed
resp = await client.post(
    f"{self.base_url}/oauth/token",
    data={
        "grant_type": "refresh_token",
        "refresh_token": self._refresh_token,
    },
)
```

### 2. Add expires_at tracking

**File**: `src/engrammic_mcp/credentials.py`

Store expiration time:
```python
def store_credentials(
    access_token: str,
    refresh_token: str,
    expires_in: int,  # seconds
    path: Path,
) -> None:
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at.isoformat(),
        "stored_at": datetime.now(UTC).isoformat(),
    }
    # ... rest unchanged
```

### 3. Proactive refresh on startup

**File**: `src/engrammic_mcp/client.py`

Check expiration before first request, with 60s buffer for clock skew:
```python
REFRESH_BUFFER_SECONDS = 60

def _load_oauth_credentials(self) -> None:
    creds = load_credentials(self.settings.credentials_path)
    if not creds:
        return
    
    self._token = creds.get("access_token")
    self._refresh_token = creds.get("refresh_token")
    
    expires_at_str = creds.get("expires_at")
    if expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str)
        if expires_at <= datetime.now(UTC) + timedelta(seconds=REFRESH_BUFFER_SECONDS):
            # Token expired or expiring soon - refresh proactively
            logger.debug("Access token expired/expiring, will refresh on first request")
            self._token = None  # Force refresh path
```

### 4. Add refresh mutex

**File**: `src/engrammic_mcp/client.py`

Prevent concurrent refresh from multiple IDE windows:
```python
import asyncio
from contextlib import asynccontextmanager
from filelock import FileLock  # Add to dependencies

_refresh_lock = asyncio.Lock()

async def _refresh_access_token(self) -> bool:
    async with _refresh_lock:
        # Re-check after acquiring lock (another task may have refreshed)
        creds = load_credentials(self.settings.credentials_path)
        if creds and creds.get("access_token") != self._token:
            # Another process refreshed - reload and return
            self._token = creds.get("access_token")
            self._refresh_token = creds.get("refresh_token")
            return True
        
        # Actually refresh
        # ... existing refresh logic
```

For cross-process safety (multiple IDE windows), also use a file lock:
```python
def _get_lock_path(self) -> Path:
    return self.settings.credentials_path.with_suffix(".lock")

async def _refresh_access_token(self) -> bool:
    lock = FileLock(self._get_lock_path(), timeout=10)
    async with _refresh_lock:  # In-process lock
        with lock:  # Cross-process lock
            # ... refresh logic
```

### 5. Better error handling

**File**: `src/engrammic_mcp/client.py`

Distinguish auth failures from network errors:
```python
async def _refresh_access_token(self) -> bool:
    try:
        client = get_http_client()
        resp = await client.post(...)
        
        if resp.status_code == 200:
            # Success - update tokens
            return True
        elif resp.status_code in (400, 401):
            # Token revoked or invalid - need re-auth
            logger.warning("Refresh token invalid, re-authentication required")
            self._clear_credentials()
            return False
        else:
            # Server error - don't clear creds, might be temporary
            logger.warning("Refresh failed with server error", status=resp.status_code)
            return False
            
    except httpx.NetworkError as e:
        logger.warning("Network error during refresh", error=str(e))
        return False

def _clear_credentials(self) -> None:
    self._token = None
    self._refresh_token = None
    if self.settings.credentials_path.exists():
        self.settings.credentials_path.unlink()
```

### 6. Update login flow to capture expires_in

**File**: `src/engrammic_mcp/cli.py` (or wherever OAuth callback is handled)

When receiving tokens from OAuth flow, pass `expires_in`:
```python
# After successful OAuth exchange
store_credentials(
    access_token=tokens["access_token"],
    refresh_token=tokens["refresh_token"],
    expires_in=tokens.get("expires_in", 3600),  # Default 1 hour
    path=settings.credentials_path,
)
```

## Dependencies

Add to `pyproject.toml`:
```toml
filelock = "^3.0"
```

## Testing

1. **Unit tests**: Mock HTTP responses, verify refresh flow
2. **Integration test**: 
   - Login, store creds
   - Wait for expiry (or mock time)
   - Make request, verify refresh happens
   - Verify new creds stored
3. **Concurrent test**: Two processes, both try to refresh simultaneously

## Rollout

1. Implement in mcp repo
2. Release new version
3. Existing users: First request after upgrade may 401 once if their current token is expired (refresh will fix it)

## Not in scope (deferred)

- Keychain integration (file storage is fine for now, properly permissioned)
- Multi-account support
- Server URL keying (single server assumption)
