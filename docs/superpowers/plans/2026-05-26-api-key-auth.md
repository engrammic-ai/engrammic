# API Key Authentication Specification

**Status:** Draft  
**Date:** 2026-05-26  
**Problem:** OAuth requires interactive browser; blocks CI, agents, and service-to-service usage

## Problem Statement

Current auth via WorkOS OAuth requires a browser flow. This blocks:
- CI/CD pipelines calling Engrammic APIs
- Teammate/subagents without browser access
- Service-to-service integrations
- Automated scripts and cron jobs

## Proposed Solution

Add API key authentication as an alternative to OAuth for programmatic access.

## Design

### Key Structure

```
eng_<silo_prefix>_<random>

Example: eng_strata_a1b2c3d4e5f6g7h8i9j0k1l2m3n4
```

- Prefix `eng_` identifies as Engrammic key
- Silo prefix (first 8 chars of silo name, slugified) aids debugging
- 32-char random suffix (base62)
- Total: ~45 chars

### Storage

**Table: `api_keys`**

```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    silo_id UUID NOT NULL REFERENCES silos(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,           -- Human label ("CI pipeline", "staging agent")
    key_hash VARCHAR(64) NOT NULL,        -- SHA-256 of full key
    key_prefix VARCHAR(12) NOT NULL,      -- First 12 chars for identification
    scopes TEXT[] DEFAULT '{}',           -- Future: granular permissions
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ,               -- NULL = never expires
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    
    CONSTRAINT unique_key_hash UNIQUE (key_hash),
    CONSTRAINT unique_name_per_silo UNIQUE (silo_id, name)
);

CREATE INDEX idx_api_keys_silo ON api_keys(silo_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_api_keys_prefix ON api_keys(key_prefix);
```

**Key points:**
- Store SHA-256 hash only, never plaintext
- Keep prefix for "which key is this?" lookups
- Soft-delete via `revoked_at` for audit trail

### API Endpoints

**Create key (admin only):**

```http
POST /admin/api-keys
Authorization: Bearer <oauth_token>
Content-Type: application/json

{
  "name": "CI pipeline",
  "expires_in_days": 90,    // Optional, null = never
  "scopes": ["read", "write"]  // Future, ignored for now
}
```

Response (only time full key is shown):

```json
{
  "id": "uuid",
  "name": "CI pipeline",
  "key": "eng_strata_a1b2c3d4e5f6g7h8i9j0k1l2m3n4",
  "key_prefix": "eng_strata_a1",
  "expires_at": "2026-08-26T00:00:00Z",
  "created_at": "2026-05-26T10:00:00Z"
}
```

**List keys:**

```http
GET /admin/api-keys
Authorization: Bearer <oauth_token>
```

Returns keys without the secret (only prefix, name, metadata).

**Revoke key:**

```http
DELETE /admin/api-keys/{id}
Authorization: Bearer <oauth_token>
```

Soft-deletes by setting `revoked_at`.

### Authentication Flow

```
1. Client sends request with API key:
   Authorization: Bearer eng_strata_a1b2...
   -- or --
   X-API-Key: eng_strata_a1b2...

2. Auth middleware:
   a. Detect key format (starts with eng_)
   b. Hash the key: sha256(key)
   c. Lookup in api_keys where key_hash = hash AND revoked_at IS NULL
   d. Check expires_at
   e. Update last_used_at (async, don't block request)
   f. Inject silo_id into request context

3. Request proceeds with silo_id from key (same as OAuth flow)
```

### Request Headers

Support both patterns:

```http
# Standard Bearer token (preferred)
Authorization: Bearer eng_strata_a1b2c3...

# X-API-Key header (alternative)
X-API-Key: eng_strata_a1b2c3...
```

If both present, `Authorization` takes precedence.

### Rate Limiting

Per-key rate limits (separate from per-user OAuth limits):

| Tier | Requests/min | Burst |
|------|--------------|-------|
| Default | 60 | 100 |
| High (future) | 300 | 500 |

Track in Redis: `ratelimit:apikey:{key_prefix}:{minute}`

### Security Considerations

1. **Key rotation:** Create new key, update clients, revoke old key
2. **No key retrieval:** Can only see key at creation time
3. **Audit logging:** Log key usage (key_prefix, endpoint, timestamp)
4. **Expiration:** Encourage time-limited keys, warn on long-lived
5. **Silo isolation:** Key is bound to exactly one silo, cannot cross-tenant

### MCP Integration

For MCP server auth, accept API key via:

```json
{
  "mcpServers": {
    "engrammic": {
      "url": "https://api.engrammic.ai/mcp",
      "headers": {
        "Authorization": "Bearer eng_strata_a1b2..."
      }
    }
  }
}
```

Or environment variable:

```bash
ENGRAMMIC_API_KEY=eng_strata_a1b2...
```

### Scopes (Future)

For v1, all keys have full silo access. Future scopes:

| Scope | Access |
|-------|--------|
| `read` | recall, trace, patterns |
| `write` | remember, learn, believe, link |
| `admin` | forget, silo config |

### Migration

No migration needed - additive feature. Existing OAuth continues to work.

## Implementation Plan

1. **Schema + model** (0.5 day)
   - Create migration for api_keys table
   - Add SQLAlchemy model

2. **Admin endpoints** (0.5 day)
   - POST/GET/DELETE /admin/api-keys
   - Key generation utility

3. **Auth middleware** (0.5 day)
   - Detect API key in headers
   - Lookup and validate
   - Inject silo context

4. **Rate limiting** (0.25 day)
   - Redis-based per-key limits

5. **Tests** (0.25 day)
   - Key lifecycle
   - Auth flow
   - Rate limiting

**Total: ~2 days**

## Open Questions

1. **Key length:** 32 random chars enough? (Yes, 62^32 is plenty)
2. **Multiple keys per silo:** Allow? (Yes, for rotation and separation)
3. **Key limit per silo:** Cap at 10? 50? (Start with 10, increase on request)
4. **Expiration default:** Require expiration or allow permanent? (Allow permanent, warn in UI)
